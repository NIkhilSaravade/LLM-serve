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


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


@dataclass
class EngineMetrics:
    """Per-decode-step gauges, averaged over steps."""
    max_slots: int = 1
    steps: int = 0                      # decode steps
    occupied_slot_steps: int = 0        # sum over steps of rows doing useful work
    kv_used_steps: float = 0.0          # sum of (allocated units / total units)
    kv_eff_steps: float = 0.0           # sum of (live tokens / allocated token capacity)
    queue_depth_steps: int = 0
    pad_frac_steps: float = 0.0         # sum of wasted attention width per step (padding)
    prefills: int = 0
    prefill_seconds: float = 0.0
    decode_seconds: float = 0.0
    preemptions: int = 0                # M5
    rejected: int = 0                   # M5 admission control
    tokens_out: int = 0
    requests: list[RequestMetrics] = field(default_factory=list)

    def record_step(self, occupied: int, queue_depth: int = 0, kv_used: float = 0.0,
                    kv_eff: float = 0.0, pad_frac: float = 0.0) -> None:
        self.steps += 1
        self.occupied_slot_steps += occupied
        self.queue_depth_steps += queue_depth
        self.kv_used_steps += kv_used
        self.kv_eff_steps += kv_eff
        self.pad_frac_steps += pad_frac

    def record_request(self, req: Request) -> None:
        self.requests.append(request_metrics(req))
        self.tokens_out += len(req.output_token_ids)

    def reset(self) -> None:
        keep = self.max_slots
        self.__init__(max_slots=keep)  # type: ignore[misc]

    def summary(self, wall_seconds: float) -> dict:
        s = max(self.steps, 1)
        ttfts = [r.ttft for r in self.requests]
        tpots = [r.tpot for r in self.requests if r.tpot is not None]
        e2es = [r.e2e for r in self.requests]
        return {
            "requests": len(self.requests),
            "output_tokens": self.tokens_out,
            "throughput_tok_per_s": self.tokens_out / wall_seconds if wall_seconds else 0.0,
            "decode_steps": self.steps,
            "slot_utilisation": self.occupied_slot_steps / (s * self.max_slots),
            "kv_utilisation": self.kv_used_steps / s,
            "kv_token_efficiency": self.kv_eff_steps / s,
            "attn_padding_waste": self.pad_frac_steps / s,
            "mean_queue_depth": self.queue_depth_steps / s,
            "preemptions": self.preemptions,
            "rejected": self.rejected,
            "prefill_seconds": self.prefill_seconds,
            "decode_seconds": self.decode_seconds,
            "ttft_p50_s": percentile(ttfts, 50), "ttft_p99_s": percentile(ttfts, 99),
            "tpot_p50_s": percentile(tpots, 50), "tpot_p99_s": percentile(tpots, 99),
            "e2e_p50_s": statistics.median(e2es) if e2es else None,
            "e2e_p99_s": percentile(e2es, 99),
        }


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n")
