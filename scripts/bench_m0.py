"""M0 baseline: tokens/sec for a fixed prompt and output length, no KV cache.

Writes results/m0_baseline.json. Warmup run is discarded; median of REPEATS reported.
"""
from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.metrics import write_json  # noqa: E402
from engine.model_runner import ModelRunner  # noqa: E402

FIXTURE = "short_5_out20"  # fixed prompt; output length fixed by max_new_tokens
OUT_TOKENS = 100
REPEATS = 3


def cpu_name() -> str:
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor).Name"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return out or platform.processor()
    except Exception:
        return platform.processor()


def main() -> None:
    fx = json.loads((ROOT / "tests" / "fixtures" / f"{FIXTURE}.json").read_text())
    runner = ModelRunner()
    prompt = fx["prompt_token_ids"]

    runner.generate_greedy(prompt, 5)  # warmup, discarded
    runs = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        out = runner.generate_greedy(prompt, OUT_TOKENS)
        dt = time.perf_counter() - t0
        runs.append({"tokens": len(out), "seconds": dt, "tok_per_s": len(out) / dt})

    tps = [r["tok_per_s"] for r in runs]
    write_json(ROOT / "results" / "m0_baseline.json", {
        "milestone": "M0",
        "description": "no KV cache; full-sequence recompute every step; batch size 1",
        "prompt_tokens": len(prompt),
        "max_new_tokens": OUT_TOKENS,
        "repeats": runs,
        "median_tok_per_s": statistics.median(tps),
        "min_tok_per_s": min(tps),
        "max_tok_per_s": max(tps),
        "machine": {
            "cpu": cpu_name(), "logical_cores": __import__("os").cpu_count(),
            "torch": torch.__version__, "torch_threads": runner.num_threads,
            "python": platform.python_version(), "os": platform.platform(),
        },
    })
    print(f"median {statistics.median(tps):.2f} tok/s  (runs: {[round(t, 2) for t in tps]})")


if __name__ == "__main__":
    main()
