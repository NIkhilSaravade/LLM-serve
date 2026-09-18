"""Request object and its state machine (docs/01-architecture.md)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class RequestState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    # PREEMPTED arrives in M5.


@dataclass
class Request:
    request_id: str
    prompt_token_ids: list[int]
    max_new_tokens: int
    output_token_ids: list[int] = field(default_factory=list)
    state: RequestState = RequestState.WAITING
    arrival_time: float = field(default_factory=time.perf_counter)
    first_token_time: float | None = None
    finish_time: float | None = None
    block_table: list[int] = field(default_factory=list)  # unused until M4

    @property
    def seq_len(self) -> int:
        # Drives position ids, masks and block counts in later milestones.
        return len(self.prompt_token_ids) + len(self.output_token_ids)
