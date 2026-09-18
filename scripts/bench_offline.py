"""In-process milestone benchmarks (no HTTP). The published HTTP numbers come from bench/.

    python scripts/bench_offline.py m2
"""
from __future__ import annotations

import os
import random
import sys
import threading
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
from engine.scheduler import Engine, EngineLoop  # noqa: E402

SLO_TTFT_S, SLO_TPOT_S = 2.0, 0.2  # chosen before measuring (docs/04 suggestion)


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


def run_open_loop(runner: ModelRunner, cfg: EngineConfig, reqs: list[tuple[list[int], int]],
                  rate: float, seed: int, inject: tuple[float, list[int], int] | None = None,
                  timeout: float = 240.0) -> dict:
    """Open-loop Poisson arrivals at `rate` req/s against the engine loop on its own thread.

    `inject=(at_seconds, prompt, max_new)` adds one extra request at a fixed time (used for
    the long-prefill stall experiment). Per-token timestamps are kept so inter-token gaps of
    the *other* requests can be examined.
    """
    eng = Engine(cfg, runner)
    loop = EngineLoop(eng)
    loop.start()
    rng = random.Random(seed)
    sched: list[tuple[float, list[int], int, bool]] = []
    t = 0.0
    for p, n in reqs:
        t += rng.expovariate(rate)
        sched.append((t, p, n, False))
    if inject:
        sched.append((inject[0], inject[1], inject[2], True))
        sched.sort(key=lambda x: x[0])
    records, lock, done = [], threading.Lock(), threading.Event()
    remaining = [len(sched)]

    def make_sink(rec):
        def sink(tok, fin):
            rec["times"].append(time.perf_counter())
            if fin:
                with lock:
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        done.set()
        return sink

    start = time.perf_counter()
    for at, p, n, injected in sched:
        delay = start + at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        r = Request(uuid.uuid4().hex, p, n, ignore_eos=True)
        rec = {"req": r, "times": [], "injected": injected}
        r.sink = make_sink(rec)
        records.append(rec)
        loop.submit(r)
    finished = done.wait(timeout)
    end = time.perf_counter()
    loop.stop()

    ok, gaps = 0, []
    for rec in records:
        r, ts = rec["req"], rec["times"]
        if not r.finished:
            continue
        if not rec["injected"]:
            ttft = r.first_token_time - r.arrival_time
            tpot = ((r.finish_time - r.first_token_time) / (len(ts) - 1)) if len(ts) > 1 else 0.0
            ok += ttft <= SLO_TTFT_S and tpot <= SLO_TPOT_S
            gaps += [(ts[i], ts[i] - ts[i - 1]) for i in range(1, len(ts))]
    wall = end - start
    m = eng.sched.metrics.summary(wall)
    return {"config": cfg.to_dict(), "rate_req_per_s": rate, "seed": seed, "completed_all": finished,
            "wall_s": wall, "goodput_req_per_s": ok / wall,
            "slo": {"ttft_s": SLO_TTFT_S, "tpot_s": SLO_TPOT_S}, **m,
            "max_inter_token_gap_s": max((g for _, g in gaps), default=None),
            "itl_p99_s": sorted(g for _, g in gaps)[int(0.99 * (len(gaps) - 1))] if gaps else None,
            "_gaps": [(t - start, g) for t, g in gaps]}


def bench_m3() -> None:
    runner = ModelRunner()
    n, seed = 40, 7
    reqs = make_requests("B", n, seed=1)
    run_open_loop(runner, EngineConfig(max_batch=2), reqs[:4], rate=4.0, seed=0)  # warmup
    rows = []
    for rate in (1.0, 2.0, 3.0, 4.0):
        for mode in ("static", "continuous"):
            r = run_open_loop(runner, EngineConfig(backend="contiguous", batching=mode,
                                                    max_batch=16), reqs, rate, seed)
            r.pop("_gaps")
            rows.append(r)
            print(f"rate={rate} {mode:10s} tput={r['throughput_tok_per_s']:6.1f} "
                  f"goodput={r['goodput_req_per_s']:.2f} slot={r['slot_utilisation']:.2f} "
                  f"ttft p50/p99={r['ttft_p50_s']:.2f}/{r['ttft_p99_s']:.2f} "
                  f"tpot p99={r['tpot_p99_s']:.3f}")

    # Long-prefill stall: same steady load, with and without one 800-token prompt injected.
    steady = make_requests("B", 30, seed=3)
    rng = random.Random(5)
    long_prompt = [rng.randrange(0, 50000) for _ in range(800)]
    stall = {}
    for label, inj in (("baseline", None), ("with_800_token_prompt", (8.0, long_prompt, 16))):
        r = run_open_loop(runner, EngineConfig(backend="contiguous", batching="continuous",
                                               max_batch=16), steady, 2.0, 11, inject=inj)
        stall[label] = r
        print(f"stall {label}: max ITL gap={r['max_inter_token_gap_s']:.3f}s "
              f"p99 ITL={r['itl_p99_s']:.3f}s")
    t0 = time.perf_counter()
    eng = Engine(EngineConfig(max_batch=2), runner)
    eng.generate_greedy(long_prompt, 1)
    prefill_800 = time.perf_counter() - t0
    write_json(ROOT / "results" / "m3_continuous.json", {
        "milestone": "M3", "workload": "B (scaled)", "requests": n, "arrival": "open-loop Poisson",
        "static_vs_continuous": rows, "long_prefill_stall": {
            "note": "steady load 2 req/s; one 800-token prompt injected at t=8s",
            "prefill_800_tokens_s": prefill_800, **{k: {kk: vv for kk, vv in v.items()}
                                                      for k, v in stall.items()}},
        "machine": machine(runner)})


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


def bench_m3_saturated() -> None:
    """Slot utilisation only means something when there is always work waiting, so measure it
    with a closed-loop burst large enough to keep the queue non-empty, both modes."""
    import json
    runner = ModelRunner()
    reqs = make_requests("B", 96, seed=1)
    run_closed(runner, EngineConfig(max_batch=2), reqs[:4])  # warmup
    rows = []
    for mode in ("static", "continuous"):
        r = run_closed(runner, EngineConfig(backend="contiguous", batching=mode, max_batch=8), reqs)
        rows.append(r)
        print(f"saturated {mode:10s} tput={r['throughput_tok_per_s']:.1f} "
              f"slot={r['slot_utilisation']:.3f} pad={r['attn_padding_waste']:.2f}")
    path = ROOT / "results" / "m3_continuous.json"
    d = json.loads(path.read_text())
    d["saturated_closed_loop"] = {"note": "96 requests of workload B submitted at t=0, max_batch=8",
                                  "rows": rows}
    write_json(path, d)


if __name__ == "__main__":
    {"m2": bench_m2, "m3": bench_m3, "m3sat": bench_m3_saturated}[sys.argv[1]]()
