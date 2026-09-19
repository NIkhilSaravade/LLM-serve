# Fallback for machines without GNU make: .\make.ps1 <target>
# Keep targets in sync with the Makefile.
param([Parameter(Position=0)][string]$Target = "help")
$vpy = ".venv\Scripts\python.exe"
switch ($Target) {
  "setup" {
    py -3.11 -m venv .venv
    & $vpy -m pip install --upgrade pip
    & $vpy -m pip install -r requirements.txt
  }
  "test"    { & $vpy -m pytest -q -m "not perf" }
  "perf"    { & $vpy -m pytest -q -m perf }
  "serve"   { & $vpy -m uvicorn engine.api:app --port 8000 }
  "bench"   { bash scripts/run_bench.sh }
  "results" { & $vpy scripts/plot.py; & $vpy scripts/build_site.py }
  "lint"    { & $vpy -m ruff check engine scripts tests --select E9,F }
  "docker"  { docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t llm-serve . }
  "up"      { docker compose -f deploy/docker-compose.yml up --build }
  "down"    { docker compose -f deploy/docker-compose.yml down }
  "deploy-check" {
    & $vpy scripts/render_prometheus_rule.py --check
    & $vpy scripts/build_dashboard.py
    kubectl kustomize deploy/k8s | Out-Null
    kubectl kustomize deploy/k8s/monitoring | Out-Null
  }
  default   { Write-Host "targets: setup test perf serve bench results lint docker up down deploy-check" }
}
