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

## Calibration on the GitHub runner (4 vCPU, container limited to 3 CPUs), 2026-09-19

The runner is about 3 times slower than the development machine, so its operating point is different. Same image on
both sides (A/A) with the `perf-calibrate` workflow:

| Offered load | Goodput ratio | Throughput ratio | What it showed |
|---|---|---|---|
| 4 req/s (the script default; the first release run used it by mistake) | 1.00 | 0.999 | far above the knee: SLO attainment only 0.20, throughput 61 tok/s, so goodput barely moves. Not a useful operating point |
| 1 req/s | 1.00 | 0.994 | far below the knee: attainment 1.00 and throughput just equals the offered load (43.5 tok/s, +/-1%), so a slower engine would look identical. The gate would be blind here |
| **2 req/s (chosen)** | **0.976** | **1.001** | attainment 0.95 to 1.00: right at the knee, where a slower engine starts losing goodput |

The rate was picked from A/A runs only, before any candidate was judged. The threshold stays 0.85: at the chosen rate
identical images differ by at most 2.4%.

Synthetic slowdown on the runner (candidate limited to 2 CPUs instead of 3), 3 pairs:

| | baseline median | candidate median | ratio |
|---|---|---|---|
| goodput (req/s) | 1.64 | 0.24 | **0.146** |
| throughput (tok/s) | 74.7 | 47.5 | **0.636** |

Verdict: **fail**, on both metrics. The gate is calibrated and can fail on the machine it actually runs on.

## What this does not tell you

* Only 4 A/A pairs and 3 slowdown pairs were measured on the runner. Runner performance varies between days and
  hosts, so occasional false alarms are possible; the artifact uploaded by every release run records the numbers.
* If a runner is ever too slow to serve the offered load at all, the gate reports "inconclusive" and fails closed
  instead of passing.
* A slowdown smaller than about 15% is not detectable with 3 pairs. More pairs tighten this at the cost of CI time.
* It measures one CPU shape at one load level. The full benchmark under `results/bench` remains the source of every
  published number.
