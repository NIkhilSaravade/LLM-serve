"""Allocators for KV memory.

`SlotManager` (M2/M3): every request reserves one full-length contiguous slot up front,
whatever length it turns out to need. This is exactly the waste M4 removes.
`BlockManager` (paged, M4) is added below in the M4 milestone.
"""
from __future__ import annotations

from engine.cache import BYTES_PER_TOKEN, MAX_LEN
from engine.request import Request


class SlotManager:
    def __init__(self, n_slots: int, max_len: int = MAX_LEN) -> None:
        self.n_slots, self.max_len = n_slots, max_len
        self.free_slots = list(range(n_slots - 1, -1, -1))
        self.live: dict[str, Request] = {}

    # Same interface the scheduler uses for every allocator.
    def can_allocate(self, req: Request, headroom: int = 0) -> bool:
        return len(self.free_slots) > 0

    def allocate(self, req: Request) -> None:
        req.block_table = [self.free_slots.pop()]
        self.live[req.request_id] = req

    def append_slot(self, req: Request) -> bool:
        return True  # the whole slot was reserved at admission

    def free(self, req: Request) -> None:
        self.free_slots.append(req.block_table[0])
        req.block_table = []
        self.live.pop(req.request_id, None)

    def stats(self) -> dict:
        """used/total in slots; live tokens vs reserved capacity for memory efficiency."""
        return {"used": self.n_slots - len(self.free_slots), "total": self.n_slots,
                "live_tokens": sum(r.seq_len for r in self.live.values()),
                "capacity_tokens": len(self.live) * self.max_len}

    @staticmethod
    def slots_for_budget(budget_bytes: int, max_len: int = MAX_LEN) -> int:
        return max(1, budget_bytes // (max_len * BYTES_PER_TOKEN))
