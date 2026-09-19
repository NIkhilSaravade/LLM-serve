"""Load results/bench/**.json (one file per Go load-generator run) and aggregate over seeds.

Everything published on the site and in the charts comes through here, so no number is ever
computed by hand (docs/04-benchmark-methodology.md).
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "results" / "bench"


def load_runs() -> list[dict]:
    runs = []
    for p in sorted(BENCH.rglob("*_s*.json")):
        d = json.loads(p.read_text())
        d["_exp"] = p.parent.name
        d["_file"] = str(p.relative_to(ROOT))
        sm = d.get("server_metrics") or {}
        d["slot_util"] = sm.get("slot_utilisation")
        d["kv_util"] = sm.get("kv_utilisation")
        d["kv_eff"] = sm.get("kv_token_efficiency")
        d["preemptions"] = sm.get("preemptions", 0)
        d["peak_batch"] = sm.get("peak_batch")
        runs.append(d)
    return runs


def machine() -> dict:
    p = BENCH / "machine.json"
    return json.loads(p.read_text()) if p.exists() else {}


METRICS = ("goodput_req_per_s", "throughput_tok_per_s", "slo_attainment", "slot_util", "kv_util",
           "kv_eff", "preemptions", "peak_batch", "completed", "rejected", "incomplete", "offered")


def _nested(d: dict, key: str) -> float | None:
    v = d.get(key)
    return v if isinstance(v, (int, float)) else None


def aggregate(runs: list[dict]) -> dict[tuple, dict]:
    """(cfg, workload, rate) -> {metric: {median, min, max, values}, n_seeds}, pooled over
    experiments so the ablation's rate-3 runs also appear on the load curves."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in runs:
        groups[(r["label"], r["workload"], r["rate_req_per_s"])].append(r)
    out = {}
    for key, rs in groups.items():
        agg: dict = {"n_seeds": len({r["seed"] for r in rs}), "runs": rs}
        for m in METRICS:
            vals = [v for v in (_nested(r, m) for r in rs) if v is not None]
            if vals:
                agg[m] = {"median": statistics.median(vals), "min": min(vals), "max": max(vals), "values": vals}
        for m in ("ttft_s", "tpot_s", "e2e_s", "itl_s"):
            for q in ("p50", "p95", "p99"):
                vals = [r[m][q] for r in rs if r.get(m) and r["completed"] > 0]
                if vals:
                    agg[f"{m}_{q}"] = {"median": statistics.median(vals), "min": min(vals),
                                       "max": max(vals), "values": vals}
        out[key] = agg
    return out
