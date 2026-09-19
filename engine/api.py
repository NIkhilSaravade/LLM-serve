"""FastAPI layer: turns HTTP requests into Request objects and streams tokens back.

Protocol for POST /generate with stream=true is newline-delimited JSON:
  {"token_id": 123, "text": " the"}      one line per token (text may be "" while a
                                          multi-byte character is still incomplete)
  {"done": true, "finish_reason": "length", "n_tokens": 64}
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine.config import EngineConfig
from engine.detokenizer import IncrementalDetokenizer
from engine.request import Request
from engine.scheduler import Engine, EngineLoop


class GenerateIn(BaseModel):
    prompt: str | None = None
    prompt_token_ids: list[int] | None = None   # the load generator sends ids directly
    max_new_tokens: int = 32
    ignore_eos: bool = False                    # benchmarks fix the output length exactly
    stream: bool = False


def create_app(cfg: EngineConfig | None = None) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = cfg or EngineConfig.from_env()
        engine = Engine(c)
        loop = EngineLoop(engine)
        loop.start()
        state.update(cfg=c, engine=engine, loop=loop, t_reset=time.perf_counter())
        yield
        loop.stop()

    app = FastAPI(title="llm-serve", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "config": state["cfg"].to_dict()}

    @app.get("/metrics")
    def metrics() -> dict:
        eng: Engine = state["engine"]
        return eng.sched.metrics.summary(time.perf_counter() - state["t_reset"])

    @app.post("/metrics/reset")
    def reset() -> dict:
        state["engine"].sched.metrics.reset()
        state["t_reset"] = time.perf_counter()
        return {"ok": True}

    @app.post("/generate")
    async def generate(body: GenerateIn):
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

        loop = asyncio.get_running_loop()
        events: asyncio.Queue = asyncio.Queue()
        req = Request(uuid.uuid4().hex, ids, body.max_new_tokens, ignore_eos=body.ignore_eos)
        # The sink runs on the engine thread; hop back onto the event loop safely.
        req.sink = lambda t, fin: loop.call_soon_threadsafe(events.put_nowait, (t, fin))
        eff_max = min(body.max_new_tokens, 1024 - len(ids))
        manager = getattr(engine, "manager", None)
        if manager is not None and not manager.fits_ever(len(ids), eff_max):
            raise HTTPException(413, "request needs more KV memory than the server has")
        if not state["loop"].submit(req):
            raise HTTPException(429, "overloaded: queue is full", headers={"Retry-After": "1"})
        detok = IncrementalDetokenizer(tok)

        async def events_iter():
            n = 0
            while True:
                t, fin = await events.get()
                n += 1
                yield t, detok.push(t), fin, n
                if fin:
                    return

        if body.stream:
            async def ndjson():
                async for t, text, fin, n in events_iter():
                    yield json.dumps({"token_id": t, "text": text}) + "\n"
                    if fin:
                        tail = detok.flush()
                        if tail:
                            yield json.dumps({"token_id": None, "text": tail}) + "\n"
                        yield json.dumps({"done": True, "finish_reason": req.finish_reason,
                                          "n_tokens": n}) + "\n"
            return StreamingResponse(ndjson(), media_type="application/x-ndjson")

        text = ""
        async for _, piece, fin, _ in events_iter():
            text += piece
        text += detok.flush()
        return {"request_id": req.request_id, "token_ids": req.output_token_ids, "text": text,
                "finish_reason": req.finish_reason,
                "ttft_s": req.first_token_time - req.arrival_time,
                "e2e_s": req.finish_time - req.arrival_time}

    return app


app = create_app()
