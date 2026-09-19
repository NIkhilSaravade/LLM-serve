# llm-serve

A from-scratch LLM inference server (GPT-2 small, CPU) built to measure continuous
batching and a paged KV cache against naive serving.

Every measurement is in [results/](results/) and on the results page. Working rules are in [CLAUDE.md](CLAUDE.md).
The design notes, build log and runbooks are kept offline and are not part of this repository.
The public results page is built from [site-src/](site-src/) (React, TypeScript, Tailwind, Motion) and deployed to Cloudflare Pages at **https://llm-serve.nikhilsaravade.com**. Preview it locally with `make site && npm --prefix site-src run preview`.

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

## Running it like a service

The engine is packaged and instrumented to be operated, not just benchmarked
(SLOs, alerts and the dashboard are defined in [deploy/](deploy/)):

| | |
|---|---|
| **Container** | `Dockerfile`: non-root, weights baked in, runs offline, one worker, readiness healthcheck |
| **Observability** | Prometheus `/metrics` (TTFT/TPOT/E2E histograms, queue depth, KV use, preemptions, outcomes), JSON request logs with `X-Request-ID`, `/health` `/ready` `/version` |
| **Dashboards + alerts** | Grafana dashboard and 12 Prometheus rules, including multi-window SLO burn-rate; generated from code, cross-checked against the live `/metrics` in tests |
| **Kubernetes** | `deploy/k8s`: probes, zero-downtime rolling update, PDB, HPA, hardened pod, ServiceMonitor + PrometheusRule |
| **CI** | `.github/workflows/ci.yml`: golden tests as the model-correctness gate, lint, generated-file drift, Go vet/build, manifest render, container smoke test |
| **Local stack** | `make up` runs the server + Prometheus + Grafana (`http://localhost:3000`) |

Verified locally: the image runs under the pod's security restrictions and returns the golden tokens;
the compose stack scrapes, loads all rules (`promtool` accepts them) and every dashboard query
returns data under real load. **Not verified:** the manifests on a live cluster, an alert actually
firing, and the GitHub workflow (no remote yet). The operations doc lists these plainly.

## Commands

```
make setup && make test      # 128 tests: golden, API, metrics, deploy config, site content
make perf                    # wall-clock throughput guard (noisy; run on a quiet machine)
make serve                   # engine on :8000
make bench                   # about 2 hours, writes results/bench/
make site                    # page data from results/bench, typecheck, production build into site/ (Node; once: make site-setup)
make site-test               # ... and drive it in desktop + mobile Chromium with the real Cloudflare headers, incl. axe accessibility
make plots                   # optional static PNG charts in results/plots
make lint                    # ruff
make docker                  # build the image
make up / make down          # server + Prometheus + Grafana
make deploy-check            # generated files current, manifests render
```

On Windows without GNU make, use `.\make.ps1 <target>`.

## License

[MIT](LICENSE). GPT-2 weights are downloaded from Hugging Face and remain under their own license; they are not redistributed here.
