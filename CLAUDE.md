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
| Benchmark output | Plain JSON files in `results/` | Keep it reproducible. Benchmark numbers never depend on Prometheus or Grafana. |
| Plotting | Python + matplotlib, run from a script | Charts must regenerate from the JSON with one command. |
| Results page | React + Tailwind CSS + Motion, built by Vite into one file | Added on 2026-09-19 at the user's request for a high-end page. Every number is read from `site-src/src/data.json`, which `scripts/build_site.py` writes from the raw run files, so `make bench && make site` still reproduces the page. Nothing on it is typed by hand. |
| Operations layer | Prometheus `/metrics`, Grafana, Docker, Kubernetes, GitHub Actions | Added on 2026-09-19 at the user's explicit request, to make the project credible for MLOps roles. It is packaging and observability only: it must not change engine behaviour or any benchmark number. See `docs/07-operations.md`. |

## Repo layout

```
llm-serve/
├── CLAUDE.md
├── README.md              # results summary + how to run
├── docs/                  # read these; they are the spec (00-05), the log (06) and the runbook (07)
├── engine/                # Python: the actual server
│   ├── api.py             # FastAPI layer: /generate (streaming), /health /ready /metrics /version /stats
│   ├── request.py         # Request object + state machine
│   ├── scheduler.py       # THE CORE. iteration-level scheduling, preemption, EngineLoop thread
│   ├── block_manager.py   # THE CORE. slot allocator + paged KV block allocator
│   ├── model_runner.py    # our own GPT-2 forward pass, one batch step
│   ├── cache.py           # KV cache storage: single cache, slot pool, paged pool
│   ├── config.py          # EngineConfig: every ablation row is one config
│   ├── detokenizer.py     # streaming detokenisation that holds back partial UTF-8
│   ├── metrics.py         # counters and timings behind the benchmark JSON
│   └── observability.py   # Prometheus metrics for operators
├── bench/                 # Go: open-loop Poisson load generator
│   ├── main.go
│   └── report.go
├── tests/
│   ├── fixtures/          # golden outputs, committed to git
│   ├── conftest.py
│   ├── test_golden.py     # reference match, batching, continuous batching, streaming
│   ├── test_paged.py      # block boundaries, scattered blocks, block-table contents
│   ├── test_preemption.py # eviction exactness, admission control, cancellation
│   ├── test_ops.py        # health/metrics API, dashboards and alerts vs live /metrics
│   └── test_perf_guard.py # wall-clock throughput guard (marker: perf)
├── results/               # milestone JSON + results/bench/ (one file per load-generator run)
├── scripts/
│   ├── make_fixtures.py   # regenerate golden fixtures from HF reference (only place generate() is allowed)
│   ├── run_bench.sh       # one command, reproduces every published number
│   ├── bench_offline.py   # in-process milestone benchmarks (M2-M5)
│   ├── bench_m0.py, bench_m1.py, workloads.py, machine_info.py, bench_data.py
│   ├── plot.py            # optional static PNG charts into results/plots
│   ├── build_site.py      # results/bench + results/m*.json -> site-src/src/data.json (every number on the page)
│   ├── build_dashboard.py # Grafana dashboard JSON
│   └── render_prometheus_rule.py  # Kubernetes PrometheusRule from deploy/prometheus/alerts.yml
├── deploy/                # docker-compose, Prometheus, Grafana, Kubernetes manifests
├── site-src/              # React + Tailwind + Motion source of the results page (Vite builds it into site/)
│   ├── src/               # components, styles, data.json (generated, committed)
│   └── tests/site.spec.js # Playwright: desktop + mobile, no errors, no overflow, numbers present
├── Dockerfile
├── .github/workflows/ci.yml
└── site/                  # the built results page: ONE self-contained index.html (generated, committed)
```

## Commands

```bash
make setup          # venv + deps
make test           # 102 tests, golden ones included. must be green. (excludes the noisy perf guard)
make perf           # wall-clock throughput guard; run on a quiet machine
make serve          # start the engine on :8000
make bench          # about 2 hours: every configuration, every sweep, into results/bench/
make site           # regenerate the results page from results/bench (Python data step, then Vite)
make site-test      # ... and verify it in desktop + mobile Chromium with Playwright
make site-setup     # npm ci + Chromium, once
make plots          # optional static PNG charts
make lint           # ruff
make docker         # build the image
make up / make down # server + Prometheus + Grafana locally
make deploy-check   # generated files current, Kubernetes manifests render
```

On Windows without GNU make use `.\make.ps1 <target>` (same targets as the Makefile).

If a command does not exist yet, create it in the Makefile rather than telling
the user a long shell incantation.

## How to work in this repo

- Work one milestone at a time. The current milestone is tracked at the top of
  `docs/06-build-log.md`. M0-M6 are complete; the stretch goals in
  `docs/02-milestones.md` have not been started.
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
