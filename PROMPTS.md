# PROMPTS.md — what to paste into Claude Code

Copy these one at a time. Do not paste two milestones at once. The whole design
of this project is that each milestone is verified before the next one starts.

A note on how to use Claude Code here: it will happily write all seven milestones
in one go if you let it, and the result will be a large pile of code you do not
understand and cannot debug. That defeats the purpose. **You are building this to
learn the mechanisms.** Go one step at a time and read what it writes.

---

## Session 0 — set up the repo

```
Read CLAUDE.md and every file in docs/ before doing anything.

Then set up the repository skeleton only. No engine logic yet.

- The folder structure described in CLAUDE.md.
- A Makefile with the targets listed there (they can be stubs that print
  "not implemented" for now).
- pyproject.toml or requirements.txt: torch (CPU build), transformers,
  fastapi, uvicorn, pytest, matplotlib.
- go.mod in bench/.
- .gitignore, and a README.md that is a short pointer to docs/.
- git init and one initial commit.

Do not write any engine code. Stop when the skeleton is committed and
`make setup` works.
```

---

## Session 1 — M0

```
We are starting M0. Read docs/02-milestones.md section M0 and
docs/03-correctness.md in full first, then restate the done criteria for M0
back to me before writing any code.

Build:
1. scripts/make_fixtures.py — generates golden fixtures using the HuggingFace
   reference implementation. This is the ONLY place model.generate() is allowed;
   put a comment saying so. Cover every fixture case listed in
   docs/03-correctness.md, including the ones that only become meaningful later.
2. tests/test_golden.py — compares token IDs exactly, never decoded strings.
3. engine/model_runner.py — loads GPT-2 small on CPU, runs a forward pass.
4. engine/api.py — POST /generate, one request at a time, greedy decoding,
   NO KV cache. Recompute the full sequence every step. Keep it deliberately dumb.
5. engine/metrics.py — the metric set from docs/01-architecture.md. Collect them
   from the start even where they are trivially constant.

Then run the golden test and write results/m0_baseline.json with tokens/sec for
a fixed prompt and output length.

Stop and show me the numbers before doing anything else.
```

---

## Session 2 — M1

```
We are starting M1: my own KV cache, single sequence. Read the M1 section of
docs/02-milestones.md.

Do not use HuggingFace's past_key_values plumbing as a black box. The cache must
be ours, because M4 replaces its memory layout completely.

Build engine/cache.py and split the model runner into prefill and decode paths.
Position IDs must now be passed explicitly.

Before you write code, tell me exactly what the position ID should be on the Nth
decode step for a prompt of length P. I want to check we agree, because that
off-by-one is the main bug in this milestone.

Done means: byte-identical token IDs to M0 on every single-sequence fixture,
including the 400-token-prompt one, plus results/m1_kvcache.json.
```

---

## Session 3 — M2

```
We are starting M2: static batching. Read the M2 section of
docs/02-milestones.md.

Build the batch dimension, padding with masking, and per-row position IDs.
Add the slot utilisation metric described in docs/01-architecture.md.

Also add the batch-independence test from docs/03-correctness.md now: a prompt
run alone must produce identical token IDs to the same prompt run inside a batch
of eight with very different neighbours.

Done means: golden tests green, results/m2_static.json with a
throughput-versus-batch-size curve, and a recorded slot utilisation number.

I expect the utilisation number to be bad. That is the point of this milestone.
Tell me what it is.
```

---

## Session 4 — M3 (this one takes weeks, expect several sessions)

```
We are starting M3: continuous batching. This is the core of the project. Read
the M3 section of docs/02-milestones.md and the scheduler pseudocode in
docs/01-architecture.md.

Before writing code, walk me through the scheduler loop in your own words and
tell me where you think per-row position or mask bugs are most likely to appear.

Then build engine/scheduler.py with iteration-level scheduling and the
WAITING/RUNNING/FINISHED state machine. Prefill for a newly admitted request runs
as its own forward pass, then it joins the decode batch next step. Do not attempt
chunked prefill.

Add streaming responses so TTFT is measurable, and handle multi-token UTF-8
characters properly in the detokeniser.

The done criterion I care about most: the batch-independence test must pass in
the hardest form, where neighbours join and leave mid-generation.
```

Follow-up prompt when a golden test fails at M3 — this will happen:

```
The golden test is failing on fixture <name>. Do not guess at a fix and do not
add a tolerance to the assertion.

Work through the debug checklist in docs/03-correctness.md in order:
1. print per-row position IDs
2. print the attention mask shape and row sums (row i must attend to exactly
   its own current length)
3. find the first differing token index
4. dump logits at that step and compare to the reference

Report what you find at each step before proposing a fix.
```

---

## Session 5 — M4

```
We are starting M4: paged KV cache. Read the M4 section of
docs/02-milestones.md and the memory arithmetic in docs/01-architecture.md.

Build engine/block_manager.py and convert the cache to a flat pool of blocks
addressed through per-request block tables. Make total KV memory a config knob,
with num_blocks derived from it.

For the attention gather: use a temporary contiguous buffer. Mark it with a
"# LIMITATION:" comment explaining that a production system uses a fused kernel
instead.

The block-boundary fixtures in docs/03-correctness.md exist specifically for this
milestone. Do not skip them, and tell me if any of them were not already created
back in M0.

Done means: golden tests green, memory per sequence tracks actual tokens, and
results/m4_paged.json includes a throughput-versus-memory-budget curve.
```

---

## Session 6 — M5

```
We are starting M5: preemption and admission control. Read the M5 section of
docs/02-milestones.md.

Implement preempt-and-recompute (not swapping). Evict the most recently admitted
request. Add a starvation guard: track preemption count per request and give
repeat victims priority.

Add admission control so the server stops accepting work it cannot serve.

Done means: I can load it well past capacity and it degrades smoothly with no
crash, no OOM and no request stuck forever, with results/m5_overload.json showing
latency versus offered load past saturation.
```

---

## Session 7 — M6

```
We are starting M6: benchmarks and the results page. Read
docs/04-benchmark-methodology.md in full — all of it, it is the spec for this
milestone.

Build:
1. bench/ — the Go load generator. Poisson arrivals, configurable prompt and
   output length distributions, precise per-request timing, JSON output.
2. scripts/run_bench.sh — one command that runs every configuration in the
   ablation table and every sweep, and writes every JSON file.
3. scripts/plot.py — regenerates every chart from the JSON.
4. site/ — a single self-contained HTML page.

Non-negotiable from the methodology doc:
- Report goodput at a stated SLO as the headline, not peak throughput.
- Run all three workloads (uniform, realistic, high variance) and publish the
  uniform one first, because it is the least flattering.
- The ablation table must include the rows that isolate paging from continuous
  batching.
- Collect every "# LIMITATION:" comment in the codebase into the limitations
  section on the page.

Do not tune any configuration to improve a number.
```

---

## Useful mid-project prompts

**When you have lost the thread:**

```
Read docs/06-build-log.md and the git log. Summarise where the project stands,
what the last recorded numbers were, and what the immediate next step is
according to docs/02-milestones.md.
```

**When Claude Code suggests something not in the plan:**

```
That is not in docs/02-milestones.md. Explain why the milestone as written will
not work, and what you propose instead, before changing anything.
```

**Closing a milestone:**

```
Milestone <N> is done. Append an entry to docs/06-build-log.md covering what was
built, what broke and why, and the headline number. Then fill in this
milestone's row in the summary table, and update the "Current milestone" line at
the top of the file. Commit with the milestone tag.
```

**Explaining a piece of the code back to you:**

```
Explain how <file/function> works, from first principles, as if I have never seen
this system before. Do not skip intermediate steps. If there is arithmetic,
show all of it.
```
