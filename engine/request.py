"""Request object and its state machine (docs/01-architecture.md)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


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
    ignore_eos: bool = False  # benchmarks fix output length exactly (as vLLM's bench does)
    output_token_ids: list[int] = field(default_factory=list)
    state: RequestState = RequestState.WAITING
    arrival_time: float = field(default_factory=time.perf_counter)
    first_token_time: float | None = None
    finish_time: float | None = None
    finish_reason: str | None = None
    block_table: list[int] = field(default_factory=list)  # slot (M2/M3) or blocks (M4)
    admit_seq: int = -1          # order of admission, used by the eviction policy (M5)
    preempt_count: int = 0       # starvation guard (M5)
    cancelled: bool = False      # set from the API thread when the client disconnects
    # Called with (token_id, finished) for every generated token, from the engine thread.
    sink: Callable[[int, bool], None] | None = field(default=None, repr=False)

    @property
    def seq_len(self) -> int:
        # Drives position ids, masks and block counts in later milestones.
        return len(self.prompt_token_ids) + len(self.output_token_ids)

    @property
    def finished(self) -> bool:
        return self.finish_reason is not None
