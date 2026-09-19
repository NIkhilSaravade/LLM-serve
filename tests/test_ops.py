"""Operational surface: health, readiness, version, Prometheus metrics, request ids."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from engine.api import create_app
from engine.config import EngineConfig


def scrape(c: TestClient) -> str:
    r = c.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    return r.text


def value(text: str, name: str, labels: str = "") -> float:
    m = re.search(rf"^{re.escape(name)}{re.escape(labels)} ([0-9.e+-]+)$", text, re.M)
    assert m, f"{name}{labels} not exposed"
    return float(m.group(1))


@pytest.fixture(scope="module")
def client():
    cfg = EngineConfig(backend="paged", block_size=16, kv_budget_mib=64, max_batch=4,
                       preemption=True, max_queue=64)
    with TestClient(create_app(cfg)) as c:
        yield c


def test_liveness_readiness_and_version(client):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/ready").json() == {"ready": True}
    v = client.get("/version").json()
    assert v["model"] == "gpt2" and v["config"]["backend"] == "paged" and "torch" in v


def test_warmup_is_not_counted(client):
    assert value(scrape(client), "llm_generated_tokens_total") == 0.0


def test_metrics_after_a_request(client):
    r = client.post("/generate", json={"prompt_token_ids": [5] * 12, "max_new_tokens": 6,
                                       "ignore_eos": True}, headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200 and r.headers["x-request-id"] == "abc-123"
    assert r.json()["request_id"] == "abc-123" and len(r.json()["token_ids"]) == 6
    t = scrape(client)
    assert value(t, "llm_requests_total", '{status="ok"}') == 1.0
    assert value(t, "llm_generated_tokens_total") == 6.0
    assert value(t, "llm_prompt_tokens_total") == 12.0
    assert value(t, "llm_ttft_seconds_count") == 1.0
    assert value(t, "llm_tpot_seconds_count") == 1.0
    assert value(t, "llm_e2e_seconds_count") == 1.0
    # State gauges are read at scrape time; all requests are finished, so nothing is running.
    assert value(t, "llm_running_requests") == 0.0
    assert value(t, "llm_queue_depth") == 0.0
    assert value(t, "llm_kv_units_total") > 0
    assert value(t, "llm_engine_thread_alive") == 1.0
    assert 'llm_build_info{' in t


def test_zero_valued_series_exist_from_the_start(client):
    t = scrape(client)
    for s in ("rejected", "too_large", "cancelled", "error"):
        assert f'llm_requests_total{{status="{s}"}}' in t   # so rate() works before the first event


def test_too_large_request_is_counted_and_rejected(client):
    before = value(scrape(client), "llm_requests_total", '{status="too_large"}')
    r = client.post("/generate", json={"prompt_token_ids": [5] * 10, "max_new_tokens": 1000})
    assert r.status_code == 413
    assert value(scrape(client), "llm_requests_total", '{status="too_large"}') == before + 1


def test_bad_input_is_400(client):
    assert client.post("/generate", json={}).status_code == 400
    assert client.post("/generate", json={"prompt_token_ids": []}).status_code == 400


def test_stats_endpoint_for_the_benchmark_harness(client):
    assert "throughput_tok_per_s" in client.get("/stats").json()
    assert client.post("/stats/reset").json() == {"ok": True}


def test_overload_returns_429_and_is_counted():
    cfg = EngineConfig(backend="contiguous", max_batch=1, max_queue=0)   # queue cap 0: always full
    with TestClient(create_app(cfg)) as c:
        r = c.post("/generate", json={"prompt_token_ids": [1, 2, 3], "max_new_tokens": 2})
        assert r.status_code == 429 and r.headers["retry-after"] == "1"
        assert value(scrape(c), "llm_requests_total", '{status="rejected"}') == 1.0


# ---------------------------------------------------------------- deploy config stays honest
import json as _json  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"


def _exposed_names(text: str) -> set[str]:
    names = set(re.findall(r"^# TYPE (\S+) ", text, re.M))
    # histograms expose _bucket/_count/_sum, counters _total/_created
    for n in list(names):
        names |= {n + "_bucket", n + "_count", n + "_sum", n + "_total"}
    return names


def _queried_metrics(expr: str) -> set[str]:
    # recording rules contain ':' (llm:ttft_...) and are not scraped metrics
    return {m for m in re.findall(r"(?<![\w:])(llm_[a-z0-9_]+)(?![\w:])", expr)}


def test_every_metric_the_dashboard_queries_is_exposed(client):
    exposed = _exposed_names(scrape(client))
    dash = _json.loads((DEPLOY / "grafana" / "dashboards" / "llm-serve.json").read_text())
    used = set()
    for p in dash["panels"]:
        for t in p["targets"]:
            used |= _queried_metrics(t["expr"])
    missing = used - exposed
    assert used and not missing, f"dashboard queries metrics the server does not expose: {missing}"


def test_every_metric_the_alerts_use_is_exposed(client):
    exposed = _exposed_names(scrape(client))
    groups = yaml.safe_load((DEPLOY / "prometheus" / "alerts.yml").read_text())["groups"]
    used = set()
    for g in groups:
        for r in g["rules"]:
            used |= _queried_metrics(r["expr"])
    assert used - exposed == set() and used


def test_alerts_have_severity_summary_and_runbook_that_exists():
    if not (ROOT / "docs").is_dir():
        pytest.skip("docs/ is kept offline; the runbook anchors are checked only where it exists")
    ops = (ROOT / "docs" / "07-operations.md").read_text(encoding="utf-8")
    groups = yaml.safe_load((DEPLOY / "prometheus" / "alerts.yml").read_text())["groups"]
    alerts = [r for g in groups for r in g["rules"] if "alert" in r]
    assert len(alerts) >= 8
    for a in alerts:
        assert a["labels"]["severity"] in {"critical", "page", "warning"}, a["alert"]
        assert a["annotations"]["summary"], a["alert"]
        anchor = a["annotations"]["runbook"].split("#", 1)[1]
        assert f'id="{anchor}"' in ops, f"{a['alert']}: no runbook anchor '{anchor}' in docs/07-operations.md"


def test_configmap_is_a_valid_engine_config_and_matches_the_pod_limits():
    from engine.config import EngineConfig
    cm = yaml.safe_load((DEPLOY / "k8s" / "configmap.yaml").read_text())["data"]
    cfg = EngineConfig(**_json.loads(cm["LLM_SERVE_CONFIG"]))
    dep = yaml.safe_load((DEPLOY / "k8s" / "deployment.yaml").read_text())
    c = dep["spec"]["template"]["spec"]["containers"][0]
    cpu = int(c["resources"]["limits"]["cpu"])
    assert int(cm["LLM_SERVE_THREADS"]) == cpu == int(c["resources"]["requests"]["cpu"])
    mem_gib = int(c["resources"]["limits"]["memory"].removesuffix("Gi"))
    assert cfg.kv_budget_mib / 1024 + 1.5 <= mem_gib, "pod memory limit too small for KV pool + model"
    assert dep["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert c["securityContext"]["readOnlyRootFilesystem"] and not c["securityContext"]["allowPrivilegeEscalation"]
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert probe in c


def test_generated_prometheus_rule_is_current():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rpr", ROOT / "scripts" / "render_prometheus_rule.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.DST.read_text(encoding="utf-8") == mod.render()


def test_dashboard_is_current():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bd", ROOT / "scripts" / "build_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert _json.loads(mod.OUT.read_text()) == _json.loads(_json.dumps(mod.dash))


# ---------------------------------------------------------------- release machinery stays honest
def _canary_docs() -> list[dict]:
    return [d for f in ("analysis-template.yaml", "rollout.yaml", "prometheus.yaml")
            for d in yaml.safe_load_all((DEPLOY / "overlays" / "canary" / f).read_text()) if d]


def test_canary_analysis_only_queries_metrics_the_server_exposes(client):
    exposed = _exposed_names(scrape(client))
    template = next(d for d in _canary_docs() if d["kind"] == "AnalysisTemplate")
    used: set[str] = set()
    for m in template["spec"]["metrics"]:
        used |= _queried_metrics(m["provider"]["prometheus"]["query"])
    assert used and used - exposed == set(), f"analysis queries metrics the server does not expose: {used - exposed}"


def test_canary_analysis_uses_the_alert_threshold_and_fails_closed():
    template = next(d for d in _canary_docs() if d["kind"] == "AnalysisTemplate")
    by_name = {m["name"]: m for m in template["spec"]["metrics"]}
    alert = yaml.safe_load((DEPLOY / "prometheus" / "alerts.yml").read_text())
    expr = next(r["expr"] for g in alert["groups"] for r in g["rules"] if r.get("alert") == "LLMHighRejectionRate")
    threshold = float(re.search(r">\s*([0-9.]+)", expr).group(1))
    # the gate that stops a release must not be looser than the alert that pages about it
    assert f"< {threshold}" in by_name["rejection-ratio"]["successCondition"]
    # a canary that receives no traffic proves nothing: silence must fail, not pass
    assert "canary-receives-traffic" in by_name
    assert by_name["canary-receives-traffic"]["consecutiveErrorLimit"] >= 1


def test_the_label_the_analysis_filters_on_is_the_one_prometheus_attaches():
    docs = _canary_docs()
    template = next(d for d in docs if d["kind"] == "AnalysisTemplate")
    config = next(d for d in docs if d["kind"] == "ConfigMap")
    prom = config["data"]["prometheus.yml"]
    assert 'target_label: pod_hash' in prom and "rollouts_pod_template_hash" in prom
    assert all("pod_hash=" in m["provider"]["prometheus"]["query"] for m in template["spec"]["metrics"])


def test_rollout_reuses_the_deployment_it_points_at():
    rollout = next(d for d in _canary_docs() if d["kind"] == "Rollout")
    ref = rollout["spec"]["workloadRef"]
    base = yaml.safe_load((DEPLOY / "k8s" / "deployment.yaml").read_text())
    assert (ref["kind"], ref["name"]) == (base["kind"], base["metadata"]["name"])
    assert rollout["spec"]["strategy"]["canary"]["maxUnavailable"] == 0


def test_production_overlay_renders_and_keeps_the_safety_settings():
    import shutil
    import subprocess
    if not shutil.which("kubectl"):
        pytest.skip("kubectl not installed")
    out = subprocess.run(["kubectl", "kustomize", str(DEPLOY / "production")], capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    kinds = {d["kind"] for d in docs}
    assert {"Rollout", "AnalysisTemplate", "Deployment", "Service", "PodDisruptionBudget"} <= kinds
    assert not any(d["kind"] == "HorizontalPodAutoscaler" for d in docs), "an HPA would fight the Rollout"
    assert "REPLACE_WITH_GIT_SHA" in out, "the image must stay a placeholder until deploy time"
    assert ":latest" not in out
    secret_refs = [d for d in docs if d["kind"] == "Secret"]
    assert secret_refs == [], "no secret may be committed; the tunnel token is created out of band"


@pytest.mark.parametrize("overlay", ["overlays/canary", "production"])
def test_every_namespaced_resource_lands_in_the_llm_serve_namespace(overlay):
    """A base's `namespace:` only covers the base's own resources; anything an overlay adds needs its own. The first
    canary drill caught Prometheus, the Rollout and the analysis template landing in `default`."""
    import shutil
    import subprocess
    if not shutil.which("kubectl"):
        pytest.skip("kubectl not installed")
    out = subprocess.run(["kubectl", "kustomize", str(DEPLOY / overlay)], capture_output=True, text=True, check=True).stdout
    cluster_scoped = {"Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition"}
    stray = [f'{d["kind"]}/{d["metadata"]["name"]}' for d in yaml.safe_load_all(out)
             if d and d["kind"] not in cluster_scoped and d["metadata"].get("namespace") != "llm-serve"]
    assert stray == [], f"resources outside the llm-serve namespace: {stray}"
