# 06 — Build log

**Current milestone: M2**

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

---

## Milestone summary table

Fill one row per milestone as it closes. This table is the skeleton of the final
write-up.

| Milestone | Closed on | Headline number | Biggest surprise |
|---|---|---|---|
| M0 baseline | 2026-09-19 | 13.06 tok/s (noisy: 12.9-17.3) | first run 33% faster than the rest; warmup alone does not remove variance |
| M1 KV cache | 2026-09-19 | 81.41 tok/s, 6.2x over M0 | golden test passed first time; runs agreed within 1% (M0 did not) |
| M2 static batching | | | |
| M3 continuous batching | | | |
| M4 paged cache | | | |
| M5 preemption | | | |
| M6 benchmarks + page | | | |
