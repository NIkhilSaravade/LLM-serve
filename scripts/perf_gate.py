"""Performance regression gate: candidate image vs the last released image, same machine, same load.

    python scripts/perf_gate.py --baseline IMG --candidate IMG [--pairs 3] [--out results/perf_gate/x.json]

Why it is built this way (each choice comes from a problem measured earlier in this project):
  * RELATIVE, not absolute. A shared runner's absolute speed drifts by 10% or more between runs, so a fixed
    "goodput >= X" would flake. Both images run on the same machine within minutes of each other.
  * INTERLEAVED (B C C B B C ...). Drift over time hits both sides equally instead of one side.
  * MEDIAN of several runs, not one run.
  * Two metrics: goodput at the SLO (a latency regression) and token throughput (a capacity regression). Near
    the knee both fall when the engine gets slower.
  * The threshold is fixed BEFORE a candidate is judged, from an A/A run (same image as both sides) that
    measures the noise floor. It is never adjusted after a candidate fails. See results/perf_gate/README.md.
  * FAIL CLOSED: if the baseline itself produced almost no goodput, the comparison means nothing, so the gate
    fails as "inconclusive" instead of passing.

LIMITATION: this detects a relative slowdown on one CPU shape at one load level. It does not replace the full
benchmark (results/bench), which is where the published numbers come from.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 18000
NAME = "perf-gate-server"


def sh(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def bench_binary() -> str:
    exe = ROOT / "bench" / ("llm-bench.exe" if os.name == "nt" else "llm-bench")
    if not exe.exists():
        subprocess.run(["go", "build", "-o", exe.name, "."], cwd=ROOT / "bench", check=True)
    return str(exe)


def start(image: str, cpus: str) -> None:
    sh("docker", "rm", "-f", NAME, check=False)
    sh("docker", "run", "-d", "--name", NAME, "--cpus", cpus, "--memory", "4g",
       "-e", "LLM_SERVE_THREADS=" + cpus.split(".")[0], "-p", f"{PORT}:8000", image)
    for _ in range(180):
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ready", timeout=2).status == 200:
                return
        except Exception:
            time.sleep(1)
    logs = sh("docker", "logs", NAME, check=False)
    raise RuntimeError(f"{image} never became ready\n{logs.stdout}{logs.stderr}")


def stop() -> None:
    sh("docker", "rm", "-f", NAME, check=False)


def one_run(image: str, side: str, idx: int, a: argparse.Namespace, binary: str, out_dir: Path) -> dict:
    start(image, a.candidate_cpus if side == "candidate" and a.candidate_cpus else a.cpus)
    try:
        out = out_dir / f"{side}_{idx}.json"
        subprocess.run(
            [binary, "-url", f"http://127.0.0.1:{PORT}", "-label", side, "-workload", a.workload,
             "-rate", str(a.rate), "-seed", str(a.seed), "-duration", str(a.duration),
             "-drain", str(a.drain), "-out", str(out)],
            check=True, capture_output=True, text=True)
        d = json.loads(out.read_text())
        return {"side": side, "run": idx, "goodput": d["goodput_req_per_s"],
                "throughput": d["throughput_tok_per_s"], "attainment": d["slo_attainment"],
                "offered": d["offered"], "rejected": d["rejected"], "errors": d["errors"],
                "ttft_p99": d["ttft_s"].get("p99")}
    finally:
        stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--workload", default="B")
    ap.add_argument("--rate", type=float, default=4.0)
    ap.add_argument("--duration", type=float, default=25)
    ap.add_argument("--drain", type=float, default=15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cpus", default="4", help="CPU limit for the server container (also its torch threads)")
    ap.add_argument("--candidate-cpus", default="",
                    help="give ONLY the candidate a different CPU limit: a synthetic slowdown to prove the gate can fail")
    ap.add_argument("--min-ratio", type=float, default=0.85,
                    help="fail if candidate median / baseline median falls below this, for either metric")
    ap.add_argument("--min-baseline-goodput", type=float, default=0.3,
                    help="below this the baseline is too weak to compare against: inconclusive")
    ap.add_argument("--out", default="results/perf_gate/latest.json")
    ap.add_argument("--report-only", action="store_true", help="always exit 0 (used for A/A calibration)")
    a = ap.parse_args()

    out_path = ROOT / a.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir = out_path.parent / (out_path.stem + "_raw")
    raw_dir.mkdir(exist_ok=True)
    binary = bench_binary()

    runs: list[dict] = []
    sides = {"baseline": a.baseline, "candidate": a.candidate}
    for i in range(a.pairs):
        # ABBA ordering: alternate which side goes first so a steady drift cancels out.
        order = ["baseline", "candidate"] if i % 2 == 0 else ["candidate", "baseline"]
        for side in order:
            r = one_run(sides[side], side, i, a, binary, raw_dir)
            runs.append(r)
            print(f"  pair {i} {side:9s} goodput {r['goodput']:.3f} req/s  throughput {r['throughput']:.1f} tok/s"
                  f"  attainment {r['attainment']:.2f}  rejected {r['rejected']} errors {r['errors']}", flush=True)

    def med(side: str, key: str) -> float:
        return statistics.median(r[key] for r in runs if r["side"] == side)

    def spread(side: str, key: str) -> float:
        v = [r[key] for r in runs if r["side"] == side]
        return (max(v) - min(v)) / statistics.median(v) if statistics.median(v) else float("nan")

    base_g, cand_g = med("baseline", "goodput"), med("candidate", "goodput")
    base_t, cand_t = med("baseline", "throughput"), med("candidate", "throughput")
    verdict = "pass"
    reasons: list[str] = []
    if base_g < a.min_baseline_goodput:
        verdict = "inconclusive"
        reasons.append(f"baseline goodput {base_g:.3f} < {a.min_baseline_goodput}: offered load is too far above "
                       "what this machine can serve, so the comparison says nothing. Recalibrate the rate.")
    else:
        rg, rt = cand_g / base_g, cand_t / base_t
        if rg < a.min_ratio:
            verdict = "fail"
            reasons.append(f"goodput ratio {rg:.3f} < {a.min_ratio}")
        if rt < a.min_ratio:
            verdict = "fail"
            reasons.append(f"throughput ratio {rt:.3f} < {a.min_ratio}")

    result = {
        "verdict": verdict, "reasons": reasons, "baseline": a.baseline, "candidate": a.candidate,
        "config": {k: getattr(a, k) for k in ("workload", "rate", "duration", "drain", "seed", "pairs", "cpus",
                                              "min_ratio", "min_baseline_goodput", "candidate_cpus")},
        "median": {"baseline": {"goodput": base_g, "throughput": base_t},
                   "candidate": {"goodput": cand_g, "throughput": cand_t}},
        "ratio": {"goodput": cand_g / base_g if base_g else None,
                  "throughput": cand_t / base_t if base_t else None},
        "spread_within_side": {"baseline_goodput": spread("baseline", "goodput"),
                               "candidate_goodput": spread("candidate", "goodput"),
                               "baseline_throughput": spread("baseline", "throughput"),
                               "candidate_throughput": spread("candidate", "throughput")},
        "runs": runs,
    }
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("verdict", "reasons", "ratio", "median")}, indent=2))
    if a.report_only:
        return 0
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
