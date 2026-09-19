# Works with GNU make under Git Bash / Linux / macOS.
# Override the interpreter used to create the venv: make setup BOOTSTRAP_PY="py -3.11"
BOOTSTRAP_PY ?= python3
VENV := .venv
ifeq ($(OS),Windows_NT)
  VPY := $(VENV)/Scripts/python
else
  VPY := $(VENV)/bin/python
endif

.PHONY: setup test perf serve bench results lint docker up down deploy-check

setup:
	$(BOOTSTRAP_PY) -m venv $(VENV)
	$(VPY) -m pip install --upgrade pip
	$(VPY) -m pip install -r requirements.txt

test:
	$(VPY) -m pytest -q -m "not perf"

perf:
	$(VPY) -m pytest -q -m perf

serve:
	$(VPY) -m uvicorn engine.api:app --port 8000

bench:
	bash scripts/run_bench.sh

results:
	$(VPY) scripts/plot.py
	$(VPY) scripts/build_site.py

lint:
	$(VPY) -m ruff check engine scripts tests --select E9,F

docker:
	docker build --build-arg GIT_SHA=$$(git rev-parse --short HEAD) -t llm-serve .

up:
	docker compose -f deploy/docker-compose.yml up --build

down:
	docker compose -f deploy/docker-compose.yml down

deploy-check:
	$(VPY) scripts/render_prometheus_rule.py --check
	$(VPY) scripts/build_dashboard.py
	kubectl kustomize deploy/k8s > /dev/null
	kubectl kustomize deploy/k8s/monitoring > /dev/null
