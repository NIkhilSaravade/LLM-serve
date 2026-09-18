"""Fails if throughput drops >20% below the value recorded in results/perf_guard.json.

Catches the classic accident of 'fixing' correctness with an expensive copy in the hot loop.
Timing on a shared desktop is noisy (M0 saw ±30%), so this takes the best of 3 runs.
Re-record with `python scripts/bench_offline.py m2` after an intentional change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_static_throughput_has_not_regressed():
    rec = ROOT / "results" / "perf_guard.json"
    if not rec.exists():
        pytest.skip("no recorded value yet")
    from bench_offline import run_closed
    from engine.config import EngineConfig
    from engine.model_runner import ModelRunner
    from workloads import make_requests

    baseline = json.loads(rec.read_text())["tok_per_s"]
    runner = ModelRunner()
    reqs = make_requests("B", 8, seed=99)
    cfg = EngineConfig(batching="static", max_batch=4)
    run_closed(runner, cfg, reqs[:2])  # warmup
    best = max(run_closed(runner, cfg, reqs)["throughput_tok_per_s"] for _ in range(3))
    assert best >= 0.8 * baseline, f"{best:.1f} tok/s vs recorded {baseline:.1f}"
