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
    from engine.model_runner import ModelRunner
    return ModelRunner()


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_matches_reference(name, engine):
    fx = FIXTURES[name]
    out = engine.generate_greedy(fx["prompt_token_ids"], max_new_tokens=fx["max_new_tokens"])
    assert out == fx["expected_token_ids"]  # exact list equality


@pytest.mark.parametrize("batch", sorted(BATCHES))
def test_batch_independence(batch, engine):
    # Written now, live from M2: a request's output must not depend on its neighbours.
    if not hasattr(engine, "generate_batch"):
        pytest.skip("batching arrives in M2")
    fxs = [FIXTURES[n] for n in BATCHES[batch]]
    outs = engine.generate_batch([f["prompt_token_ids"] for f in fxs],
                                 [f["max_new_tokens"] for f in fxs])
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"]
