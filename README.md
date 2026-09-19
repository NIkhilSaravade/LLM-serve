# llm-serve

A from-scratch LLM inference server (GPT-2 small, CPU) built to measure continuous
batching and a paged KV cache against naive serving.

Start with [docs/00-project-brief.md](docs/00-project-brief.md). The plan is in
[docs/02-milestones.md](docs/02-milestones.md); progress and every measurement are in
[docs/06-build-log.md](docs/06-build-log.md). Working rules are in [CLAUDE.md](CLAUDE.md).
The public results page is [site/index.html](site/index.html).

## Results

Measured on one CPU (hardware in `results/bench/machine.json`). Workload B, 3 requests/s offered,
KV budget 512 MiB, median of 3 seeds:

| config | goodput @ SLO (req/s) |
|---|---|
| naive, no cache | 0.07 |
| KV cache, batch 1 | 0.20 |
| static batching | 0.80 |
| continuous batching | 2.83 |
| continuous + paged KV | 2.83 (p99 TTFT 0.11 s vs 1.64 s) |

Continuous batching is the big win. Paging changes goodput only when KV memory binds (128 MiB: 2.73
vs 0.18 req/s) or load is high (8 req/s: 1.77 vs 0.83). Limitations and deviations from the plan
(scaled-down workloads, fewer requests per run) are on the page and in the build log.

## Commands

```
make setup && make test      # 88 golden and unit tests
make serve                   # engine on :8000
make bench                   # about 2 hours, writes results/bench/
make results                 # charts and site/index.html
```

On Windows without GNU make, use `.\make.ps1 <target>`.
