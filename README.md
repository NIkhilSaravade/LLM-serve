# llm-serve

A from-scratch LLM inference server (GPT-2 small, CPU) built to measure continuous
batching and a paged KV cache against naive serving.

Start with [docs/00-project-brief.md](docs/00-project-brief.md). The plan is in
[docs/02-milestones.md](docs/02-milestones.md); progress is in
[docs/06-build-log.md](docs/06-build-log.md). Working rules are in [CLAUDE.md](CLAUDE.md).

```
make setup     # venv + deps
make test      # golden tests
make serve     # engine on :8000
make bench     # Go load generator
make results   # plots + tables
```
