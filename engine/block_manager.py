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

    def fits_ever(self, prompt_len: int, max_new: int) -> bool:
        return prompt_len + max_new <= self.max_len

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
        # At least one slot even if the budget is smaller than a slot, otherwise nothing runs.
        return max(1, budget_bytes // (max_len * BYTES_PER_TOKEN))


class BlockManager:
    """Paged allocator (M4): a free list of fixed-size physical blocks and, per request, a
    block table saying which physical block holds each logical block.

    Blocks are handed out only when a sequence actually reaches them, so memory used tracks
    tokens generated, not the maximum a request might reach.
    """

    def __init__(self, num_blocks: int, block_size: int, reserve_max_new: bool = True) -> None:
        self.num_blocks, self.block_size = num_blocks, block_size
        # LIFO free list; blocks are NOT handed out in address order once requests come and go.
        self.free_blocks = list(range(num_blocks - 1, -1, -1))
        self.live: dict[str, Request] = {}
        # M4 has no preemption, so it must never over-commit: admit a request only if the
        # worst-case block count (prompt + max_new_tokens) of everyone running still fits.
        # Blocks are still allocated lazily; this only bounds admission. M5 replaces it with
        # optimistic admission plus preemption.
        self.reserve_max_new = reserve_max_new
        self.committed: dict[str, int] = {}

    def blocks_needed(self, n_tokens: int) -> int:
        return -(-n_tokens // self.block_size)

    def fits_ever(self, prompt_len: int, max_new: int) -> bool:
        """False if the request could not complete even with the whole pool to itself.
        Without this check such a request would be preempted and readmitted forever."""
        return self.blocks_needed(prompt_len + max_new) <= self.num_blocks

    def can_allocate(self, req: Request, headroom: int = 0) -> bool:
        need = self.blocks_needed(req.seq_len)
        if self.reserve_max_new:
            worst = self.blocks_needed(len(req.prompt_token_ids) + req.max_new_tokens)
            return sum(self.committed.values()) + worst <= self.num_blocks
        return len(self.free_blocks) >= need + headroom

    def allocate(self, req: Request) -> None:
        """Initial blocks for the prompt (plus anything already generated, after preemption)."""
        need = self.blocks_needed(req.seq_len)
        assert len(self.free_blocks) >= need, "allocate() called without can_allocate()"
        req.block_table = [self.free_blocks.pop() for _ in range(need)]
        self.live[req.request_id] = req
        self.committed[req.request_id] = self.blocks_needed(
            len(req.prompt_token_ids) + req.max_new_tokens)

    def append_slot(self, req: Request) -> bool:
        """Make room for the token about to be fed (position seq_len - 1). It needs one new
        block exactly when that position is the first slot of a block."""
        need = self.blocks_needed(req.seq_len)
        while len(req.block_table) < need:
            if not self.free_blocks:
                return False
            req.block_table.append(self.free_blocks.pop())
        return True

    def free(self, req: Request) -> None:
        self.free_blocks.extend(reversed(req.block_table))
        req.block_table = []
        self.live.pop(req.request_id, None)
        self.committed.pop(req.request_id, None)

    def stats(self) -> dict:
        used = self.num_blocks - len(self.free_blocks)
        return {"used": used, "total": self.num_blocks,
                "live_tokens": sum(r.seq_len for r in self.live.values()),
                "capacity_tokens": used * self.block_size}

    @staticmethod
    def blocks_for_budget(budget_bytes: int, block_size: int) -> int:
        return budget_bytes // (block_size * BYTES_PER_TOKEN)
