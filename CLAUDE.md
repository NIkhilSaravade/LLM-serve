# CLAUDE.md — llm-serve

This file is read automatically at the start of every session. Follow it.

## What this project is

A from-scratch LLM inference server. It serves GPT-2 small on CPU.

The point of the project is **not** the model. The point is the **scheduler** and
the **KV cache memory manager**. Those two pieces are the whole reason this repo
exists. Everything else is scaffolding.

The final deliverable is a benchmark result: continuous batching plus paged KV
cache versus naive serving, measured honestly, with an ablation table.

Read `docs/00-project-brief.md` for the full context before starting real work.

## Non-negotiable rules

1. **Never use `model.generate()` or any HuggingFace generation helper.**
   The generation loop is the thing being built. Using the library version
   defeats the entire project. The reference implementation is allowed in tests
   only, to produce golden fixtures.

2. **The golden test must pass before any milestone is considered done.**
   Greedy decoding must produce token IDs that are byte-identical to the stored
   HuggingFace reference output. If it does not match, the work is not finished,
   no matter how fast it is. See `docs/03-correctness.md`.

3. **Correct first, fast second.** Do not optimize a code path until it has a
   passing golden test and a recorded benchmark number.

4. **Every milestone ends with a number written into `results/`.**
   A milestone with no measurement is not done.

5. **Do not silently change scope.** If a milestone looks like it needs a
   different design than the one in `docs/02-milestones.md`, say so and explain
   why. Do not just do it.

6. **No GPU code paths.** This runs on CPU only. Do not add CUDA kernels,
   `device="cuda"`, or Triton. Where a real system would need a fused kernel,
   write a slow correct version and add a `# LIMITATION:` comment explaining
   what a production version would do instead.

7. **Never tune a benchmark to look good.** If a configuration makes the new
   approach look bad, that configuration still gets published. See
   `docs/04-benchmark-methodology.md`.

## Tech choices (already decided, do not relitigate)

| Piece | Choice | Reason |
|---|---|---|
| Engine core | Python 3.11+ | PyTorch is here. The scheduler is the interesting part, not the language. |
| Tensors / model | PyTorch, CPU only | Free, correct, easy to inspect. |
| Model | GPT-2 small (124M), `transformers` for weights + tokenizer only | Small, well documented, learned position embeddings (simple). |
| API layer | FastAPI + uvicorn | Fine. Not the point of the project. |
| Load generator | **Go** | Concurrent load generation with accurate timing is what Go is good at. |
| Metrics output | Plain JSON files in `results/` | No Prometheus, no Grafana. Keep it reproducible. |
| Plotting | Python + matplotlib, run from a script | Charts must regenerate from the JSON with one command. |

## Repo layout

```
llm-serve/
├── CLAUDE.md
├── docs/                  # read these; they are the spec
├── engine/                # Python: the actual server
│   ├── api.py             # FastAPI layer
│   ├── request.py         # Request object + state machine
│   ├── scheduler.py       # THE CORE. iteration-level scheduling
│   ├── block_manager.py   # THE CORE. paged KV cache allocator
│   ├── model_runner.py    # forward pass for one batch step
│   ├── cache.py           # KV cache storage
│   └── metrics.py         # counters, timings
├── bench/                 # Go: load generator
│   ├── main.go
│   └── report.go
├── tests/
│   ├── fixtures/          # golden outputs, committed to git
│   └── test_golden.py
├── results/               # benchmark JSON, committed to git
├── scripts/
│   ├── make_fixtures.py   # regenerate golden fixtures from HF reference
│   ├── run_bench.sh       # one command, reproduces every published number
│   └── plot.py
└── site/                  # the public results page
```

## Commands

```bash
make setup          # venv + deps
make test           # golden tests. must be green.
make serve          # start the engine on :8000
make bench          # run the Go load generator against a running engine
make results        # regenerate plots + tables from results/*.json
```

If a command does not exist yet, create it in the Makefile rather than telling
the user a long shell incantation.

## How to work in this repo

- Work one milestone at a time. The current milestone is tracked at the top of
  `docs/06-build-log.md`.
- Before writing code for a milestone, restate the "done" criteria from
  `docs/02-milestones.md` and confirm they are understood.
- After finishing a milestone, append an entry to `docs/06-build-log.md`:
  what was built, what broke, what the number was.
- Prefer small commits with the milestone tag in the message, e.g.
  `M3: iteration-level scheduler admits requests mid-batch`.

## Style

- Plain, boring Python. Type hints on public functions.
- Comments explain **why**, not what.
- Any place where this implementation is knowingly worse than a production
  system gets a `# LIMITATION:` comment. These are collected into the results
  page later, so write them carefully.
