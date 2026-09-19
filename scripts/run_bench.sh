#!/usr/bin/env bash
# Reproduces every published benchmark number: starts each server configuration, drives it
# with the Go load generator, and writes one JSON per run to results/bench/.
#
#   ./scripts/run_bench.sh              # everything (about 2 hours on the reference machine)
#   ONLY=ablation ./scripts/run_bench.sh   # one experiment: ablation curve sweeps stall
#
# Idempotent: a run whose JSON already exists is skipped, so an interrupted run resumes.
# Delete results/bench/ to start from scratch. Then `make results` rebuilds charts and page.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
BENCH=bench/llm-bench; [ "${OS:-}" = "Windows_NT" ] && BENCH=bench/llm-bench.exe
PORT=8000
URL=http://127.0.0.1:$PORT
OUT=results/bench
DURATION=${DURATION:-30}     # seconds of Poisson arrivals per run
DRAIN=${DRAIN:-20}           # extra seconds for in-flight requests before they count as unfinished
THREADS=4                    # torch threads: pinned, identical for every variant
ONLY=${ONLY:-all}
Q='"max_queue":64'           # the same admission-control cap for every variant

(cd bench && go build -o "$(basename "$BENCH")" .) || { echo "go build failed"; exit 1; }
mkdir -p "$OUT"
$PY scripts/machine_info.py > "$OUT/machine.json"

SERVER_PID=""
start_server() {  # $1 = EngineConfig JSON
  LLM_SERVE_CONFIG="$1" LLM_SERVE_THREADS=$THREADS "$PY" -m uvicorn engine.api:app \
      --port $PORT --log-level warning &
  SERVER_PID=$!
  for _ in $(seq 1 180); do
    curl -sf "$URL/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "server failed to start: $1" >&2; exit 1
}
stop_server() {
  [ -z "$SERVER_PID" ] && return
  if [ -e "/proc/$SERVER_PID/winpid" ]; then   # Git Bash: kill the real Windows process tree
    taskkill //F //T //PID "$(cat /proc/$SERVER_PID/winpid)" >/dev/null 2>&1 || true
  else
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
  for _ in $(seq 1 30); do curl -sf "$URL/health" >/dev/null 2>&1 || break; sleep 1; done
}
trap stop_server EXIT

# bench <experiment> <cfgname> <workload> <rate> <seed> [extra llm-bench flags]
bench() {
  local exp=$1 cfg=$2 wl=$3 rate=$4 seed=$5; shift 5
  local file="$OUT/$exp/${cfg}_${wl}_r${rate}_s${seed}.json"
  if [ -s "$file" ]; then echo "skip $file"; return; fi
  mkdir -p "$OUT/$exp"
  "$BENCH" -url "$URL" -label "$cfg" -workload "$wl" -rate "$rate" -seed "$seed" \
      -duration "$DURATION" -drain "$DRAIN" -out "$file" "$@"
}
# with_server <cfgname> <json> <command...>: start the server, run the command, stop it.
with_server() {
  local name=$1 json=$2; shift 2
  echo "=== server: $name  $json"
  start_server "$json"; "$@"; stop_server
}
want() { [ "$ONLY" = "all" ] || [ "$ONLY" = "$1" ]; }

# ---- Ablation table: one row per real configuration (docs/04-benchmark-methodology.md) ----
# Fixed KV budget 512 MiB (chosen before measuring; the budget sweep below shows other values).
declare -A ABL=(
  [m0_naive]="{\"backend\":\"naive\",$Q}"
  [m1_kv_only]="{\"backend\":\"contiguous\",\"batching\":\"continuous\",\"max_batch\":1,\"kv_budget_mib\":512,$Q}"
  [m2_static]="{\"backend\":\"contiguous\",\"batching\":\"static\",\"max_batch\":16,\"kv_budget_mib\":512,$Q}"
  [m3_continuous]="{\"backend\":\"contiguous\",\"batching\":\"continuous\",\"max_batch\":16,\"kv_budget_mib\":512,$Q}"
  [m4_static_paged]="{\"backend\":\"paged\",\"batching\":\"static\",\"max_batch\":16,\"kv_budget_mib\":512,\"preemption\":false,$Q}"
  [m4_full]="{\"backend\":\"paged\",\"batching\":\"continuous\",\"max_batch\":16,\"kv_budget_mib\":512,\"preemption\":false,$Q}"
  [m5_full]="{\"backend\":\"paged\",\"batching\":\"continuous\",\"max_batch\":16,\"kv_budget_mib\":512,\"preemption\":true,$Q}"
)
ABL_ORDER=(m0_naive m1_kv_only m2_static m3_continuous m4_static_paged m4_full m5_full)
rate_for() { case $1 in A) echo 3;; B) echo 3;; C) echo 2;; esac; }   # offered load, fixed up front

run_ablation_cfg() {  # <cfg> : all three workloads, three seeds, at the fixed offered rate
  for wl in A B C; do for seed in 1 2 3; do bench ablation "$1" $wl "$(rate_for $wl)" $seed; done; done
}
run_seeds() {  # <exp> <cfg> <workload> <rate> <seeds...> [-- extra flags]
  local exp=$1 cfg=$2 wl=$3 rate=$4; shift 4
  for seed in "$@"; do bench "$exp" "$cfg" "$wl" "$rate" "$seed"; done
}
run_curve_cfg() {  # <cfg> <rates...>
  local cfg=$1; shift
  for r in "$@"; do for seed in 1 2 3; do bench curve "$cfg" B "$r" $seed; done; done
}
run_stall() {
  for seed in 1 2 3; do
    bench stall stall_baseline B 2 $seed -record-itl
    bench stall stall_injected B 2 $seed -record-itl -inject-at 15 -inject-prompt 800
  done
}

ablation() {
  for cfg in "${ABL_ORDER[@]}"; do
    with_server "$cfg" "${ABL[$cfg]}" run_ablation_cfg "$cfg"
  done
  # The same contiguous vs paged pair with memory NOT binding (2 GiB), workload B.
  for cfg in m3_continuous m4_full; do
    json=${ABL[$cfg]//\"kv_budget_mib\":512/\"kv_budget_mib\":2048}
    with_server "${cfg}_2048" "$json" run_seeds ablation "${cfg}_2048" B 3 1 2 3
  done
}

# ---- Throughput / latency versus offered load (workload B). Rate 3 comes from the ablation. ----
curve() {
  with_server m0_naive "${ABL[m0_naive]}" run_curve_cfg m0_naive 1 2 4
  for cfg in m2_static m3_continuous m5_full; do
    with_server "$cfg" "${ABL[$cfg]}" run_curve_cfg "$cfg" 1 2 4 6 8
  done
}

# ---- Sweeps: block size, KV budget, max batch (workload B, 2 seeds) ----
sweeps() {
  for bs in 4 8 16 32 64; do
    with_server "block$bs" "{\"backend\":\"paged\",\"batching\":\"continuous\",\"max_batch\":16,\"kv_budget_mib\":256,\"block_size\":$bs,\"preemption\":false,$Q}"       run_seeds sweep_block "block$bs" B 3 1 2
  done
  for mib in 128 256 512 1024 2048; do
    for be in contiguous paged; do
      with_server "budget${mib}_$be" "{\"backend\":\"$be\",\"batching\":\"continuous\",\"max_batch\":16,\"kv_budget_mib\":$mib,\"preemption\":false,$Q}"         run_seeds sweep_budget "budget${mib}_$be" B 3 1 2
    done
  done
  for mb in 1 2 4 8 16 32; do   # rate 8 is past capacity, so the batch cap is what limits throughput
    with_server "maxbatch$mb" "{\"backend\":\"paged\",\"batching\":\"continuous\",\"max_batch\":$mb,\"kv_budget_mib\":1024,\"preemption\":false,$Q}"       run_seeds sweep_maxbatch "maxbatch$mb" B 8 1 2
  done
}

# ---- Long-prefill stall: steady load, with and without one 800-token prompt at t=15 s ----
stall() { with_server stall "${ABL[m3_continuous]}" run_stall; }

want ablation && ablation
want curve && curve
want sweeps && sweeps
want stall && stall
echo "done: $(find "$OUT" -name '*_s*.json' | wc -l) run files in $OUT"
