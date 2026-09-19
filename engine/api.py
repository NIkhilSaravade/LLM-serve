"""FastAPI layer: turns HTTP requests into Request objects and streams tokens back.

Endpoints
  POST /generate      stream=true returns newline-delimited JSON:
                        {"token_id": 123, "text": " the"}   one line per token (text may be ""
                                                             while a multi-byte character is incomplete)
                        {"done": true, "finish_reason": "length", "n_tokens": 64}
  GET  /health        liveness: the process is up and the scheduler thread is alive
  GET  /ready         readiness: model loaded and warmed (503 otherwise)
  GET  /metrics       Prometheus exposition (see engine/observability.py)
  GET  /version       git sha, model, torch, effective config
  GET  /stats         JSON engine summary read by the benchmark harness (POST /stats/reset)

Run ONE worker per process: the engine owns the model and the KV pool, so scale out by
replicas, not by uvicorn workers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request as HttpRequest
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from engine.config import EngineConfig
from engine.detokenizer import IncrementalDetokenizer
from engine.observability import Observability, version_info
from engine.request import Request
from engine.scheduler import Engine, EngineLoop

log = logging.getLogger("llm_serve")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))  # one JSON object per line
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


class GenerateIn(BaseModel):
    prompt: str | None = None
    prompt_token_ids: list[int] | None = None   # the load generator sends ids directly
    max_new_tokens: int = 32
    ignore_eos: bool = False                    # benchmarks fix the output length exactly
    stream: bool = False


def create_app(cfg: EngineConfig | None = None) -> FastAPI:
    state: dict = {"ready": False}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = cfg or EngineConfig.from_env()
        engine = Engine(c)
        # Warm up before reporting ready: first-call costs (allocator, kernels) must not land
        # on a user request. Then forget the warmup in the counters.
        engine.generate_greedy([1, 2, 3], 2)
        engine.sched.metrics.reset()
        loop = EngineLoop(engine)
        loop.start()
        state.update(cfg=c, engine=engine, loop=loop, t_reset=time.perf_counter(),
                     obs=Observability(engine, loop), ready=True)
        log.info(json.dumps({"event": "ready", **version_info(engine)}))
        yield
        # On SIGTERM uvicorn stops accepting and lets in-flight requests finish before this runs;
        # the Kubernetes preStop sleep gives the load balancer time to stop routing first.
        state["ready"] = False
        loop.stop()

    app = FastAPI(title="llm-serve", lifespan=lifespan)

    # ------------------------------------------------------------------ operations
    @app.get("/health")
    def health() -> dict:
        if "loop" not in state or not state["loop"]._thread.is_alive():
            raise HTTPException(503, "scheduler thread is dead")
        return {"ok": True, "config": state["cfg"].to_dict()}

    @app.get("/ready")
    def ready():
        if not state["ready"]:
            raise HTTPException(503, "not ready")
        return {"ready": True}

    @app.get("/version")
    def version() -> dict:
        return version_info(state["engine"])

    @app.get("/metrics")
    def prometheus() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(state["obs"].registry).decode(),
                                 media_type=CONTENT_TYPE_LATEST)

    @app.get("/stats")
    def stats() -> dict:
        eng: Engine = state["engine"]
        return eng.sched.metrics.summary(time.perf_counter() - state["t_reset"])

    @app.post("/stats/reset")
    def reset() -> dict:
        state["engine"].sched.metrics.reset()
        state["t_reset"] = time.perf_counter()
        return {"ok": True}

    # ------------------------------------------------------------------ inference
    @app.post("/generate")
    async def generate(body: GenerateIn, http: HttpRequest):
        obs: Observability = state["obs"]
        engine: Engine = state["engine"]
        tok = engine.runner.tokenizer
        if body.prompt_token_ids is not None:
            ids = body.prompt_token_ids
        elif body.prompt is not None:
            ids = tok.encode(body.prompt)
        else:
            raise HTTPException(400, "give prompt or prompt_token_ids")
        if not 0 < len(ids) < 1024:
            raise HTTPException(400, "prompt must have 1..1023 tokens")

        rid = http.headers.get("x-request-id") or uuid.uuid4().hex
        headers = {"X-Request-ID": rid}
        loop = asyncio.get_running_loop()
        events: asyncio.Queue = asyncio.Queue()
        req = Request(rid, ids, body.max_new_tokens, ignore_eos=body.ignore_eos)
        # The sink runs on the engine thread; hop back onto the event loop safely.
        req.sink = lambda t, fin: loop.call_soon_threadsafe(events.put_nowait, (t, fin))
        eff_max = min(body.max_new_tokens, 1024 - len(ids))
        manager = getattr(engine, "manager", None)
        if manager is not None and not manager.fits_ever(len(ids), eff_max):
            obs.requests.labels("too_large").inc()
            raise HTTPException(413, "request needs more KV memory than the server has")
        if not state["loop"].submit(req):
            obs.requests.labels("rejected").inc()
            raise HTTPException(429, "overloaded: queue is full", headers={"Retry-After": "1", **headers})
        detok = IncrementalDetokenizer(tok)

        async def events_iter():
            n = 0
            while True:
                t, fin = await events.get()
                n += 1
                yield t, detok.push(t), fin, n
                if fin:
                    return

        def finish(status: str) -> None:
            if status == "ok":
                obs.observe_finished(req)
            else:
                obs.requests.labels(status).inc()
            first = req.first_token_time
            log.info(json.dumps({
                "event": "request_done", "request_id": rid, "status": status,
                "prompt_tokens": len(ids), "output_tokens": len(req.output_token_ids),
                "ttft_s": round(first - req.arrival_time, 4) if first else None,
                "e2e_s": round(req.finish_time - req.arrival_time, 4) if req.finish_time else None,
                "preemptions": req.preempt_count}))

        if body.stream:
            async def ndjson():
                status = "error"
                try:
                    async for t, text, fin, n in events_iter():
                        yield json.dumps({"token_id": t, "text": text}) + "\n"
                        if fin:
                            tail = detok.flush()
                            if tail:
                                yield json.dumps({"token_id": None, "text": tail}) + "\n"
                            yield json.dumps({"done": True, "finish_reason": req.finish_reason,
                                              "n_tokens": n}) + "\n"
                            status = "ok"
                except asyncio.CancelledError:
                    status = "cancelled"
                    raise
                finally:
                    # Client went away: stop spending capacity and KV memory on a response
                    # nobody will read.
                    if not req.finished:
                        req.cancelled = True
                        status = "cancelled"
                    finish(status)
            return StreamingResponse(ndjson(), media_type="application/x-ndjson", headers=headers)

        text, status = "", "error"
        try:
            async for _, piece, fin, _ in events_iter():
                text += piece
            status = "ok"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            if not req.finished:
                req.cancelled = True
                status = "cancelled"
            finish(status)
        text += detok.flush()
        return JSONResponse({"request_id": rid, "token_ids": req.output_token_ids, "text": text,
                             "finish_reason": req.finish_reason,
                             "ttft_s": req.first_token_time - req.arrival_time,
                             "e2e_s": req.finish_time - req.arrival_time}, headers=headers)

    return app


app = create_app()
