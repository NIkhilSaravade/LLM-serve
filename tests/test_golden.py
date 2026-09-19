"""Golden tests: token IDs must match the HuggingFace reference exactly.

Compare token IDs, never decoded strings. No tolerance, ever (docs/03-correctness.md).
"""
from __future__ import annotations

import json

import pytest
from conftest import BATCHES, FIXTURES, make_engine


# --------------------------------------------------------------------------- M0 / M1
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_matches_reference(name, engine):
    fx = FIXTURES[name]
    out = engine.generate_greedy(fx["prompt_token_ids"], max_new_tokens=fx["max_new_tokens"])
    assert out == fx["expected_token_ids"]  # exact list equality


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_cached_matches_reference(name, engine):
    """M1: our own forward pass + our own KV cache, single sequence."""
    fx = FIXTURES[name]
    out = engine.generate_cached(fx["prompt_token_ids"], max_new_tokens=fx["max_new_tokens"])
    assert out == fx["expected_token_ids"]


# --------------------------------------------------------------------------- M2 static
@pytest.fixture(scope="session")
def static_engine(engine):
    return make_engine(engine, backend="contiguous", batching="static", max_batch=8)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_static_single_matches_reference(name, static_engine):
    fx = FIXTURES[name]
    out = static_engine.generate_greedy(fx["prompt_token_ids"], fx["max_new_tokens"])
    assert out == fx["expected_token_ids"]


@pytest.mark.parametrize("batch", sorted(BATCHES))
def test_batch_independence(batch, static_engine):
    """A request's output must not depend on what else was in the batch."""
    fxs = [FIXTURES[n] for n in BATCHES[batch]]
    outs = static_engine.generate_batch([f["prompt_token_ids"] for f in fxs],
                                        [f["max_new_tokens"] for f in fxs])
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"]


# --------------------------------------------------------------------------- M3 continuous
@pytest.fixture(scope="session")
def cont_engine(engine):
    return make_engine(engine, backend="contiguous", batching="continuous", max_batch=8)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_continuous_single_matches_reference(name, cont_engine):
    fx = FIXTURES[name]
    assert cont_engine.generate_greedy(fx["prompt_token_ids"],
                                       fx["max_new_tokens"]) == fx["expected_token_ids"]


@pytest.mark.parametrize("batch", sorted(BATCHES))
def test_continuous_batch_independence(batch, cont_engine):
    fxs = [FIXTURES[n] for n in BATCHES[batch]]
    outs = cont_engine.generate_batch([f["prompt_token_ids"] for f in fxs],
                                      [f["max_new_tokens"] for f in fxs])
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"]


# Arrival iterations chosen so neighbours join while others are mid-generation and leave
# while others are still running. max_batch smaller than the request count forces waiting.
ARRIVALS = [0, 0, 3, 5, 8, 13, 21, 34]


@pytest.mark.parametrize("max_batch", [2, 3, 5])
@pytest.mark.parametrize("backend_kwargs", [dict(backend="contiguous")],
                         ids=["contiguous"])
def test_join_and_leave_mid_generation(max_batch, backend_kwargs, engine):
    eng = make_engine(engine, batching="continuous", max_batch=max_batch, **backend_kwargs)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    specs = [(f["prompt_token_ids"], f["max_new_tokens"], a) for f, a in zip(fxs, ARRIVALS)]
    outs = eng.run_schedule(specs)
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"], fx["name"]


def test_detokenizer_holds_back_partial_utf8(engine):
    from engine.detokenizer import IncrementalDetokenizer
    tok = engine.tokenizer
    text = "naïve café 😀 日本語 done"
    ids = tok.encode(text)
    d = IncrementalDetokenizer(tok)
    pieces = [d.push(i) for i in ids]
    assert "�" not in "".join(pieces)          # never emits half a character
    assert "".join(pieces) + d.flush() == tok.decode(ids)
    assert any(p == "" for p in pieces)             # multi-token characters were held back


def test_streamed_text_matches_token_decode(engine):
    from fastapi.testclient import TestClient
    from engine.api import create_app
    from engine.config import EngineConfig
    with TestClient(create_app(EngineConfig(max_batch=4))) as c:
        lines = c.post("/generate", json={"prompt": "Emoji test 😀 and 日本語:",
                                          "max_new_tokens": 24, "stream": True}).text.splitlines()
    msgs = [json.loads(x) for x in lines]
    assert msgs[-1]["done"] is True
    ids = [m["token_id"] for m in msgs if m.get("token_id") is not None]
    streamed = "".join(m["text"] for m in msgs if "text" in m)
    assert streamed == engine.tokenizer.decode(ids)
