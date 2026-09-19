# Performance gate: calibration record

`scripts/perf_gate.py` compares a candidate image with the last `stable` image on the same machine and fails the
release on a relative regression. This file records how its settings were chosen. The rule is that the threshold is
fixed from an A/A run (the same image on both sides, so any difference is noise) **before** any candidate is judged,
and is never changed after a candidate fails.

## Settings

| Setting | Value | Why |
|---|---|---|
| Workload | B (realistic), seed 1 | the workload the published ablation is built on |
| Offered load | 4 req/s locally, 3 req/s on the CI runner | near the knee of the goodput curve, where a slower engine visibly loses goodput. Well below the knee a slower engine still serves everything and the gate would be blind |
| Window | 25 s arrivals + 15 s drain | long enough for a stable goodput, short enough for 6 runs in about 10 minutes |
| Pairs | 3, order alternated (B C, C B, B C) | drift over time hits both sides equally |
| Statistic | median of the runs on each side | one bad run does not decide |
| Metrics | goodput at the SLO, and token throughput | goodput catches a latency regression, throughput a capacity regression |
| Threshold | candidate median / baseline median >= **0.85** for both | see below |
| Inconclusive | baseline goodput < 0.3 req/s fails the gate | if the baseline barely serves anything the comparison means nothing, so it fails closed |

## A/A calibration, local machine (2026-09-19)

Same image on both sides, 4 pairs, 4 CPUs per container, `aa_local.json`:

| | goodput (req/s) | throughput (tok/s) |
|---|---|---|
| baseline median | 2.34 | 176.3 |
| candidate median | 2.20 | 168.1 |
| ratio | **0.94** | **0.95** |
| spread within one side (max-min over median) | 0% to 7% | 5% |

Noise floor: identical builds differed by about 5 to 6%. A threshold of 0.85 leaves about 2.5 times that margin, so
noise alone should not fail a release, while a 15% loss does.

## Can it fail? Synthetic regression (local, 2026-09-19)

The candidate was given half the CPU (2 instead of 4), which is a large slowdown made on purpose, `synthetic_regression_local.json`:

| | baseline median | candidate median | ratio |
|---|---|---|---|
| goodput (req/s) | 2.30 | 0.70 | **0.30** |
| throughput (tok/s) | 171.7 | 56.8 | **0.33** |

Verdict: **fail**. The gate distinguishes a real regression from noise by a wide margin.

## What this does not tell you

* The CI runner is a different, slower, noisier machine. Its noise floor has not been measured yet. Run the
  `perf-calibrate` workflow (Actions tab) to measure it there before relying on the threshold, and record the result
  here. If 3 req/s turns out to be far above what the runner can serve, the gate reports "inconclusive" instead of
  passing.
* A slowdown smaller than about 15% is not detectable with 3 pairs. More pairs tighten this at the cost of CI time.
* It measures one CPU shape at one load level. The full benchmark under `results/bench` remains the source of every
  published number.
