# Works with GNU make under Git Bash / Linux / macOS.
# Override the interpreter used to create the venv: make setup BOOTSTRAP_PY="py -3.11"
BOOTSTRAP_PY ?= python3
VENV := .venv
ifeq ($(OS),Windows_NT)
  VPY := $(VENV)/Scripts/python
else
  VPY := $(VENV)/bin/python
endif

.PHONY: setup test serve bench results

setup:
	$(BOOTSTRAP_PY) -m venv $(VENV)
	$(VPY) -m pip install --upgrade pip
	$(VPY) -m pip install -r requirements.txt

test:
	$(VPY) -m pytest -q

serve:
	$(VPY) -m uvicorn engine.api:app --port 8000

bench:
	bash scripts/run_bench.sh

results:
	$(VPY) scripts/plot.py
	$(VPY) scripts/build_site.py
