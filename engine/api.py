"""FastAPI layer. M0: blocking, one request at a time."""
from __future__ import annotations

import threading
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

from engine.metrics import request_metrics
from engine.model_runner import ModelRunner
from engine.request import Request

app = FastAPI(title="llm-serve")
_runner: ModelRunner | None = None
# LIMITATION: M0 serialises requests behind a lock. Real concurrency arrives with
# the scheduler in M2/M3.
_lock = threading.Lock()


def get_runner() -> ModelRunner:
    global _runner
    if _runner is None:
        _runner = ModelRunner()
    return _runner


class GenerateIn(BaseModel):
    prompt: str
    max_new_tokens: int = 32


@app.post("/generate")
def generate(body: GenerateIn) -> dict:
    runner = get_runner()
    ids = runner.tokenizer.encode(body.prompt)
    req = Request(request_id=uuid.uuid4().hex, prompt_token_ids=ids,
                  max_new_tokens=body.max_new_tokens)
    with _lock:
        runner.run(req)
    m = request_metrics(req)
    return {
        "request_id": req.request_id,
        "token_ids": req.output_token_ids,
        "text": runner.tokenizer.decode(req.output_token_ids),
        "ttft_s": m.ttft, "tpot_s": m.tpot, "e2e_s": m.e2e,
    }
