"""Counters and timings. Collected from M0 so later milestones never re-run for them.

Definitions follow docs/04-benchmark-methodology.md. Published numbers are always
computed here, never by hand.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from engine.request import Request


@dataclass
class RequestMetrics:
    ttft: float            # arrival -> first token, seconds
    e2e: float             # arrival -> last token, seconds
    tpot: float | None     # (e2e - ttft) / (output_tokens - 1); None for 1 token
    output_tokens: int
    prompt_tokens: int


def request_metrics(req: Request) -> RequestMetrics:
    assert req.first_token_time is not None and req.finish_time is not None
    ttft = req.first_token_time - req.arrival_time
    e2e = req.finish_time - req.arrival_time
    n = len(req.output_token_ids)
    tpot = (e2e - ttft) / (n - 1) if n > 1 else None
    return RequestMetrics(ttft, e2e, tpot, n, len(req.prompt_token_ids))


@dataclass
class EngineMetrics:
    """Per-step gauges, averaged over steps."""
    max_slots: int = 1
    steps: int = 0
    occupied_slot_steps: int = 0
    kv_blocks_total: int = 0            # 0 until the paged cache exists (M4)
    kv_blocks_used_steps: int = 0
    queue_depth_steps: int = 0
    preemptions: int = 0                # M5
    tokens_out: int = 0
    requests: list[RequestMetrics] = field(default_factory=list)

    def record_step(self, occupied: int, queue_depth: int = 0, kv_blocks_used: int = 0) -> None:
        self.steps += 1
        self.occupied_slot_steps += occupied
        self.queue_depth_steps += queue_depth
        self.kv_blocks_used_steps += kv_blocks_used

    def record_request(self, req: Request) -> None:
        self.requests.append(request_metrics(req))
        self.tokens_out += len(req.output_token_ids)

    def summary(self, wall_seconds: float) -> dict:
        s = max(self.steps, 1)
        ttfts = [r.ttft for r in self.requests]
        tpots = [r.tpot for r in self.requests if r.tpot is not None]
        return {
            "requests": len(self.requests),
            "output_tokens": self.tokens_out,
            "throughput_tok_per_s": self.tokens_out / wall_seconds if wall_seconds else 0.0,
            "slot_utilisation": self.occupied_slot_steps / (s * self.max_slots),
            "kv_utilisation": (self.kv_blocks_used_steps / (s * self.kv_blocks_total)
                               if self.kv_blocks_total else None),
            "mean_queue_depth": self.queue_depth_steps / s,
            "preemptions": self.preemptions,
            "ttft_median_s": statistics.median(ttfts) if ttfts else None,
            "tpot_median_s": statistics.median(tpots) if tpots else None,
        }


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n")
