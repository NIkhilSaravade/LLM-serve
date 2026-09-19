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
from workloads import make_requests  # noqa: E402

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
        if not loop.submit(r):          # refused by admission control: never runs
            with lock:
                remaining[0] -= 1
                if remaining[0] == 0:
                    done.set()
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


def bench_m5() -> None:
    """Overload: offered load from well under capacity to far past it, at a tight KV budget.

    Three systems, same workload, same seeds:
      m5      paged + preemption (optimistic admission) + admission control (queue cap 32)
      m4      paged, worst-case-commit admission, unbounded queue (no admission control)
      m3      contiguous slots, unbounded queue
    """
    runner = ModelRunner()
    reqs = make_requests("B", 60, seed=1)
    run_open_loop(runner, EngineConfig(max_batch=2), reqs[:4], rate=4.0, seed=0)  # warmup
    systems = {
        "m5_paged_preempt_admission": dict(backend="paged", preemption=True, max_queue=32),
        "m4_paged_reserve": dict(backend="paged", preemption=False),
        "m3_contiguous": dict(backend="contiguous", preemption=False),
    }
    rows = []
    for rate in (1.0, 2.0, 4.0, 6.0, 8.0, 12.0):
        for name, kw in systems.items():
            r = run_open_loop(runner, EngineConfig(batching="continuous", max_batch=32,
                                                    kv_budget_mib=128, block_size=16, **kw),
                              reqs, rate, seed=13, timeout=180)
            r.pop("_gaps")
            r["system"] = name
            rows.append(r)
            print(f"rate={rate:4.1f} {name:28s} done={r['requests']:2d} rej={r['rejected']:2d} "
                  f"preempt={r['preemptions']:3d} tput={r['throughput_tok_per_s']:6.1f} "
                  f"goodput={r['goodput_req_per_s']:.2f} "
                  f"ttft p99={r['ttft_p99_s'] or 0:5.2f} e2e p99={r['e2e_p99_s'] or 0:6.2f} "
                  f"all_done={r['completed_all']}")
    write_json(ROOT / "results" / "m5_overload.json", {
        "milestone": "M5", "workload": "B (scaled)", "requests_per_point": len(reqs),
        "arrival": "open-loop Poisson", "kv_budget_mib": 128, "max_batch": 32, "block_size": 16,
        "rows": rows, "machine": machine(runner)})


def bench_m4() -> None:
    """Paged vs contiguous KV under a fixed memory budget, plus the block-size sweep.
    Closed-loop burst (keeps work waiting, so memory is what limits concurrency)."""
    runner = ModelRunner()
    reqs = make_requests("B", 96, seed=1)
    run_closed(runner, EngineConfig(max_batch=2), reqs[:4])  # warmup
    keys = ("throughput_tok_per_s", "peak_batch", "kv_utilisation", "kv_token_efficiency",
            "slot_utilisation", "wall_s")

    import statistics

    def one(**kw) -> dict:
        r = run_closed(runner, EngineConfig(batching="continuous", max_batch=32, **kw), reqs)
        return {**{k: r[k] for k in keys}, "config": r["config"]}

    def sweep(points: list[dict], reps: int = 3) -> list[dict]:
        """Repetitions are interleaved across points (rep-major) so slow drift in machine state
        hits every point equally. A single run of one config varied 195-292 tok/s."""
        runs: list[list[dict]] = [[] for _ in points]
        for rep in range(reps):
            for i, kw in enumerate(points):
                runs[i].append(one(**kw))
        out = []
        for kw, rs in zip(points, runs):
            tps = [r["throughput_tok_per_s"] for r in rs]
            out.append({**kw, "throughput_median_tok_per_s": statistics.median(tps),
                        "throughput_runs": tps,
                        # memory metrics are deterministic; identical across repetitions
                        **{k: rs[0][k] for k in ("peak_batch", "kv_utilisation",
                                                 "kv_token_efficiency", "slot_utilisation")}})
            print(kw, f"median={statistics.median(tps):.1f} runs={[round(t) for t in tps]} "
                      f"peak_batch={rs[0]['peak_batch']} kv_eff={rs[0]['kv_token_efficiency']:.2f}")
        return out

    budget_curve = sweep([dict(backend=b, kv_budget_mib=m, block_size=16)
                          for m in (128, 256, 512, 1024, 2048) for b in ("contiguous", "paged")])
    block_sweep = sweep([dict(backend="paged", kv_budget_mib=256, block_size=bs)
                         for bs in (4, 8, 16, 32, 64)])
    write_json(ROOT / "results" / "m4_paged.json", {
        "milestone": "M4", "workload": "B (scaled)", "requests": len(reqs), "repetitions": 3,
        "arrival": "closed-loop burst", "max_batch": 32,
        "admission": "worst-case commit (no preemption)",
        "budget_curve": budget_curve, "block_size_sweep_at_256MiB": block_sweep,
        "machine": machine(runner)})


if __name__ == "__main__":
    {"m2": bench_m2, "m3": bench_m3, "m3sat": bench_m3_saturated, "m4": bench_m4,
     "m5": bench_m5}[sys.argv[1]]()
