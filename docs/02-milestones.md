# 02 — Milestones

Rules for all milestones:

- Work on one at a time. Do not start the next one early.
- A milestone is done when its **done criteria** are met *and* a number is
  written into `results/`.
- The golden test must be green at the end of every milestone.
- Append an entry to `docs/06-build-log.md` when a milestone closes.

Rough total: **about 3 months at 8–10 hours a week.** M0–M2 go fast. M3 and M4
are where the real time goes. That is expected — those two are the reason the
project is worth doing.

---

## M0 — Baseline, no cache at all

**Time: ~3 days**

Load GPT-2 small. Serve one request at a time over HTTP. Generate each token by
running a forward pass over the **entire sequence so far**, from scratch, every
step.

This is deliberately the dumbest possible implementation. Do not optimise it.

### Build

- `engine/model_runner.py` — load the model, run a forward pass, return logits.
- `engine/api.py` — a `POST /generate` endpoint. Blocking is fine.
- Greedy token selection: `argmax` on the last position's logits.
- Stop on the EOS token or `max_new_tokens`.
- `scripts/make_fixtures.py` and `tests/test_golden.py` (see
  `docs/03-correctness.md`).

### Done when

- Golden test passes for the single-sequence fixtures.
- `results/m0_baseline.json` contains tokens/sec for a fixed prompt and output
  length.

### Why start this dumb

It gives you the true floor. Every later improvement is measured against a real
number, not against a guess. It also means M1's win is large and obvious, which
teaches you the shape of the problem early.

---

## M1 — Your own KV cache, single sequence

**Time: ~1 week**

Right now, producing token 50 recomputes tokens 1–49. That work is identical
every time. Stop throwing it away.

Inside attention, each token produces a Key vector and a Value vector. Store
them. On the next step, compute K and V only for the one new token, and read the
rest from the cache.

Write this yourself. Do not use HuggingFace's `past_key_values` plumbing as a
black box — you can look at it, but the cache must be yours, because M4 replaces
its memory layout entirely.

### Build

- `engine/cache.py` — a contiguous per-sequence cache, shaped roughly
  `[layers, 2, heads, max_len, head_dim]`.
- Model runner learns two modes: **prefill** (many tokens at once) and **decode**
  (exactly one token, reading cache).
- Position IDs must now be passed explicitly, because the model only sees one
  token but that token is at position `len(sequence)`.

### Done when

- Output is **byte-identical** to M0. Same token IDs.
- `results/m1_kvcache.json` shows the speedup, measured on the same prompt as M0.

### Tricky part

The first off-by-one lives here. On a decode step the new token is at position
`len(prompt) + len(generated_so_far)`. Not `+1`, not `-1`. Write the fixture with
a 400-token prompt now — a short prompt hides this bug.

---

## M2 — Static batching

**Time: ~1 week**

Serve many requests at once. Collect up to N requests, run them together as one
batch, and let the batch run until **every** sequence in it has finished. Then
return them all and start the next batch.

This is how most naive servers work. You are building it in order to prove it is
bad.

### Build

- Batch dimension through the model runner.
- Padding to the longest sequence in the batch, with masking so padding
  contributes nothing.
- Per-row position IDs.
- New metric: **slot utilisation** — the fraction of batch slots doing useful
  work, averaged over every step of the run.

### Done when

- Golden test passes, including the batch-independence test.
- `results/m2_static.json` has a throughput-versus-batch-size curve.
- Slot utilisation is recorded, and it is clearly bad (expect well under 50% once
  output lengths vary).

### Why the bad number matters

That utilisation figure is the evidence that motivates M3. You are not going to
*claim* static batching wastes slots. You are going to have measured it, in your
own system, before you fixed it. That is a much stronger story.

---

## M3 — Continuous batching  ← the heart of the project

**Time: 2–3 weeks**

Stop thinking in batches. Think in steps.

At every decode step, the scheduler:

1. retires sequences that just finished and frees their cache,
2. pulls waiting requests from the queue into the freed slots,
3. runs one step for whatever is now in the batch.

A new request no longer waits for the batch to drain. It joins at the next step.

### Build

- `engine/scheduler.py` — the iteration-level loop (pseudocode in
  `docs/01-architecture.md`).
- Request state machine: WAITING → RUNNING → FINISHED.
- Prefill for a newly admitted request runs as its own forward pass, then that
  request joins the decode batch next step. (Chunked prefill is a later stretch
  goal, not now.)
- Streaming responses, so time-to-first-token is measurable.

### Done when

- Golden test passes, **including the batch-independence test where neighbours
  join and leave mid-generation**. This is the real proof.
- At the same p99 latency, throughput is meaningfully above M2.
- Slot utilisation is near 100%.
- `results/m3_continuous.json` written.

### Tricky parts

1. **Per-row positions and masks.** Sequences are now at different lengths in the
   same batch. Row 3 might be at position 12 while row 4 is at 400. Get this
   wrong and the output is fluent and wrong. The golden test is your only
   defence. Expect to lose days here. This is normal.

2. **Ragged batches.** Padding everything to the longest sequence wastes compute.
   Accept that waste for now — correctness first — but measure it and note it.

3. **Streaming detokenisation.** A single UTF-8 character can span several
   tokens. Decoding each token independently produces broken characters. Keep a
   small buffer and only emit complete characters.

4. **A long prefill stalls the decode loop.** Known weakness of the simple
   design. Measure it: send one 800-token prompt into a busy server and record
   the latency spike other requests see. Publish that chart. It is honest and it
   sets up chunked prefill as future work.

---

## M4 — Paged KV cache

**Time: 2–3 weeks**

Right now each sequence reserves cache space for the maximum length it might
reach. A request that generates 100 tokens against a 1024 limit reserves 73.7 MB
and uses 7.2 MB. Ninety percent wasted. (Arithmetic in
`docs/01-architecture.md`.)

Fix it the way an operating system fixes memory fragmentation. Cut the cache into
fixed-size blocks — say 16 tokens each. Give each sequence a **block table**: a
list saying which physical block holds each of its logical blocks. A sequence
grows by grabbing one more block when it needs one. Blocks do not need to sit
next to each other.

### Build

- `engine/block_manager.py` — free list, `can_allocate`, `allocate`,
  `append_slot`, `free`.
- Cache storage becomes one flat pool of blocks, not per-sequence arrays.
- Attention gathers K and V through the block table.
- Config knob for the total KV memory budget, so `num_blocks` is derived from it.
- New metric: KV utilisation.

### Done when

- Golden test passes, including the block-boundary fixtures.
- Memory used per sequence tracks tokens actually generated, not the maximum.
- Maximum concurrent sequences at a fixed memory budget is clearly higher than
  M3.
- `results/m4_paged.json` written, including a throughput-versus-memory-budget
  curve.

### Tricky parts

1. **The gather.** Attention must read K and V from blocks scattered across the
   pool. vLLM solves this with a custom CUDA kernel. You cannot. So gather the
   needed blocks into a temporary contiguous buffer, then run normal attention.
   It is slower. Mark it `# LIMITATION:` and explain in the results page what a
   production system does instead. **This limitation is a feature of the
   write-up, not an embarrassment.**

2. **Off-by-one at block boundaries.** The classic bug: a sequence of exactly
   `block_size` tokens needs one block, and the very next token needs a second.
   The fixtures listed in `docs/03-correctness.md` exist specifically to catch
   this. Do not skip them.

3. **Choosing block size.** Small blocks waste less memory but add more
   indirection overhead. Do not guess — run the sweep and publish the curve. This
   is one of the more interesting charts you will produce.

---

## M5 — Preemption and admission control

**Time: 1–2 weeks**

Memory is now packed tightly, so eventually a running sequence asks for a block
and there is none free. Decide what happens.

Two options. Pick one, implement it properly, and explain the choice.

- **Preempt and recompute** — evict a sequence, throw away its KV, put it back in
  WAITING, redo its prefill later. Simple. Wastes the recomputation.
- **Preempt and swap** — copy its blocks out to ordinary RAM, bring them back
  when space frees. More code. Avoids recompute.

Recommendation: implement recompute first, since it is simpler and the eviction
policy matters more than the mechanism.

Also add **admission control** at the front door: stop admitting new requests
when the system is already over its memory or latency budget, rather than
accepting work you cannot serve.

### Build

- Eviction policy — the simplest reasonable one is to evict the most recently
  admitted request, so you do not throw away work that is nearly finished.
- Starvation guard: a request that has been preempted must not be preempted
  forever. Track preemption count per request and prioritise repeat victims.
- Preemption metrics.

### Done when

- Load the server well past its capacity. It slows down smoothly. No crash, no
  OOM, no request stuck forever.
- `results/m5_overload.json` shows latency degrading gracefully as offered load
  rises past capacity.
- Golden test still green.

### Why this milestone punches above its weight

Anyone can make a system fast when it is under-loaded. What separates people who
have run things in production from people who have not is **behaviour at the
edge**. A latency curve that degrades smoothly past saturation is a strong
signal, and it is the milestone most portfolio projects never reach.

---

## M6 — Benchmarks and the public page

**Time: 1–2 weeks. Do not rush this one.**

This is the milestone that turns code into a credential. Everything before it is
raw material.

Read `docs/04-benchmark-methodology.md` in full before starting.

### Build

- `bench/` — the Go load generator. Poisson arrivals, configurable prompt and
  output length distributions, precise per-request timing, JSON output.
- `scripts/run_bench.sh` — one command, runs every configuration, writes every
  JSON file.
- `scripts/plot.py` — regenerates every chart from the JSON.
- `site/` — the public results page.

### Done when

- The page is live and contains: the headline throughput chart, latency
  percentile tables, the **ablation table**, the block-size sweep, the
  memory-budget sweep, the overload behaviour chart, the methodology section, and
  the limitations section.
- A stranger can clone the repo, run one command, and reproduce every published
  number.

---

## Stretch goals (only after M6 ships)

Do not touch these until the page is live. A finished M6 beats a half-finished
M7 every time.

- **Chunked prefill** — interleave pieces of a long prompt with decode steps, so
  long prompts stop stalling the loop. Then re-measure the stall chart from M3
  and show the improvement. This is the most valuable stretch goal because you
  will already have the "before" measurement.
- **Prefix caching** — share KV blocks between requests with a common prefix
  (system prompts). Big real-world win, and the block table makes it natural.
- **A second model architecture** — one using grouped-query attention, which
  shrinks the KV cache substantially. Shows the mechanisms generalise.
- **Speculative decoding** — a much larger project. Probably a separate repo.
