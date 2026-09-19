"""Prometheus metrics for operating the server (GET /metrics).

Two kinds of series:
  * event series (counters, latency histograms) are updated by the API layer when a request
    finishes;
  * state series (queue depth, running requests, KV blocks) are read from the scheduler at scrape
    time by a custom collector, so they are never stale and the engine thread is not slowed down.

The JSON summary the benchmark harness reads lives at /stats; this module is for operators.
"""
from __future__ import annotations

import os
import platform
from typing import TYPE_CHECKING

import torch
from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

if TYPE_CHECKING:  # pragma: no cover
    from engine.scheduler import Engine, EngineLoop

# Buckets chosen around the SLO in docs/07-operations.md (TTFT 2 s, TPOT 200 ms).
TTFT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60)
TPOT_BUCKETS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2)
E2E_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 30, 60, 120)

# Never label by request id or prompt: unbounded cardinality would take Prometheus down.
STATUSES = ("ok", "rejected", "too_large", "cancelled", "error")


class Observability:
    def __init__(self, engine: "Engine", loop: "EngineLoop") -> None:
        self.registry = CollectorRegistry()   # per app, so tests can build many apps
        self.requests = Counter("llm_requests_total", "Requests by outcome.", ["status"],
                                registry=self.registry)
        for s in STATUSES:
            self.requests.labels(s)           # export zero-valued series so rate() works from t=0
        self.tokens = Counter("llm_generated_tokens_total", "Output tokens produced.",
                              registry=self.registry)
        self.prompt_tokens = Counter("llm_prompt_tokens_total", "Prompt tokens received.",
                                     registry=self.registry)
        self.ttft = Histogram("llm_ttft_seconds", "Arrival to first token.",
                              buckets=TTFT_BUCKETS, registry=self.registry)
        self.tpot = Histogram("llm_tpot_seconds", "Mean time per output token after the first.",
                              buckets=TPOT_BUCKETS, registry=self.registry)
        self.e2e = Histogram("llm_e2e_seconds", "Arrival to last token.",
                             buckets=E2E_BUCKETS, registry=self.registry)
        self.registry.register(_StateCollector(engine, loop))
        info = GaugeMetricFamily("llm_build_info", "Build and model identity.",
                                 labels=["git_sha", "model", "backend", "batching", "torch"])
        cfg = engine.cfg
        info.add_metric([os.environ.get("GIT_SHA", "unknown"), "gpt2", cfg.backend, cfg.batching,
                         torch.__version__], 1)
        self.registry.register(_Static([info]))

    def observe_finished(self, req) -> None:
        """Called once per request that ran to completion."""
        self.requests.labels("ok").inc()
        self.tokens.inc(len(req.output_token_ids))
        self.prompt_tokens.inc(len(req.prompt_token_ids))
        if req.first_token_time is not None:
            self.ttft.observe(req.first_token_time - req.arrival_time)
            n = len(req.output_token_ids)
            if n > 1 and req.finish_time is not None:
                self.tpot.observe((req.finish_time - req.first_token_time) / (n - 1))
        if req.finish_time is not None:
            self.e2e.observe(req.finish_time - req.arrival_time)


class _Static:
    def __init__(self, families) -> None:
        self.families = families

    def collect(self):
        yield from self.families


class _StateCollector:
    """Reads live scheduler state when Prometheus scrapes."""

    def __init__(self, engine: "Engine", loop: "EngineLoop") -> None:
        self.engine, self.loop = engine, loop

    def collect(self):
        sched = self.engine.sched
        g = lambda name, doc, v: GaugeMetricFamily(name, doc, value=v)  # noqa: E731
        yield g("llm_queue_depth", "Requests waiting to be admitted.", self.loop.queue_depth())
        yield g("llm_running_requests", "Requests currently in the decode batch.", len(sched.running))
        yield g("llm_queue_cap", "Admission-control queue cap (0 = unbounded).",
                self.engine.cfg.max_queue or 0)
        yield g("llm_max_batch", "Configured maximum decode batch size.", self.engine.cfg.max_batch)
        manager = getattr(self.engine, "manager", None)
        if manager is not None:
            st = manager.stats()
            yield g("llm_kv_units_used", "KV blocks (paged) or slots (contiguous) in use.", st["used"])
            yield g("llm_kv_units_total", "Total KV blocks or slots.", st["total"])
            cap = st["capacity_tokens"]
            yield g("llm_kv_token_efficiency", "Live tokens / allocated token capacity.",
                    st["live_tokens"] / cap if cap else 0.0)
        c = CounterMetricFamily("llm_preemptions_total", "Requests evicted for KV memory.")
        c.add_metric([], sched.metrics.preemptions)
        yield c
        c = CounterMetricFamily("llm_decode_steps_total", "Decode steps executed.")
        c.add_metric([], sched.metrics.steps)
        yield c
        yield g("llm_engine_thread_alive", "1 if the scheduler thread is running.",
                1 if self.loop._thread.is_alive() else 0)


def version_info(engine: "Engine") -> dict:
    return {"git_sha": os.environ.get("GIT_SHA", "unknown"), "model": "gpt2",
            "torch": torch.__version__, "python": platform.python_version(),
            "config": engine.cfg.to_dict()}
