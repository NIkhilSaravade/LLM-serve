"""Emit site-src/src/data.json from results/, for the React results page.

Every number on the page comes from this file, and this file comes only from the raw run files
(results/bench/**.json) and the milestone results (results/m*.json). Nothing is typed by hand.
The limitations list is extracted from the `# LIMITATION:` comments in engine/*.py so it cannot
drift from the code.

    python scripts/build_site.py     # writes the data
    npm --prefix site-src run build  # typechecks and builds the page into site/ (git-ignored)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import ROOT, aggregate, load_runs, machine  # noqa: E402
from workloads import WORKLOADS  # noqa: E402

OUT = ROOT / "site-src" / "src" / "data.json"
RATES = {"A": 3, "B": 3, "C": 2}
SYSTEMS = ["m0_naive", "m2_static", "m3_continuous", "m5_full"]
ROWS = [  # key, label, kv cache, batching, paging, what this row adds over the previous one
    ("m0_naive", "Naive", "none", "none", "no", "Recomputes the whole sequence every token."),
    ("m1_kv_only", "KV cache", "contiguous", "none", "no", "Stores keys and values instead of recomputing them."),
    ("m2_static", "Static batching", "contiguous", "static", "no", "Runs many requests per step, but only admits a new batch when the last one has fully drained."),
    ("m3_continuous", "Continuous batching", "contiguous", "continuous", "no", "Refills a freed slot on the very next step."),
    ("m4_static_paged", "Static + paged", "paged", "static", "yes", "Isolates paging: same batching as static, memory in fixed-size blocks."),
    ("m4_full", "Continuous + paged", "paged", "continuous", "yes", "Both mechanisms together."),
    ("m5_full", "+ preemption", "paged", "continuous", "yes", "Admits optimistically and evicts and recomputes when memory runs out."),
]


def stat(agg: dict | None, metric: str, nd: int = 3):
    if not agg or metric not in agg:
        return None
    a = agg[metric]
    return {"median": round(a["median"], nd), "min": round(a["min"], nd), "max": round(a["max"], nd)}


def limitations() -> list[dict]:
    found = []
    for p in sorted((ROOT / "engine").glob("*.py")):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            m = re.search(r"#\s*LIMITATION:\s*(.*)", ln)
            if not m:
                continue
            text = [m.group(1).strip()]
            for nxt in lines[i + 1:]:
                if re.match(r"\s*#\s?(?!LIMITATION)", nxt) and nxt.strip() != "#":
                    text.append(nxt.strip().lstrip("#").strip())
                else:
                    break
            found.append({"file": p.name, "text": " ".join(text)})
    return found


def stall(runs: list[dict]) -> dict:
    """Per-0.25 s maximum inter-token gap seen by ordinary requests (seed 1), and the median
    worst gap over all seeds."""
    out: dict = {"series": {}, "worst_gap_s": {}}
    for label in ("stall_baseline", "stall_injected"):
        rs = [r for r in runs if r["label"] == label and r.get("itl_events")]
        worst = sorted(max(g for _, g in r["itl_events"]) for r in rs)
        out["worst_gap_s"][label] = worst[len(worst) // 2] if worst else None
        seed1 = next((r for r in rs if r["seed"] == 1), None)
        bins: dict[int, float] = {}
        if seed1:
            for t, g in seed1["itl_events"]:
                b = int(t / 0.25)
                bins[b] = max(bins.get(b, 0.0), g)
        out["series"][label] = [[round(b * 0.25, 2), round(g, 4)] for b, g in sorted(bins.items())]
    return out


def _loc(patterns: list[str]) -> int:
    n = 0
    for pat in patterns:
        for p in ROOT.glob(pat):
            if p.is_file() and "node_modules" not in p.parts and "__pycache__" not in p.parts:
                n += sum(1 for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip())
    return n


def facts() -> dict:
    """Counted from the repository, never typed: what a reader can check for themselves."""
    import subprocess

    import yaml

    tests = None
    try:  # the collected test count, excluding the wall-clock guard (same as `make test`)
        out = subprocess.run([sys.executable, "-m", "pytest", "--co", "-q", "-m", "not perf"], cwd=ROOT,
                             capture_output=True, text=True, timeout=180).stdout
        m = re.search(r"(\d+)/?\d* tests? collected", out) or re.search(r"^(\d+) tests? collected", out, re.M)
        tests = int(m.group(1)) if m else None
    except Exception:
        pass
    alerts = yaml.safe_load((ROOT / "deploy" / "prometheus" / "alerts.yml").read_text(encoding="utf-8"))["groups"]
    rules = [r for g in alerts for r in g["rules"]]
    dash = json.loads((ROOT / "deploy" / "grafana" / "dashboards" / "llm-serve.json").read_text(encoding="utf-8"))
    return {
        "tests": tests,
        "loc": {"engine_python": _loc(["engine/*.py"]), "tests_python": _loc(["tests/*.py"]),
                "scripts": _loc(["scripts/*.py", "scripts/*.sh"]), "load_generator_go": _loc(["bench/*.go"]),
                "site_typescript": _loc(["site-src/src/**/*.ts", "site-src/src/**/*.tsx"])},
        "alert_rules": sum(1 for r in rules if "alert" in r),
        "recording_rules": sum(1 for r in rules if "record" in r),
        "dashboard_panels": len(dash["panels"]),
        "k8s_manifests": len(list((ROOT / "deploy" / "k8s").glob("*.yaml"))) + len(list((ROOT / "deploy" / "k8s" / "monitoring").glob("*.yaml"))),
        "docs_pages": len(list((ROOT / "docs").glob("*.md"))),
        "golden_fixtures": len([p for p in (ROOT / "tests" / "fixtures").glob("*.json") if p.stem != "batches"]),
    }


def main() -> None:
    runs = load_runs()
    agg = aggregate(runs)
    res = ROOT / "results"
    m0 = json.loads((res / "m0_baseline.json").read_text())
    m1 = json.loads((res / "m1_kvcache.json").read_text())
    m2 = json.loads((res / "m2_static.json").read_text())
    m3 = json.loads((res / "m3_continuous.json").read_text())
    sat = {r["config"]["batching"]: r for r in m3["saturated_closed_loop"]["rows"]}

    ablation = {}
    for wl, rate in RATES.items():
        ablation[wl] = {"rate": rate, "rows": [
            {"key": k, "label": lab, "kv": kv, "batching": bt, "paging": pg, "adds": adds,
             "goodput": stat(agg.get((k, wl, rate)), "goodput_req_per_s"),
             "throughput": stat(agg.get((k, wl, rate)), "throughput_tok_per_s", 1),
             "ttft_p99": stat(agg.get((k, wl, rate)), "ttft_s_p99"),
             "slot_util": stat(agg.get((k, wl, rate)), "slot_util"),
             "kv_eff": stat(agg.get((k, wl, rate)), "kv_eff"),
             "preemptions": stat(agg.get((k, wl, rate)), "preemptions", 1)}
            for k, lab, kv, bt, pg, adds in ROWS]}

    rates = sorted({k[2] for k in agg if k[1] == "B" and k[0] in SYSTEMS})
    load = {"rates": rates, "systems": {}}
    for s in SYSTEMS:
        load["systems"][s] = [
            {"rate": r, "goodput": stat(agg.get((s, "B", r)), "goodput_req_per_s"),
             "throughput": stat(agg.get((s, "B", r)), "throughput_tok_per_s", 1),
             "ttft_p99": stat(agg.get((s, "B", r)), "ttft_s_p99"),
             "rejected": stat(agg.get((s, "B", r)), "rejected", 1),
             "completed": stat(agg.get((s, "B", r)), "completed", 1)}
            for r in rates if (s, "B", r) in agg]

    budgets = [128, 256, 512, 1024, 2048]
    budget = {"budgets": budgets, "series": {be: [
        {"mib": m, "goodput": stat(agg.get((f"budget{m}_{be}", "B", 3)), "goodput_req_per_s"),
         "throughput": stat(agg.get((f"budget{m}_{be}", "B", 3)), "throughput_tok_per_s", 1),
         "kv_eff": stat(agg.get((f"budget{m}_{be}", "B", 3)), "kv_eff")} for m in budgets]
        for be in ("contiguous", "paged")}}

    maxbatch = [{"max_batch": m, "throughput": stat(agg.get((f"maxbatch{m}", "B", 8)), "throughput_tok_per_s", 1)}
                for m in (1, 2, 4, 8, 16, 32)]
    blocks = [{"block": b, "kv_eff": stat(agg.get((f"block{b}", "B", 3)), "kv_eff"),
               "throughput": stat(agg.get((f"block{b}", "B", 3)), "throughput_tok_per_s", 1)}
              for b in (4, 8, 16, 32, 64)]

    # M4 closed-loop burst (results/m4_paged.json): how much slower paged was once memory stopped binding.
    m4 = json.loads((res / "m4_paged.json").read_text())
    by = {(r["backend"], r["kv_budget_mib"]): r["throughput_median_tok_per_s"] for r in m4["budget_curve"]}
    slow = [round((1 - by[("paged", m)] / by[("contiguous", m)]) * 100) for m in (1024, 2048)]
    burst = {"paged_slowdown_pct_min": min(slow), "paged_slowdown_pct_max": max(slow),
             "paged_speedup_at_128": round(by[("paged", 128)] / by[("contiguous", 128)], 1)}

    full = load["systems"]["m5_full"]
    hi = full[-1]
    lo = next(x for x in full if x["rate"] == 4)
    data = {
        "meta": {
            "machine": machine(), "runs": len(runs), "seeds": 3,
            "slo": {"ttft_s": 2.0, "tpot_s": 0.2},
            "workloads": {k: {"prompt": v["prompt"], "output": v["output"]} for k, v in WORKLOADS.items()},
            "ablation_rates": RATES, "queue_cap": 64, "kv_budget_mib": 512, "threads": 4,
        },
        "milestones": {
            "naive_tok_s": round(m0["median_tok_per_s"], 1), "kv_tok_s": round(m1["median_tok_per_s"], 1),
            "kv_speedup": round(m1["speedup_vs_m0"], 1),
            "static16_tok_s": round(m2["curve"][-1]["throughput_tok_per_s"], 0),
            "sat_static_tok_s": round(sat["static"]["throughput_tok_per_s"], 0),
            "sat_cont_tok_s": round(sat["continuous"]["throughput_tok_per_s"], 0),
            "sat_static_util": round(sat["static"]["slot_utilisation"], 2),
            "sat_cont_util": round(sat["continuous"]["slot_utilisation"], 2),
            "padding_waste_cont": round(sat["continuous"]["attn_padding_waste"], 2),
        },
        "ablation": ablation, "load": load, "budget": budget, "maxbatch": maxbatch, "blocks": blocks,
        "overload": {"p99_ttft_at_4": lo["ttft_p99"]["median"], "p99_ttft_at_max": hi["ttft_p99"]["median"],
                     "max_rate": hi["rate"], "rejected_at_max": hi["rejected"]["median"],
                     "completed_at_max": hi["completed"]["median"]},
        "m4_burst": burst,
        "facts": facts(),
        "stall": stall(runs),
        "limitations": limitations(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB) from {len(runs)} runs")


if __name__ == "__main__":
    main()
