#!/usr/bin/env bash
# Release drill against whatever cluster kubectl points at (kind in CI). Usage:
#   scripts/rollout_drill.sh <image-with-tag> <git-sha>
#
# 1. Roll out the release and wait for it to be Ready.
# 2. Smoke-test the running service (right build, ready, concurrent requests, metrics).
# 3. Ship a deliberately bad release (config the engine refuses to start with). A safe pipeline must keep
#    serving on the old pods, detect that the rollout never becomes Ready, and roll back on its own.
#    The drill fails if capacity ever drops or the rollback does not restore the old build.
set -euo pipefail

IMAGE="${1:?image with tag}"
SHA="${2:?git sha}"
NS=llm-serve
REPLICAS=2
cd "$(dirname "$0")/.."

say() { printf '\n== %s\n' "$*"; }
PF_PID=""
forward() { [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null || true
            kubectl -n $NS port-forward svc/llm-serve 8000:80 >/tmp/pf.log 2>&1 & PF_PID=$!
            for _ in $(seq 1 30); do curl -sf localhost:8000/ready >/dev/null && return 0; sleep 1; done
            echo "port-forward never became ready"; cat /tmp/pf.log; return 1; }
trap '[ -n "$PF_PID" ] && kill $PF_PID 2>/dev/null || true' EXIT

say "1. deploy $IMAGE"
kubectl kustomize deploy/overlays/ci \
  | sed "s#ghcr.io/nikhilsaravade/llm-serve:REPLACE_WITH_GIT_SHA#$IMAGE#g" \
  | kubectl apply -f -
kubectl -n $NS rollout status deployment/llm-serve --timeout=420s

say "2. smoke test"
forward
python scripts/smoke_deploy.py --expect-sha "$SHA"
GOOD_REVISION=$(kubectl -n $NS get deployment llm-serve -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')

say "3. bad release (engine config it cannot start with)"
MIN_AVAILABLE=$REPLICAS
( while true; do
    a=$(kubectl -n $NS get deployment llm-serve -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)
    echo "${a:-0}" >> /tmp/available.log; sleep 2
  done ) & POLL_PID=$!
kubectl -n $NS set env deployment/llm-serve 'LLM_SERVE_CONFIG={"no_such_field":1}'
if kubectl -n $NS rollout status deployment/llm-serve --timeout=90s; then
  echo "FAIL: a release that cannot start was reported healthy"; kill $POLL_PID; exit 1
fi
echo "rollout did not become Ready within 90s, as it should not. Rolling back."
kubectl -n $NS get pods -l app=llm-serve
kill $POLL_PID
LOWEST=$(sort -n /tmp/available.log | head -1)
[ "${LOWEST:-0}" -ge "$MIN_AVAILABLE" ] || { echo "FAIL: capacity dropped to $LOWEST during the bad rollout"; exit 1; }
echo "capacity never fell below $MIN_AVAILABLE replicas during the bad rollout"

say "4. roll back"
kubectl -n $NS rollout undo deployment/llm-serve
kubectl -n $NS rollout status deployment/llm-serve --timeout=300s
forward
python scripts/smoke_deploy.py --expect-sha "$SHA" --requests 8
NOW=$(kubectl -n $NS get deployment llm-serve -o jsonpath='{.spec.template.spec.containers[0].env}')
echo "restored spec has no bad override: ${NOW:-<none>}"
echo "$NOW" | grep -q no_such_field && { echo "FAIL: bad config still in the spec"; exit 1; }
say "PASS: release deployed, bad release contained and rolled back (was revision $GOOD_REVISION)"
