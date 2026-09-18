"""M1: same prompt and output length as M0, now with our own KV cache.

Writes results/m1_kvcache.json. Warmup discarded, median of REPEATS.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench_m0 import FIXTURE, OUT_TOKENS, REPEATS, cpu_name  # noqa: E402
from engine.metrics import write_json  # noqa: E402
from engine.model_runner import ModelRunner  # noqa: E402


def main() -> None:
    fx = json.loads((ROOT / "tests" / "fixtures" / f"{FIXTURE}.json").read_text())
    m0 = json.loads((ROOT / "results" / "m0_baseline.json").read_text())
    runner = ModelRunner()
    prompt = fx["prompt_token_ids"]
    runner.generate_cached(prompt, 5)  # warmup, discarded
    runs = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        out = runner.generate_cached(prompt, OUT_TOKENS, ignore_eos=True)
        dt = time.perf_counter() - t0
        runs.append({"tokens": len(out), "seconds": dt, "tok_per_s": len(out) / dt})
    tps = [r["tok_per_s"] for r in runs]
    med = statistics.median(tps)
    write_json(ROOT / "results" / "m1_kvcache.json", {
        "milestone": "M1", "description": "own KV cache, contiguous, batch size 1",
        "prompt_tokens": len(prompt), "max_new_tokens": OUT_TOKENS, "repeats": runs,
        "median_tok_per_s": med, "min_tok_per_s": min(tps), "max_tok_per_s": max(tps),
        "m0_median_tok_per_s": m0["median_tok_per_s"],
        "speedup_vs_m0": med / m0["median_tok_per_s"],
        "machine": {**m0["machine"], "cpu": cpu_name()},
    })
    print(f"median {med:.2f} tok/s, speedup vs M0 {med / m0['median_tok_per_s']:.1f}x  {[round(t, 1) for t in tps]}")


if __name__ == "__main__":
    main()
