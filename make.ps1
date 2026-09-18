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
  "test"    { & $vpy -m pytest -q }
  "serve"   { & $vpy -m uvicorn engine.api:app --port 8000 }
  "bench"   { Write-Host "not implemented (M6)" }
  "results" { Write-Host "not implemented (M6)" }
  default   { Write-Host "targets: setup test serve bench results" }
}
