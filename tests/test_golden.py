"""Golden tests: token IDs must match the HuggingFace reference exactly.

Compare token IDs, never decoded strings. No tolerance, ever (docs/03-correctness.md).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixtures() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text())
            for p in sorted(FIXTURE_DIR.glob("*.json")) if p.stem != "batches"}


FIXTURES = load_fixtures()
BATCHES = (json.loads((FIXTURE_DIR / "batches.json").read_text())
           if (FIXTURE_DIR / "batches.json").exists() else {})


@pytest.fixture(scope="session")
def engine():
    """The bare model runner: M0 naive path and M1 cached path."""
    from engine.model_runner import ModelRunner
    return ModelRunner()


def make_engine(runner, **cfg):
    from engine.config import EngineConfig
    from engine.scheduler import Engine
    return Engine(EngineConfig(**cfg), runner)


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
