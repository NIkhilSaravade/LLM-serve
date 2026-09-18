# 06 — Build log

**Current milestone: M0**

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

---

## Milestone summary table

Fill one row per milestone as it closes. This table is the skeleton of the final
write-up.

| Milestone | Closed on | Headline number | Biggest surprise |
|---|---|---|---|
| M0 baseline | 2026-09-19 | 13.06 tok/s (noisy: 12.9-17.3) | first run 33% faster than the rest; warmup alone does not remove variance |
| M1 KV cache | | | |
| M2 static batching | | | |
| M3 continuous batching | | | |
| M4 paged cache | | | |
| M5 preemption | | | |
| M6 benchmarks + page | | | |
