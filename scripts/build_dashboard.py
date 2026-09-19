"""Generate deploy/grafana/dashboards/llm-serve.json. Run: python scripts/build_dashboard.py

Generated rather than hand-edited so panel queries stay consistent, and so
tests/test_ops.py can check that every metric the dashboard queries is actually exposed.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "deploy" / "grafana" / "dashboards" / "llm-serve.json"
DS = {"type": "prometheus", "uid": "prom"}


def q(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def panel(pid: int, title: str, targets: list[dict], x: int, y: int, w: int = 8, h: int = 8,
          kind: str = "timeseries", unit: str = "short", desc: str = "", thresholds=None,
          fmin=None) -> dict:
    p = {"id": pid, "type": kind, "title": title, "description": desc, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
         "fieldConfig": {"defaults": {"unit": unit}, "overrides": []}, "options": {}}
    if fmin is not None:
        p["fieldConfig"]["defaults"]["min"] = fmin
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute", "steps": [{"color": c, "value": v} for c, v in thresholds]}
        p["fieldConfig"]["defaults"]["custom"] = {"thresholdsStyle": {"mode": "line"}}
    return p


def quant(metric: str, qt: float) -> str:
    return f"histogram_quantile({qt}, sum by (le) (rate({metric}_bucket[5m])))"


panels = [
    panel(1, "TTFT within SLO (2 s)", [q('1 - llm:ttft_slo_bad_ratio:rate5m')], 0, 0, 6, 5, "stat",
          "percentunit", "Share of requests whose first token arrived within 2 s (SLO target 99%).",
          [("red", None), ("orange", 0.95), ("green", 0.99)]),
    panel(2, "Rejection ratio (429)", [q("llm:rejection_ratio:rate5m")], 6, 0, 6, 5, "stat", "percentunit",
          "Share of requests refused by admission control.", [("green", None), ("orange", 0.01), ("red", 0.05)]),
    panel(3, "Queue depth / cap", [q("llm_queue_depth", "depth"), q("llm_queue_cap", "cap", "B")], 12, 0, 6, 5,
          "stat", "short"),
    panel(4, "KV cache in use", [q("llm_kv_units_used / llm_kv_units_total")], 18, 0, 6, 5, "gauge", "percentunit",
          "Blocks (paged) or slots (contiguous) in use.", [("green", None), ("orange", 0.8), ("red", 0.95)], 0),

    panel(5, "Requests / s by outcome", [q("sum by (status) (rate(llm_requests_total[1m]))", "{{status}}")],
          0, 5, 8, 8, unit="reqps"),
    panel(6, "Time to first token", [q(quant("llm_ttft_seconds", 0.5), "p50"),
                                     q(quant("llm_ttft_seconds", 0.95), "p95", "B"),
                                     q(quant("llm_ttft_seconds", 0.99), "p99", "C")],
          8, 5, 8, 8, unit="s", desc="What a user feels as 'did it hang'. SLO: p99 < 2 s.",
          thresholds=[("transparent", None), ("red", 2)]),
    panel(7, "Time per output token", [q(quant("llm_tpot_seconds", 0.5), "p50"),
                                       q(quant("llm_tpot_seconds", 0.99), "p99", "B")],
          16, 5, 8, 8, unit="s", desc="Reading speed. SLO: p99 < 200 ms.",
          thresholds=[("transparent", None), ("red", 0.2)]),

    panel(8, "Output tokens / s", [q("rate(llm_generated_tokens_total[1m])", "tokens/s")], 0, 13, 8, 8),
    panel(9, "Queue and running requests", [q("llm_queue_depth", "waiting"),
                                            q("llm_running_requests", "running", "B"),
                                            q("llm_max_batch", "max batch", "C")], 8, 13, 8, 8),
    panel(10, "End-to-end latency p99", [q(quant("llm_e2e_seconds", 0.99), "p99")], 16, 13, 8, 8, unit="s"),

    panel(11, "KV memory: token efficiency", [q("llm_kv_token_efficiency", "live tokens / allocated")],
          0, 21, 8, 8, unit="percentunit",
          desc="Paged: near 1. Contiguous slots reserve 1024 tokens each, so this stays low.", fmin=0),
    panel(12, "Preemptions / s", [q("rate(llm_preemptions_total[5m])", "evictions/s")], 8, 21, 8, 8,
          desc="Requests evicted for KV memory and recomputed later."),
    panel(13, "Decode steps / s", [q("rate(llm_decode_steps_total[1m])", "steps/s")], 16, 21, 8, 8),
]

dash = {
    "uid": "llm-serve", "title": "llm-serve", "tags": ["llm", "serving"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "refresh": "5s", "time": {"from": "now-30m", "to": "now"},
    "panels": panels, "templating": {"list": []}, "annotations": {"list": []},
}

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
