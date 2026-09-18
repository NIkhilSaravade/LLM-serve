# 06 — Build log

**Current milestone: M3**

---

## How to use this file

Add a short entry every working session. Five minutes, no polish. Three lines is
fine.

Why bother: at the end of the project this log becomes the technical write-up,
and the write-up is often what people read before they read any code. It is the
cheapest leverage in the whole project.

Also, when something breaks at M4 that you already solved at M1, this is where
the answer is.

### Template

```markdown
### YYYY-MM-DD — <milestone> — <short title>

**Goal today:**

**What I built:**

**What broke, and why:**

**Number:** (throughput, latency, utilisation — whatever moved)

**Next:**
```

### What makes a good entry

Write down the **wrong** mental model you had, not just the fix. "I assumed
position IDs were per-batch, they are per-row" is worth more later than "fixed
position bug".

Record numbers even when they are unremarkable. A flat number is data.

---

## Entries

### 2026-09-19 — M0 — baseline, no cache

**Goal today:** golden fixtures, golden test, naive full-recompute engine, first number.

**What I built:** `scripts/make_fixtures.py` (8 single fixtures + `batches.json`),
`tests/test_golden.py`, `engine/{request,metrics,model_runner,api}.py`,
`scripts/bench_m0.py`. Every decode step re-runs the whole sequence; no cache.

**What broke, and why:** Nothing in the engine; all 8 fixtures matched on the first
run. Batch-independence tests are written but skip until M2 (`generate_batch` does
not exist). Chocolatey could not install `make` without admin, so `make.ps1` mirrors
the Makefile. Run-to-run noise is large: 17.3 tok/s on the first run vs ~13 on the
others, so the 3-run median is the number to trust and the spread must be shown.

**Number:** 13.06 tok/s median (runs 17.31 / 12.91 / 13.06), 5-token prompt,
100 output tokens, batch 1, 4 torch threads, i7-14700K. `results/m0_baseline.json`.

**Next:** M1, own KV cache. Before coding, agree the decode-step position id.

### 2026-09-19 — process note — building M1..M6 in one run

The user asked for the whole project to be completed step by step with every step
documented, overriding the "one milestone per session" habit in PROMPTS.md. The
per-milestone gate is kept: golden tests green, a number in `results/`, a log entry
and a commit at the end of each milestone. Each entry below is written when its
milestone closes.

### 2026-09-19 — M1 — own KV cache, single sequence

**Goal today:** stop recomputing K/V for old tokens, with a cache that is ours.

**Position id, agreed before coding:** prompt length P, decode step N (1-indexed):
the token fed is output token N, which sits at position P+N-1 = `seq_len - 1`
(seq_len counts the prompt plus every output token including that one). It writes
its K/V to cache index P+N-1 and attends to P+N keys. Prefill produces output token 1.

**What I built:** `engine/cache.py` (`ContiguousKVCache`, `[layers, 2, heads,
max_len, head_dim]`), and in `engine/model_runner.py` our own GPT-2 forward pass
(HF supplies weights only) with a prefill path (causal mask, start=0) and a decode
path (one token, explicit position). `generate_cached` drives it.

**What broke, and why:** nothing. All 8 fixtures matched on the first run, including
the 400-token prompt. Decode-step logits are computed for the last token only, so the
LM head is not applied to every prompt token during prefill.

**Number:** 81.41 tok/s median (81.4 / 81.0 / 82.2) vs 13.06 for M0, a 6.2x speedup,
same prompt and output length. `results/m1_kvcache.json`.

**Next:** M2, static batching.

### 2026-09-19 — M2 — static batching

**Goal today:** a batch dimension with padding, masks and per-row positions; measure
slot utilisation.

**What I built:** `SlotPool` and `BatchAccess` in `engine/cache.py` (each request gets a
full 1024-token contiguous slot; a batch reads/writes through an access object),
`SlotManager` in `engine/block_manager.py`, `ModelRunner.step_tokens` (one batched
forward for prefill or decode), `engine/scheduler.py` (static mode: admit only when the
previous batch has fully drained, one padded prefill for the whole batch),
`engine/config.py`, `scripts/workloads.py`, `scripts/bench_offline.py`, and
`tests/test_perf_guard.py`. The batch-independence tests from M0 are now live.

**Design decisions worth recording:**
- Finished rows drop out of the compute; only their *slots* stay idle until the whole
  batch drains. A naive server would keep computing padded finished rows, so this static
  baseline is stronger than the common one and the M3 gain measured against it is
  conservative.
- Tokens are streamed as they are produced even in static mode (most servers return the
  batch at the end), which is also generous to static batching.
- Slot utilisation counts unfinished rows / max_batch, averaged over decode steps only.
- Query t of row i sits at position start_i+t and may attend key j iff j <= start_i+t and
  j < total_i. Single-row cases keep the exact M1 kernels (no mask / is_causal) so
  numerics match the single-sequence path.

**What broke, and why:** the golden and batch-independence tests passed first time
(including a batch of 8 mixed lengths). The performance guard did not: it failed at
~83 tok/s against a recorded 110, twice in a row. Wrong mental model: I assumed
`torch.empty` for the pool was free. It is not: first-touch page faults land inside the
timed region, and whether they happen depended on whether the allocator recycled memory
from earlier engines in the same process. The same configuration ranged 145-205 tok/s
at batch 16 depending on that. Fix: `torch.zeros` for pools, so pages are touched at
startup as a real server would. After the fix, repeated runs agree within 1%. The 205
figure was an artefact and is not reported. Lesson: allocate and touch memory before the
timer starts.

**Number:** static batching, workload B (scaled), 32 requests, closed-loop burst:

| max_batch | tok/s | slot utilisation | attention padding waste |
|---|---|---|---|
| 1 | 57.7 | 1.00 | 0.00 |
| 2 | 65.2 | 0.75 | 0.06 |
| 4 | 85.1 | 0.60 | 0.13 |
| 8 | 119.2 | 0.55 | 0.18 |
| 16 | 145.0 | 0.54 | 0.26 |

Batch 16 is 2.5x the throughput of batch 1, but slot utilisation is only 0.54. That is
above the "well under 50%" the docs predicted: workload B is only moderately variable
(lognormal sigma 0.7). Workload C should be worse; M6 measures it. `results/m2_static.json`.
Prefill was 4.4 s of ~12.6 s at batch 16 with this prompt mix, a larger share than I
expected. Batch 1 here (57.7) is below M1's 81.4 because these prompts are longer (median 64
vs 5) and the time includes prefill.

**Scope note recorded here:** workload lengths are scaled down ~3x from
`docs/04-benchmark-methodology.md` (see `scripts/workloads.py`), decided before measuring,
because full-size runs are too slow on CPU to repeat 3x across every configuration.

**Next:** M3, continuous batching.

---

## Milestone summary table

Fill one row per milestone as it closes. This table is the skeleton of the final
write-up.

| Milestone | Closed on | Headline number | Biggest surprise |
|---|---|---|---|
| M0 baseline | 2026-09-19 | 13.06 tok/s (noisy: 12.9-17.3) | first run 33% faster than the rest; warmup alone does not remove variance |
| M1 KV cache | 2026-09-19 | 81.41 tok/s, 6.2x over M0 | golden test passed first time; runs agreed within 1% (M0 did not) |
| M2 static batching | 2026-09-19 | 145 tok/s at batch 16 (2.5x batch 1), slot util 0.54 | an uninitialised pool made identical runs differ by 40%; page faults in the timed region |
| M3 continuous batching | | | |
| M4 paged cache | | | |
| M5 preemption | | | |
| M6 benchmarks + page | | | |
