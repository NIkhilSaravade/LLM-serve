"""In-process milestone benchmarks (no HTTP). The published HTTP numbers come from bench/.

    python scripts/bench_offline.py m2
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bench_m0 import cpu_name  # noqa: E402
from workloads import WORKLOADS, make_requests  # noqa: E402

import torch  # noqa: E402
from engine.config import EngineConfig  # noqa: E402
from engine.metrics import write_json  # noqa: E402
from engine.model_runner import ModelRunner  # noqa: E402
from engine.request import Request  # noqa: E402
from engine.scheduler import Engine  # noqa: E402


def machine(runner: ModelRunner) -> dict:
    return {"cpu": cpu_name(), "logical_cores": os.cpu_count(), "torch": torch.__version__,
            "torch_threads": runner.num_threads}


def run_closed(runner: ModelRunner, cfg: EngineConfig, reqs: list[tuple[list[int], int]]) -> dict:
    """Closed-loop burst: every request is submitted at t=0 and the engine runs to completion.

    A burst keeps the queue full, which flatters continuous batching; it is used here only
    for the throughput-vs-batch-size curve. Open-loop Poisson numbers come from bench/.
    """
    eng = Engine(cfg, runner)
    t0 = time.perf_counter()
    for i, (p, n) in enumerate(reqs):
        r = Request(uuid.uuid4().hex, p, n, ignore_eos=True)
        eng.sched.submit(r)
    while eng.sched.has_work():
        eng.sched.step()
    wall = time.perf_counter() - t0
    return {"config": cfg.to_dict(), "wall_s": wall, **eng.sched.metrics.summary(wall)}


def bench_m2() -> None:
    runner = ModelRunner()
    reqs = make_requests("B", 32, seed=1)
    run_closed(runner, EngineConfig(batching="static", max_batch=2), reqs[:4])  # warmup
    curve = []
    for mb in (1, 2, 4, 8, 16):
        r = run_closed(runner, EngineConfig(backend="contiguous", batching="static",
                                            max_batch=mb), reqs)
        curve.append(r)
        print(f"static max_batch={mb:2d}: {r['throughput_tok_per_s']:7.1f} tok/s  "
              f"slot_util={r['slot_utilisation']:.2f}  pad_waste={r['attn_padding_waste']:.2f}")
    write_json(ROOT / "results" / "m2_static.json", {
        "milestone": "M2", "workload": "B (scaled, see scripts/workloads.py)",
        "requests": len(reqs), "seed": 1, "arrival": "closed-loop burst",
        "total_output_tokens": sum(n for _, n in reqs), "curve": curve,
        "machine": machine(runner)})

    # Small fixed benchmark used by tests/test_perf_guard.py (docs/03: fail if >20% slower).
    guard_reqs = make_requests("B", 8, seed=99)
    tps = [run_closed(runner, EngineConfig(batching="static", max_batch=4), guard_reqs)
           ["throughput_tok_per_s"] for _ in range(3)]
    write_json(ROOT / "results" / "perf_guard.json", {
        "note": "static, max_batch=4, workload B seed 99, 8 requests; best of 3",
        "tok_per_s": max(tps), "runs": tps})
    print("perf guard:", max(tps))


if __name__ == "__main__":
    {"m2": bench_m2}[sys.argv[1]]()
