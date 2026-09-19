#!/usr/bin/env bash
# Canary drill against whatever cluster kubectl points at (kind in CI). Usage:
#   scripts/canary_drill.sh <image-with-tag> <git-sha>
#
# Unlike scripts/rollout_drill.sh, whose bad release cannot even start (readiness catches it), the bad release here
# STARTS FINE and passes every probe, but rejects requests under load: the failure only the SLO can see.
#   1. Install Argo Rollouts and the canary overlay; wait for a healthy 4-pod rollout under steady traffic.
#   2. Good release: must be promoted to 100% by the analysis, unaided.
#   3. Bad release: the analysis must fail it and abort, unaided, and the stable pods must stay in service.
set -euo pipefail

IMAGE="${1:?image with tag}"
SHA="${2:?git sha}"
NS=llm-serve
ARGO_ROLLOUTS_VERSION=v1.7.2       # pinned: a floating "latest" controller would make this drill unreproducible
cd "$(dirname "$0")/.."

say() { printf '\n== %s\n' "$*"; }
phase() { kubectl -n $NS get rollout llm-serve -o jsonpath='{.status.phase}' 2>/dev/null || true; }
field() { kubectl -n $NS get rollout llm-serve -o "jsonpath={.status.$1}" 2>/dev/null || true; }
dump() { kubectl -n $NS get rollout,rs,pods -o wide || true
         kubectl -n $NS get analysisrun -o wide || true
         kubectl -n $NS describe analysisrun 2>/dev/null | tail -60 || true; }

# wait_phase <phase> <seconds>: fail early if the rollout goes Degraded while we want something else.
wait_phase() {
  local want=$1 limit=$2 waited=0 p
  while [ "$waited" -lt "$limit" ]; do
    p=$(phase)
    [ "$p" = "$want" ] && return 0
    if [ "$p" = "Degraded" ] && [ "$want" != "Degraded" ]; then echo "rollout went Degraded: $(field message)"; return 1; fi
    sleep 5; waited=$((waited + 5))
  done
  echo "timed out after ${limit}s waiting for phase $want (now: $(phase))"; return 1
}

say "1. install Argo Rollouts $ARGO_ROLLOUTS_VERSION and the canary overlay"
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argo-rollouts --server-side -f \
  "https://github.com/argoproj/argo-rollouts/releases/download/$ARGO_ROLLOUTS_VERSION/install.yaml"
kubectl -n argo-rollouts rollout status deployment/argo-rollouts --timeout=240s
kubectl wait --for=condition=Established crd/rollouts.argoproj.io crd/analysistemplates.argoproj.io \
  crd/analysisruns.argoproj.io --timeout=60s
kubectl kustomize deploy/overlays/canary \
  | sed "s#ghcr.io/nikhilsaravade/llm-serve:REPLACE_WITH_GIT_SHA#$IMAGE#g" \
  | kubectl apply -f -
# The production overlay has never been deployed, so at least prove the API server accepts every object in it
# (schema, RBAC escalation checks, the Argo Rollouts CRDs). A dry run changes nothing in the cluster.
kubectl kustomize deploy/production   | sed "s#ghcr.io/nikhilsaravade/llm-serve:REPLACE_WITH_GIT_SHA#$IMAGE#g"   | kubectl apply --dry-run=server -f -
echo "production overlay accepted by the API server (dry run)"
kubectl -n $NS rollout status deployment/prometheus --timeout=180s
kubectl -n $NS rollout status deployment/loadgen --timeout=180s
wait_phase Healthy 600 || { dump; exit 1; }
INITIAL_STABLE=$(field stableRS)
echo "healthy, stable ReplicaSet $INITIAL_STABLE"

say "2. good release (a new pod template that changes nothing that matters): must be promoted"
kubectl -n $NS set env deployment/llm-serve RELEASE=good
sleep 10
wait_phase Healthy 900 || { dump; exit 1; }
GOOD_STABLE=$(field stableRS)
[ "$GOOD_STABLE" != "$INITIAL_STABLE" ] || { echo "FAIL: good release was never promoted"; dump; exit 1; }
kubectl -n $NS get analysisrun -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{"\n"}{end}'
echo "promoted: stable ReplicaSet moved $INITIAL_STABLE -> $GOOD_STABLE"

say "3. bad release: starts, passes readiness, rejects requests under load"
: > /tmp/available.log
( while true; do
    a=$(kubectl -n $NS get rollout llm-serve -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)
    echo "${a:-0}" >> /tmp/available.log; sleep 3
  done ) & POLL_PID=$!
trap 'kill $POLL_PID 2>/dev/null || true' EXIT
BAD_CONFIG='{"backend":"paged","batching":"continuous","max_batch":1,"kv_budget_mib":128,"block_size":16,"preemption":true,"max_queue":1}'
kubectl -n $NS set env deployment/llm-serve "LLM_SERVE_CONFIG=$BAD_CONFIG"
sleep 10
if ! wait_phase Degraded 600; then
  echo "FAIL: the bad release was not aborted (phase now $(phase))"; dump; exit 1
fi
echo "aborted by the analysis: $(field message)"
kill $POLL_PID 2>/dev/null || true

say "4. the stable pods must still be the ones serving, and capacity must never have dropped"
[ "$(field stableRS)" = "$GOOD_STABLE" ] || { echo "FAIL: stable ReplicaSet changed to $(field stableRS)"; dump; exit 1; }
kubectl -n $NS get analysisrun -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{"\n"}{end}' | tee /tmp/runs.txt
grep -q Failed /tmp/runs.txt || { echo "FAIL: no analysis run failed, so something other than the SLO stopped it"; dump; exit 1; }
LOWEST=$(sort -n /tmp/available.log | head -1)
[ "${LOWEST:-0}" -ge 4 ] || { echo "FAIL: available replicas dropped to $LOWEST during the bad release"; dump; exit 1; }
# Wait for the aborted canary pods to be scaled away, then confirm traffic is still being served.
for _ in $(seq 1 40); do
  n=$(kubectl -n $NS get pods -l app=llm-serve --no-headers 2>/dev/null | wc -l)
  [ "$n" -le 4 ] && break; sleep 5
done
before=$(kubectl -n $NS logs deploy/loadgen --tail=1 | grep -o "'ok': [0-9]*" | grep -o '[0-9]*$' || echo 0)
sleep 30
after=$(kubectl -n $NS logs deploy/loadgen --tail=1 | grep -o "'ok': [0-9]*" | grep -o '[0-9]*$' || echo 0)
[ "${after:-0}" -gt "${before:-0}" ] || { echo "FAIL: no successful requests after the abort ($before -> $after)"; dump; exit 1; }
echo "successful requests still advancing after the abort: $before -> $after"
say "PASS: good release promoted, SLO-breaching release aborted automatically, stable pods kept serving"
