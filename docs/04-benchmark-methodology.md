# 04 — Benchmark methodology

This document exists because benchmarking is where portfolio projects lose
credibility. The code can be excellent and the numbers still worthless.

A knowledgeable reader is looking for a reason to disbelieve you. Give them none.

## The governing rule

> **Never tune the benchmark to flatter the system.**

If a configuration makes the new approach look bad, that configuration still gets
published. Publishing the case where your work barely helps is what makes the
cases where it helps a lot believable.

## Metrics, defined precisely

Define these once, in code, and never compute a published number by hand.

| Metric | Definition |
|---|---|
| **TTFT** | Time to first token. Request arrival → first token sent to the client. This is what a user feels as "did it hang". |
| **TPOT** | Time per output token, after the first. Measured as `(e2e − ttft) / (output_tokens − 1)`. This is what a user feels as reading speed. |
| **E2E latency** | Arrival → final token. |
| **Throughput** | Total output tokens produced per second, across all requests, over the measurement window. |
| **Goodput at SLO** | Requests per second completed **while meeting a stated latency target**. This is the honest headline number. |
| **Slot utilisation** | Occupied batch slots ÷ maximum batch slots, averaged over every scheduler step. |
| **KV utilisation** | Blocks in use ÷ total blocks, averaged over steps. |

**Report goodput, not peak throughput, as the headline.** Peak throughput is
achieved by letting the queue grow without limit, which means terrible latency.
Any system can win that contest by being slow. The question a real engineer asks
is: *how much load can I serve while keeping p99 under my target?*

Pick an SLO up front and state it. Suggested for CPU GPT-2: **p99 TTFT under
2 seconds, p99 TPOT under 200 ms.** Choose your own if these are unreasonable
once you see real numbers, but choose before you measure, not after.

## Workload design

The workload decides the answer. So it must be stated openly and it must not be
cherry-picked.

### Arrival pattern

Use **Poisson arrivals** at a configured rate. Do not fire all requests at once.

Why: a burst of N simultaneous requests is not how real traffic behaves, and it
happens to make continuous batching look artificially good, because the queue is
always full. Poisson arrivals produce a realistic mix of busy and idle moments,
which is a harder and fairer test.

Sweep the arrival rate from well under capacity to well over it. The interesting
part of every chart is near and past saturation.

### Length distributions — this is the important one

**Output length variance is the single biggest lever on your results.** Be
scrupulous here.

If every request generates exactly 100 tokens, static batching wastes almost
nothing, and continuous batching looks barely better. If output lengths vary
wildly, static batching wastes most of its slots, and continuous batching looks
spectacular.

Both results are true. They are answers to different questions. So run **three**
workloads and publish all three:

| Workload | Prompt length | Output length | What it shows |
|---|---|---|---|
| **A — uniform** | 128 fixed | 128 fixed | The near-worst case for continuous batching. Publish it first. |
| **B — realistic** | lognormal, median ~200 | lognormal, median ~150 | The main result. |
| **C — high variance** | lognormal, median ~200 | 20 to 800, heavy tail | The best case. Label it clearly as such. |

Publishing A before C is the move. It shows you are not selling something.

State the exact distribution parameters and the random seed in the results page.

### Warmup and measurement

- Run a warmup phase and **discard it**. First-run effects, lazy imports and
  memory allocator warmup will otherwise pollute your numbers.
- Measure over a fixed window long enough to include many full request
  lifecycles. Aim for at least a few hundred completed requests per data point.
- Run every configuration **at least three times** with different seeds. Report
  the median and show the spread.
- Record machine details: CPU model, core count, RAM, PyTorch version, thread
  settings. Put them on the page.

### Thread pinning

Set `torch.set_num_threads()` explicitly and record the value. Leaving it to the
default means your numbers change with the machine and cannot be compared across
runs. Set the same value for every variant.

## The ablation table

This is the single most important artifact on the results page. One combined
"we are 5x faster" number is easy to produce and easy to distrust. A table
showing what each mechanism contributed **on its own** is much harder to fake and
much more informative.

Build it like this. Every row is a real configuration your code can actually run.

| Config | KV cache | Batching | Paging | Goodput @ SLO | Slot util | KV util |
|---|---|---|---|---|---|---|
| M0 naive | none | none | — | | | |
| M1 | contiguous | none | — | | | |
| M2 | contiguous | static | — | | | |
| M3 | contiguous | continuous | — | | | |
| M4 | paged | static | yes | | | |
| M4 full | paged | continuous | yes | | | |

Note rows M4-static and M3: those two isolate paging and continuous batching
from each other. Keeping the code able to run those combinations is worth the
small extra effort, because that pair of rows is what proves the ablation is
real.

Fill this in for workload B, and repeat it in an appendix for A and C.

## Sweeps worth publishing

- **Block size sweep** (M4): 4, 8, 16, 32, 64 tokens per block. Small blocks
  waste less memory but add more indirection. Show the curve and the optimum.
- **KV memory budget sweep** (M4): throughput as a function of cache memory. This
  chart makes the paging argument visually obvious.
- **Max batch size sweep**: where CPU compute becomes the limit instead of memory
  bandwidth. This is the chart that honestly shows the CPU ceiling.
- **Long-prefill stall** (M3): inject one 800-token prompt into a steady load and
  chart the latency spike other requests experience. Then, if you do chunked
  prefill as a stretch goal, chart the same thing again after.

## Writing the limitations section

Collect every `# LIMITATION:` comment from the code and turn them into plain
sentences. At minimum this section must say:

- CPU only. Absolute numbers are far below any GPU system, and the batching gains
  are smaller than GPU literature reports, because a CPU hits its compute limit
  before its memory-bandwidth limit.
- Paged attention gathers into a temporary buffer instead of using a fused
  kernel. A production system would not do this.
- Padded batches, not ragged. Some compute is wasted.
- GPT-2 only. No grouped-query attention, no RoPE, no quantisation.
- Prefill is not chunked (unless the stretch goal was completed), so a long
  prompt stalls the decode loop. Quantified in the stall chart.
- Single process, single machine.

Do not bury this section. Put it on the main page. Every experienced reader goes
looking for it, and finding it well-written is a stronger signal than any chart.

## Reproducibility

`./scripts/run_bench.sh` must regenerate every JSON file in `results/`, and
`scripts/plot.py` must regenerate every chart from those files. (As built: `make site` regenerates the results page, whose charts are drawn from the same files; `plot.py` is an optional PNG export.)

Commit the JSON to git. Then a reader can check your charts against your raw
data without running anything at all. Very few portfolio projects do this, and it
takes about twenty minutes to set up.

---

# As run (2026-09-19)

What the published numbers (`results/bench/` and the results page built from `site-src/`) actually were, including every
place this differs from the spec above. Nothing here was tuned after seeing a result.

## Definitions as implemented (`bench/report.go`)

- **TTFT** is measured from the request's *scheduled* arrival, not from when the generator got
  round to sending it, so generator lateness cannot hide server latency. Maximum send lateness is
  recorded in every run.
- **TPOT** = `(e2e - ttft) / (output_tokens - 1)`, as specified.
- **Goodput** = requests that completed and met both per-request SLOs (TTFT <= 2 s, TPOT <= 200 ms),
  divided by the arrival window. Rejected, errored and unfinished requests count against it (SLO
  attainment is over everything offered). The SLOs are the doc's suggestion, fixed before measuring.
- **Throughput** = output tokens of completed requests divided by `max(window, last completion)`.
- Percentiles use `round(p/100 * (n-1))`, identically in Go and Python.

## Deviations from the spec, and why

| Spec | As run | Why |
|---|---|---|
| Prompt/output medians ~200/~150; C output 20-800 | medians 64/48 (B), 64/40 with heavier tail capped at 400 (C), fixed 64/64 (A) | full-size runs were too slow on CPU to repeat three times for every configuration. Shape of the length distribution, which drives the result, is preserved. Decided before measuring (`scripts/workloads.py`) |
| "A few hundred completed requests per data point" | 60-90 offered per run, 30 s arrival window plus 20 s drain | same reason; compensated with 3 seeds (ablation, load curves) or 2 seeds (sweeps) |
| Three seeds for every configuration | sweeps used 2 | run time |
| Unspecified admission policy | queue cap 64 for every variant | uniform across variants; rejections count as SLO failures |
| One offered load | A and B at 3 req/s, C at 2 req/s; load curve 1-8 req/s | offered loads fixed up front; rate 3 comes from the ablation runs and is reused on the curves |
| Ablation KV budget unspecified | 512 MiB, chosen before measuring | a budget where contiguous slots are scarce; the KV-budget sweep and the 2 GiB rows show where it does not matter |
| Prompts | random token ids, `ignore_eos` on every request | output length is exactly the sampled value; batching behaviour depends on lengths, not text |

The Go generator and `scripts/workloads.py` implement the same distributions with different random
number generators, so the request streams differ; the parameters are identical.

## Static baseline is generous on purpose

Finished rows leave the compute (a naive server keeps computing padded finished rows) and tokens are
streamed as produced (most servers return the batch at the end). Continuous batching's gain over
this baseline is therefore conservative.

## Harness problems found and fixed during the run

Documented in `docs/06-build-log.md` (M2 and M6): first-touch page faults inflating one variant's
numbers (memory is now touched before the timer starts); two copies of the runner sharing a port
(a lock now prevents it); abandoned requests continuing to run on the server (requests are now
cancelled on disconnect). Everything measured before the last fix was deleted and re-run.

## Machine drift

This desktop's speed varies between sessions. On 2026-09-19 the same configuration and seed measured
224.8 tok/s during the benchmark and about 107 tok/s hours later, on both the old and new code. Runs
within a session are comparable; runs across sessions are not. The benchmark interleaves nothing
across configurations (each configuration runs to completion in turn), so slow drift inside the two
hours could bias one configuration; the repeated seeds show the within-configuration spread, which
is reported as min-max next to every median.

## Reproducing

`make bench` (about 2 hours), then `make site` (or its alias `make results`). The script is resumable and refuses to run twice
at once. `results/bench/machine.json` records the hardware, `torch` version and thread count (4,
identical for every variant).
