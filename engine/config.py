"""Engine configuration. Every ablation row in docs/04 is one EngineConfig."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class EngineConfig:
    backend: str = "contiguous"      # naive | contiguous | paged
    batching: str = "continuous"     # static | continuous
    max_batch: int = 16              # decode slots (rows) per step
    kv_budget_mib: int = 1024        # total KV memory; slots / blocks are derived from it
    block_size: int = 16             # tokens per block (paged)
    num_threads: int = 4
    max_queue: int | None = None     # admission control (M5); None = unbounded
    preemption: bool = False         # M5: optimistic admission + preempt-and-recompute

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_env(cls) -> "EngineConfig":
        raw = os.environ.get("LLM_SERVE_CONFIG")
        return cls(**json.loads(raw)) if raw else cls()
