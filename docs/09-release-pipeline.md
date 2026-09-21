# 09 — Release pipeline (continuous delivery)

How a commit becomes a released, gated image, and what is prepared for putting it in front of users. This is the
reference for the pipeline; `docs/07-operations.md` has the SLOs, alerts and runbooks it relies on, and
`docs/08-deploying-the-site.md` covers the results page (a separate, simpler pipeline).

**Status (2026-09-19):** the pipeline up to and including `stable` runs on GitHub Actions and is green. Deployment to a
production host is **prepared as code and validated in CI, but not deployed**: no VM exists and nothing serves real
traffic.

---

## 1. The path from commit to `stable`

```
push to main
   |
   v
ci  (.github/workflows/ci.yml)                 must be green for anything below to start
   | golden tests + API + deploy config, ruff, Go vet/build, page build + browser tests,
   | manifests render, image builds and serves
   v
release  (.github/workflows/release.yml, triggered by workflow_run of ci)
   |
   +-- publish   build ONE image per commit, push ghcr.io/<owner>/llm-serve:<commit-sha>  (SBOM + provenance)
   |      |
   |      +--> drill    deploy to kind with the production manifests; smoke test; ship a build that cannot start;
   |      |             capacity must never drop; rollback must restore the old build
   |      +--> canary   Argo Rollouts canary under steady traffic; a good release must be promoted and a release
   |      |             that starts fine but rejects requests must be aborted by the SLO analysis
   |      +--> perf     A/B against the last `stable` image on the same runner; fail on a relative regression
   |
   +-- promote   only if publish + drill + canary + perf all passed: retag the SAME image as `stable`
                 (no rebuild, so `stable` is byte-identical to what was tested)
```

Nothing is deployed to users by this workflow. `stable` means "the last commit that passed every gate", and it is the
baseline the next candidate is compared against.

A release image is identified three ways that must agree: the tag (commit SHA), the `GIT_SHA` baked into the image, and
`GET /version`. The smoke test fails if the running build is not the one that was deployed.

## 2. What each gate proves, and what it does not

| Gate | Proves | Does not prove |
|---|---|---|
| ci: golden tests | greedy output is token-for-token the HuggingFace reference, including batching, eviction and recompute | anything about speed |
| drill (`scripts/rollout_drill.sh`) | a release is deployed with `maxUnavailable: 0`; a build that cannot start never becomes Ready, never reduces capacity, and rollback restores the previous build | failures that pass readiness |
| canary (`scripts/canary_drill.sh`) | a release that starts fine, passes every probe, and rejects requests under load is aborted **automatically** by the SLO analysis, while stable pods keep serving | behaviour under real user traffic, exact traffic weights (see limitations) |
| perf (`scripts/perf_gate.py`) | the candidate is not more than 15% slower than the last stable on goodput or throughput, on one CPU shape at one load | absolute performance; a small slowdown; behaviour on other hardware |

## 3. Reproducing the gates on your own machine

Requirements: Docker, `kubectl`, `kind` (`go install sigs.k8s.io/kind@v0.24.0`), Go, Python venv from `make setup`.

```bash
docker build --build-arg GIT_SHA=local1 -t ghcr.io/nikhilsaravade/llm-serve:local1 .
kind create cluster --name drill --wait 120s
kind load docker-image ghcr.io/nikhilsaravade/llm-serve:local1 --name drill

scripts/rollout_drill.sh ghcr.io/nikhilsaravade/llm-serve:local1 local1     # about 3 minutes
scripts/canary_drill.sh  ghcr.io/nikhilsaravade/llm-serve:local1 local1     # about 8 minutes

python scripts/perf_gate.py --baseline IMG_A --candidate IMG_B --pairs 3 --rate 4   # about 10 minutes
kind delete cluster --name drill
```

On Windows run the scripts from Git Bash with `MSYS_NO_PATHCONV=1` and the venv's `Scripts` directory first on `PATH`.

## 4. The canary in detail (`deploy/overlays/canary`)

* **Rollout, not a second Deployment.** `rollout.yaml` uses `workloadRef` to reuse the pod template of the existing
  `llm-serve` Deployment, so a release is still "change the Deployment's image or config". Steps: 25% (1 of 4 pods),
  hold 60 s, 50%, hold 60 s, then 100%.
* **The analysis** (`analysis-template.yaml`) runs in the background from the first step and asks Prometheus about the
  canary's pods only, selected by the `pod_hash` label that Prometheus copies from the `rollouts-pod-template-hash`
  pod label:
  * `rejection-ratio`: `rate(llm_requests_total{status="rejected"}) / rate(llm_requests_total)` must stay below **0.05**,
    the same threshold as the `LLMHighRejectionRate` alert (a test enforces that the gate is not looser than the
    alert). Two bad readings fail the release.
  * `canary-receives-traffic`: the canary must be serving more than 0.05 req/s. **It fails closed**: an empty result is
    an error and errors fail the analysis, because a canary that gets no traffic proves nothing.
* **Traffic** comes from `loadgen/cluster_load.py`, a 12-worker closed loop inside the cluster, using the engine image
  (it already has Python).
* **The bad release in the drill** changes only `LLM_SERVE_CONFIG` to `max_batch 1, max_queue 1`. The engine starts,
  passes `/health` and `/ready`, and rejects requests once it has more than two in flight. This is the failure only an
  SLO check can see; readiness cannot.
* **Pass criteria** (all asserted by the script): the good release moves the stable ReplicaSet; the bad release ends in
  phase `Degraded` with an analysis run in phase `Failed`; the stable ReplicaSet is unchanged; available replicas never
  fell below 4; successful requests keep advancing after the abort.
* **Argo Rollouts is pinned** (`v1.7.2`) so the drill is reproducible.

## 5. The performance gate in detail

* **Relative, interleaved, median.** The two images run on the same machine in the order baseline, candidate,
  candidate, baseline, baseline, candidate, so drift over time hits both sides equally. The gate compares medians of
  3 runs per side.
* **Two metrics.** Goodput at the SLO (TTFT at most 2 s, TPOT at most 200 ms; a latency regression) and token
  throughput (a capacity regression). Fail if either candidate median is below **0.85** of the baseline median.
* **Operating point matters.** Well below the knee of the goodput curve both sides serve everything and a slower engine
  looks identical; far above it goodput collapses to a constant. The gate runs near the knee: **4 req/s locally,
  2 req/s on the GitHub runner** (cpu limit 3 of its 4 vCPUs, workload B, 25 s window + 15 s drain).
* **Fail closed.** If the baseline's goodput is under 0.3 req/s the comparison is "inconclusive" and the gate fails.
* **Recalibrating** (after changing runner type, engine defaults, or the workload): run the `perf-calibrate` workflow
  (Actions tab) with the same image on both sides at two or three candidate rates. Pick the rate where SLO attainment
  is roughly 0.9 to 1.0 but throughput is not just the offered load. Then run it once more with `candidate_cpus`
  set lower than the baseline's 3 to confirm the gate can fail. **Choose the rate and threshold from A/A runs before
  judging any candidate, and never move them after a candidate fails.** Record the result in
  `results/perf_gate/README.md`.
* Every release run uploads its numbers as the `perf-gate` artifact.

## 6. Production deployment: prepared, not deployed

Files: `deploy/production/` (overlay, `cloudflared.yaml`, `deployer-rbac.yaml`), `scripts/provision_vm.sh`,
`.github/workflows/deploy-production.yml`.

Design: one VM running k3s (single-node Kubernetes) with Argo Rollouts. The only public entry is a Cloudflare Tunnel to
`api.<domain>`; the VM opens no inbound port. The deploy workflow is manual, waits for the reviewer of the GitHub
`production` environment, resolves the chosen tag to an image **digest**, applies the rendered manifests over SSH as a
namespace-restricted ServiceAccount (never cluster-admin), waits for the canary to be promoted or aborted, and checks
that the public `/version` reports the deployed build. An aborted canary fails the job and leaves the stable pods
serving.

**What is verified:** the overlay renders in CI; a server-side dry run against a real cluster with the Argo Rollouts
CRDs installed accepts every object in it (schema and RBAC escalation checks included).
**What is not:** `provision_vm.sh`, the SSH deploy, the tunnel, and a real release on a real host.

### Go-live checklist (nothing here has been done)

1. Get a VM: Ubuntu or Debian, 8 vCPU and 16 GiB (four engine pods of 1 CPU each plus one surge pod). About 4 CPUs
   is not enough for the canary.
2. On the VM, as root: `sudo ./scripts/provision_vm.sh`. It installs k3s and Argo Rollouts and creates the restricted
   deployer identity and its kubeconfig.
3. Cloudflare: Zero Trust, Networks, Tunnels, create a tunnel, route `api.<domain>` to
   `http://llm-serve.llm-serve.svc:80`, then on the VM
   `k3s kubectl -n llm-serve create secret generic cloudflared-token --from-literal=token=<TOKEN>`.
4. Make the GHCR package public, or create an image pull secret.
5. GitHub: environment `production` with a required reviewer; secrets `PROD_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY`,
   `PROD_SSH_KNOWN_HOSTS` (pinned host key); variable `PROD_URL`. Put the public half of the deploy key in
   `/home/deploy/.ssh/authorized_keys`.
6. Add a Cloudflare WAF rate-limiting rule on `/generate` and decide whether to require an API key. A public LLM
   endpoint is an abuse target; the engine's own 429 admission control only protects capacity.
7. Run the `deploy-production` workflow with `image_tag: stable`. Then update the "Production deployment" statements
   in `docs/07`, the README and the page's verification matrix from not-verified to verified, with what you observed.

## 7. When a gate fails

| Symptom | Meaning | What to do |
|---|---|---|
| `ci` red | correctness, lint, build or page-data drift | fix it; nothing else runs. If "Page data is current" fails, run `python scripts/build_site.py` and commit `site-src/src/data.json` (it embeds the test count and line counts) |
| release `drill` red | rollout or rollback path is broken | the job prints pods and events; a build that starts but never becomes Ready is expected in the drill, so read the step that failed |
| release `canary` red | good release not promoted, or bad release not aborted | the job dumps the Rollout, ReplicaSets, AnalysisRuns and controller logs |
| release `perf` red | candidate slower than the last stable beyond calibrated noise | download the `perf-gate` artifact. Re-run once to rule out a bad runner; if it repeats, it is a real regression: fix or revert. Do not lower the threshold |
| `perf` "inconclusive" | the runner cannot serve the offered load at all | recalibrate (section 5); do not skip the gate |
| `stable` did not move | at least one gate failed | `stable` still points at the last good release, which is the point |

## 8. Limitations, stated once

* No long-lived cluster and no real traffic: every rollout in this pipeline happens on an ephemeral kind cluster.
* Canary traffic is split by replica count (1 of 4 pods), not by exact weight, and kube-proxy balances per connection.
  A service mesh, ingress or Gateway API would give exact weights.
* The canary judges rejections, not latency. Latency SLOs are gated by the performance gate; a latency-based analysis
  on shared runners would be flaky.
* The performance gate detects relative slowdowns of about 15% or more, on one CPU shape at one load level. Only
  synthetic slowdowns (less CPU) have been tested, not a real code regression.
* The smoke test asserts no latency, deliberately.
* In production the load generator is only a two-request prober, so an SLO analysis of a real release depends on real
  traffic being present too.
* The HPA is removed in the CI and production overlays (no metrics-server in kind; it would also fight the Rollout).
  It is validated only by rendering.

## 9. Record of what has run

| What | Where | Result |
|---|---|---|
| ci, five jobs | GitHub Actions, every push to main | green |
| release, five jobs | first green run 35436785477 (drill only); full pipeline 35440722193 | green |
| canary drill | local kind, and release run 35438689281 and later | good release promoted, bad release aborted |
| perf gate A/A | local (0.94 / 0.95); runner at 2 req/s (0.976 / 1.001) | noise about 2 to 6% |
| perf gate synthetic slowdown | local (0.30 / 0.33); runner (0.146 / 0.636) | fail, as intended |
| production overlay dry run | inside the canary drill | accepted by the API server |
| deploy-production, provision_vm.sh | never | not run |
