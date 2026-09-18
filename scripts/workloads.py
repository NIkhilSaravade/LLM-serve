"""Workload definitions, shared by the Python milestone benchmarks.

bench/main.go implements the SAME distributions with the same parameters for the
published HTTP benchmarks. Change one, change both.

SCOPE NOTE (deviation from docs/04-benchmark-methodology.md, decided before measuring):
the doc suggests prompt/output medians of ~200/~150 tokens. On a CPU these make one
data point take far too long to repeat 3x across every configuration, so all lengths
are scaled down by roughly 3x. Relative results depend on the *shape* of the length
distribution, which is preserved.

  A uniform    prompt 64,                          output 64 fixed
  B realistic  prompt lognormal(median 64, s=0.5), output lognormal(median 48, s=0.7)
  C highvar    prompt lognormal(median 64, s=0.5), output lognormal(median 40, s=1.2)

Lengths are clipped: prompts to [8, 512], outputs B to [4, 256], C to [8, 400].
Prompt tokens are random ids; requests set ignore_eos so output length is exactly the
sampled value (the same practice vLLM's benchmark uses).
"""
from __future__ import annotations

import math
import random

WORKLOADS = {
    "A": dict(prompt=("fixed", 64), output=("fixed", 64)),
    "B": dict(prompt=("lognormal", 64, 0.5, 8, 512), output=("lognormal", 48, 0.7, 4, 256)),
    "C": dict(prompt=("lognormal", 64, 0.5, 8, 512), output=("lognormal", 40, 1.2, 8, 400)),
}
VOCAB = 50257


def _sample(rng: random.Random, spec: tuple) -> int:
    if spec[0] == "fixed":
        return int(spec[1])
    _, median, sigma, lo, hi = spec
    return int(min(hi, max(lo, round(rng.lognormvariate(math.log(median), sigma)))))


def make_requests(workload: str, n: int, seed: int) -> list[tuple[list[int], int]]:
    """Return n (prompt_token_ids, max_new_tokens) pairs."""
    rng = random.Random(seed)
    w = WORKLOADS[workload]
    out = []
    for _ in range(n):
        p, o = _sample(rng, w["prompt"]), _sample(rng, w["output"])
        out.append(([rng.randrange(0, VOCAB - 1) for _ in range(p)], o))
    return out
