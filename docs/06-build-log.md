# 06 — Build log

**Current milestone: M6**

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

### 2026-09-19 — M3 — continuous batching

**Goal today:** admit at every iteration instead of every batch; stream tokens; measure
against M2.

**Where I predicted per-row bugs would appear (before coding):** (1) position ids for a
row that joined late, (2) the key-side mask when rows have different lengths, (3) a slot
reused by a new request still holding the previous occupant's K/V. (3) is safe by
construction: a slot is fully overwritten from position 0 by prefill and the mask hides
everything past `total`. None of the three bit.

**What I built:** continuous mode in `Scheduler._admit` (a slot freed this iteration is
refilled the next; each admitted request gets its own prefill forward, then joins the
decode batch), `EngineLoop` (scheduler on its own thread, requests handed over through a
thread-safe inbox), `NaiveScheduler` (so the HTTP server can also serve the M0 baseline),
`engine/detokenizer.py` (sliding-window incremental decode that holds back incomplete
UTF-8), a streaming NDJSON `POST /generate`, `GET /metrics`, `POST /metrics/reset`, and an
open-loop Poisson harness in `scripts/bench_offline.py`.
Two small additions outside the planned layout: `engine/config.py`, `engine/detokenizer.py`.

**Tests:** every fixture through the continuous engine, the three batch cases, and the
hard one: the `mixed_8` set arriving at iterations `[0,0,3,5,8,13,21,34]` with
`max_batch` 2, 3 and 5, so neighbours join and leave mid-generation. All passed first time,
as did a streamed-text-equals-decoded-tokens test with emoji/CJK and a detokenizer unit test.

**What broke, and why:** nothing in correctness. One trap avoided: continuous mode needs
`max_batch - len(running)` computed *after* retiring, otherwise a just-finished row's slot
is not offered to the queue until the following iteration.

**Number (open-loop Poisson, workload B scaled, 40 requests, max_batch 16, contiguous):**

| rate req/s | mode | tok/s | goodput req/s | p99 TTFT s |
|---|---|---|---|---|
| 1 | static | 72.8 | 0.66 | 5.01 |
| 1 | continuous | 80.6 | 1.39 | 0.15 |
| 2 | static | 132.4 | 1.94 | 2.86 |
| 2 | continuous | 147.3 | 2.53 | 0.14 |
| 3 | static | 160.5 | 1.66 | 3.92 |
| 3 | continuous | 199.5 | 3.43 | 0.16 |
| 4 | static | 180.8 | 1.48 | 4.06 |
| 4 | continuous | 235.7 | 4.05 | 0.70 |

Goodput uses SLO p99-style per-request thresholds TTFT <= 2 s and TPOT <= 200 ms, chosen
before measuring. Continuous wins on every row; the biggest gap is TTFT, because a request
no longer waits for a batch to drain.

Slot utilisation only means something when work is always waiting, so it was measured
separately with a saturating burst (96 requests, max_batch 8): **static 0.427, continuous
0.937**, throughput 169.8 vs 231.0 tok/s (+36%). Continuous does not reach 100% because the
tail of the burst drains. In the open-loop rows utilisation is low (0.13-0.50) simply
because 16 slots were never full at these offered loads; that is not a scheduler defect.

**Measured weakness (docs asked for this):** attention padding waste under continuous
batching is **0.39** (39% of attended key width is padding) versus 0.14 for static in the
same burst, because rows are at very different lengths and everything is padded to the
longest. This is the cost of the padded-not-ragged design. Long-prefill stall: a single
800-token prompt injected into steady 2 req/s load raised the worst inter-token gap seen by
other requests from 0.141 s to **0.374 s** (prefill of the 800-token prompt alone takes
`prefill_800_tokens_s` in the JSON). The p99 inter-token gap did NOT rise (0.097 vs 0.073),
so the stall is a single event, visible in the max but not in p99 for one injection. Chunked
prefill is the stretch fix.

`results/m3_continuous.json`.

**Correction to the entry above:** the 800-token prefill measured 0.447 s (`prefill_800_tokens_s`;
it includes building a small slot pool), against a worst inter-token gap of 0.374 s seen by
other requests.

**Next:** M4, paged KV cache.

### 2026-09-19 — M4 — paged KV cache

**Goal today:** allocate KV memory in fixed blocks addressed through a block table, so memory
used tracks tokens generated instead of the maximum.

**What I built:** `PagedPool` / `PagedAccess` in `engine/cache.py` (flat pool
`[num_blocks, heads, block_size, head_dim]` per layer; decode scatters one token per row,
attention gathers the needed blocks into a temporary contiguous buffer, marked
`# LIMITATION:`), `BlockManager` in `engine/block_manager.py` (free list, `can_allocate`,
`allocate`, `append_slot`, `free`), `num_blocks` derived from `kv_budget_mib`, and the
`kv_token_efficiency` and `peak_batch` metrics.

**Design decision (scope-relevant, recorded per CLAUDE.md rule 5):** M4 has no preemption yet,
so it must never over-commit. Admission therefore requires the worst-case block count
(prompt + max_new_tokens) of every running request to fit, while blocks are still allocated
lazily as tokens arrive. This bounds concurrency by worst case, not by actual use; M5 removes
that restriction with optimistic admission plus preemption. It is the reason M4 alone leaves
some concurrency on the table.

**Tests (all first-time green):** every fixture at block sizes 4 and 16; the three batch
cases static and continuous; neighbours joining and leaving with the free list shuffled so a
sequence's blocks are genuinely non-adjacent; allocator unit tests for the block-boundary
off-by-one (prompt of 16 needs 1 block, the token at position 16 needs a second); and a test
that dumps the block table and compares K and V for all 12 layers and 70 positions against a
contiguous prefill, bit for bit. One failure was my own wrong expectation: the newest token
has been emitted but not fed, so it owns no storage until the next step (stored tokens =
seq_len - 1). The fixture set already contained the block-boundary cases from M0, so none had
to be added.

**Measurement problem found and handled:** the identical config (paged, 256 MiB, block 16)
gave 292 and 195 tok/s in two single runs, a 50% swing. Single runs cannot support any
conclusion on this machine. The benchmark was rewritten to repeat every point 3 times,
interleaved rep-major, and report medians with all runs. The third repetition was about 30%
slower for nearly every point (machine drift, not configuration), which interleaving spreads
equally.

**Number** (workload B scaled, 96 requests, closed-loop burst, max_batch 32, median of 3):

| budget MiB | contiguous tok/s | peak batch | paged tok/s | peak batch |
|---|---|---|---|---|
| 128 | 72 | 1 | 213 | 13 |
| 256 | 122 | 3 | 240 | 25 |
| 512 | 203 | 7 | 230 | 32 |
| 1024 | 255 | 14 | 234 | 32 |
| 2048 | 291 | 28 | 240 | 32 |

- Memory: KV token efficiency (live tokens / allocated capacity) is **0.94-0.95 paged versus
  0.12-0.17 contiguous**, and paged fits 13x the concurrent sequences at 128 MiB. The memory
  criterion is met clearly.
- Throughput: paged wins **2.9x at 128 MiB and 2.0x at 256 MiB**, roughly ties at 512 MiB,
  and is **slower once memory stops binding**: 234 vs 255 at 1 GiB and 240 vs 291 at 2 GiB
  (about 8-18% lower). That is the price of the gather copy plus the worst-case admission rule,
  and it is published as measured. Paging does not make things faster when there is plenty of
  memory; it makes the same memory go further.
- Block size (256 MiB): efficiency 0.99 / 0.98 / 0.95 / 0.90 / 0.82 for blocks of 4 / 8 / 16 /
  32 / 64 tokens, peak batch 25 / 25 / 25 / 23 / 22. Throughput 241 / 241 / 262 / 246 / 225:
  differences are inside the run-to-run spread except that 64 is worst, so the honest reading
  is "16-32 is a fine default; 64 wastes memory". `results/m4_paged.json`.

**Next:** M5, preemption and admission control.

### 2026-09-19 — M5 — preemption and admission control

**What I built:** optimistic admission (`preemption=True`: admit if the free blocks cover the
prompt plus one block of headroom per running request), preempt-and-recompute
(`Scheduler._ensure_capacity` / `_preempt`: free the victim's blocks, put it back in WAITING
keeping its generated tokens, and on readmission prefill prompt + generated tokens, which yields
the next token directly), eviction policy (most recently admitted among the least-preempted
requests), starvation guard (preempted requests re-enter at the front, worst-treated first, and
are the last to be evicted again), front-door admission control (`max_queue`; HTTP 429 when the
queue is full), and a 413 for requests that could never fit in the whole pool (without that
check such a request would be preempted and readmitted forever).

**Tests:** preemption is forced (asserted `preemptions > 0`, otherwise the test would be
meaningless) with a 40 MiB pool of 4-token blocks and with a 30 MiB pool (106 blocks, just
enough for the longest fixture alone) under overlapping arrivals; outputs after eviction and
recompute are byte-identical to the reference; all 16 requests of a doubled overload set
finish, nobody is evicted more than 40 times, and no block leaks; reserve mode serves the same
overload with zero preemptions; admission control returns False and API returns 413.
My first attempt at the join/leave preemption test never preempted anything because its
staggered arrivals never overlapped enough. The engine was fine; the test premise was wrong.

**Number** (open-loop Poisson, workload B scaled, 60 requests per point, single seed, KV budget
128 MiB, max_batch 32; `results/m5_overload.json`). Columns: goodput req/s / p99 TTFT s.

| offered req/s | M5 paged+preempt+queue cap 32 | M4 paged, worst-case commit | M3 contiguous |
|---|---|---|---|
| 1 | 1.08 / 0.20 | 1.08 / 0.19 | 0.44 / 7.22 |
| 2 | 2.04 / 0.11 | 1.84 / 0.68 | 0.10 / 36.7 |
| 4 | 3.50 / 0.14 | 3.44 / 1.05 | 0.12 / 44.5 |
| 6 | 1.03 / 5.40 | 1.28 / 7.55 | 0.09 / 44.7 |
| 8 | 0.83 / 7.15 | 1.89 / 6.11 | 0.09 / 45.4 |
| 12 | 0.98 / 6.84 (7 rejected) | 1.55 / 8.17 | 0.10 / 43.4 |

What this shows, and what it does not:
- **Done criterion met:** past saturation (4 req/s) every system finished all 60 requests, with
  no crash, no OOM and nothing stuck. Latency rises to roughly 5-8 s p99 TTFT and stays there
  instead of growing without bound; throughput stays flat near 200 tok/s. Admission control
  only started refusing at 12 req/s (7 of 60 rejected with a cap of 32).
- **Honest negative:** preemption almost never fired (0-1 events per run). At this scale a
  sequence is ~130 tokens against a 1800-token pool, so optimistic admission rarely runs out of
  blocks. The M5 configuration was therefore NOT better than M4's worst-case admission on
  goodput at overload (0.83 vs 1.89 req/s at 8 req/s) and was better only at 2 req/s. With one
  seed and 60 requests the differences between the two paged systems are within noise, so I
  make no claim that preemption improves throughput here. What it adds is safety: it is what
  makes optimistic admission legal, and the tests prove it produces exact tokens when it does
  fire. Forcing it to fire required deliberately tiny pools in the tests.
- **The real contrast is contiguous versus paged at a tight budget:** 128 MiB holds one
  contiguous slot, so M3 collapses (p99 TTFT 36-45 s from 2 req/s upward) while paged keeps
  serving. This is the M4 effect, not the M5 one.

**Next:** M6, benchmarks and the public page.

---

## Milestone summary table

Fill one row per milestone as it closes. This table is the skeleton of the final
write-up.

| Milestone | Closed on | Headline number | Biggest surprise |
|---|---|---|---|
| M0 baseline | 2026-09-19 | 13.06 tok/s (noisy: 12.9-17.3) | first run 33% faster than the rest; warmup alone does not remove variance |
| M1 KV cache | 2026-09-19 | 81.41 tok/s, 6.2x over M0 | golden test passed first time; runs agreed within 1% (M0 did not) |
| M2 static batching | 2026-09-19 | 145 tok/s at batch 16 (2.5x batch 1), slot util 0.54 | an uninitialised pool made identical runs differ by 40%; page faults in the timed region |
| M3 continuous batching | 2026-09-19 | 231 vs 170 tok/s saturated (+36%), slot util 0.94 vs 0.43, p99 TTFT 0.70 s vs 4.06 s at 4 req/s | continuous batching pads 39% of attention width; one 800-token prefill doubled the worst token gap |
| M4 paged cache | 2026-09-19 | 2.9x throughput at 128 MiB, KV efficiency 0.95 vs 0.12 | paged is 8-18% slower when memory is plentiful (gather cost) |
| M5 preemption | 2026-09-19 | all requests finish at 3x capacity; latency plateaus ~5-8 s p99 TTFT | preemption almost never fired; worst-case admission did as well |
| M6 benchmarks + page | | | |
