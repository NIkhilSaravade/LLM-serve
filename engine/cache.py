"""KV cache storage.

M1: `ContiguousKVCache`, one sequence, shaped [layers, 2, heads, max_len, head_dim].
M2: `SlotPool`, a fixed number of contiguous per-sequence slots; a batch reads and writes
    through a `BatchAccess` so the model runner never touches the storage layout.
M4 adds a paged block pool in this file.
"""
from __future__ import annotations

import torch

N_LAYERS = 12
N_HEADS = 12
HEAD_DIM = 64
MAX_LEN = 1024
# 2 (K,V) * 12 layers * 768 dims * 4 bytes = 73,728 bytes per token (docs/01-architecture.md)
BYTES_PER_TOKEN = 2 * N_LAYERS * N_HEADS * HEAD_DIM * 4


class ContiguousKVCache:
    """Single-sequence cache (M1). The layout M4 will replace."""

    def __init__(self, max_len: int = MAX_LEN) -> None:
        # empty, not zeros: unread positions are never attended to, and untouched pages
        # are not committed by the OS.
        self.data = torch.empty(N_LAYERS, 2, N_HEADS, max_len, HEAD_DIM)
        self.max_len = max_len
        self.length = 0  # tokens currently stored

    def write(self, layer: int, start: int, k: torch.Tensor, v: torch.Tensor) -> None:
        """k, v: [1, heads, T, head_dim] for positions start .. start+T-1."""
        t = k.shape[2]
        self.data[layer, 0, :, start:start + t] = k[0]
        self.data[layer, 1, :, start:start + t] = v[0]

    def read(self, layer: int, n: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Return K, V for the first n positions as [1, heads, n, head_dim] views."""
        return self.data[layer, 0, :, :n].unsqueeze(0), self.data[layer, 1, :, :n].unsqueeze(0)

    def reset(self) -> None:
        self.length = 0


class BatchAccess:
    """One forward step's view of the cache for a batch of rows.

    Row i already holds `starts[i]` tokens and gets `ns[i]` new ones this step (prefill:
    start=0, n=prompt length; decode: start=seq_len-1, n=1). New tokens are right-padded
    to T = max(ns); pad positions are never written and never attended to by real rows.
    """

    def __init__(self, starts: list[int], ns: list[int]) -> None:
        self.starts, self.ns = starts, ns
        self.b, self.t = len(starts), max(ns)
        self.totals = [s + n for s, n in zip(starts, ns)]
        self.lk = max(self.totals)  # subclasses may round this up (paged: whole blocks)

    def build_mask(self, lk: int) -> tuple[torch.Tensor | None, bool]:
        """Return (bool mask [B,1,T,lk] or None, is_causal).

        Query t of row i is at absolute position starts[i]+t. It may attend to key j iff
        j <= starts[i]+t (causal) and j < totals[i] (no padding). Getting this wrong gives
        fluent, wrong text, so the single-row cases keep the exact M1 kernels.
        """
        if self.b == 1 and self.starts[0] == 0 and self.t > 1:
            return None, True            # plain prefill: causal, nothing padded
        if self.b == 1 and self.t == 1:
            return None, False           # single decode token sees everything
        keys = torch.arange(lk)[None, None, :]
        q_abs = torch.tensor(self.starts)[:, None] + torch.arange(self.t)[None, :]
        total = torch.tensor(self.totals)[:, None, None]
        return ((keys <= q_abs[:, :, None]) & (keys < total)).unsqueeze(1), False

    def positions(self) -> torch.Tensor:
        pos = torch.tensor(self.starts)[:, None] + torch.arange(self.t)[None, :]
        return pos.clamp_(max=MAX_LEN - 1)  # clamped only for pad columns of short rows

    def write(self, layer: int, k: torch.Tensor, v: torch.Tensor) -> None:
        raise NotImplementedError

    def gather(self, layer: int) -> tuple[torch.Tensor, torch.Tensor]:
        raise NotImplementedError


class SlotAccess(BatchAccess):
    def __init__(self, pool: "SlotPool", slots: list[int], starts: list[int], ns: list[int]):
        super().__init__(starts, ns)
        self.pool, self.slots = pool, slots
        self.slots_t = torch.tensor(slots)
        self.starts_t = torch.tensor(starts)
        self.mask, self.is_causal = self.build_mask(self.lk)

    def write(self, layer: int, k: torch.Tensor, v: torch.Tensor) -> None:
        """k, v: [B, heads, T, head_dim]."""
        pk, pv = self.pool.k[layer], self.pool.v[layer]
        if self.t == 1:  # decode: one vectorised scatter for the whole batch
            pk[self.slots_t, :, self.starts_t] = k[:, :, 0]
            pv[self.slots_t, :, self.starts_t] = v[:, :, 0]
            return
        for i, (slot, s, n) in enumerate(zip(self.slots, self.starts, self.ns)):
            pk[slot, :, s:s + n] = k[i, :, :n]
            pv[slot, :, s:s + n] = v[i, :, :n]

    def gather(self, layer: int) -> tuple[torch.Tensor, torch.Tensor]:
        # Copies [B, heads, lk, head_dim]. LIMITATION: a production kernel would read the
        # slots in place instead of materialising a padded copy for every layer and step.
        return (self.pool.k[layer][self.slots_t, :, :self.lk],
                self.pool.v[layer][self.slots_t, :, :self.lk])


class SlotPool:
    """`n_slots` contiguous sequences of `max_len` tokens each, per layer."""

    def __init__(self, n_slots: int, max_len: int = MAX_LEN) -> None:
        self.n_slots, self.max_len = n_slots, max_len
        # zeros, not empty: touch every page at startup, like a real server that preallocates
        # its pool. With empty(), first-touch page faults land inside timed regions and made
        # identical runs differ by ~25% depending on whether the allocator recycled memory.
        self.k = [torch.zeros(n_slots, N_HEADS, max_len, HEAD_DIM) for _ in range(N_LAYERS)]
        self.v = [torch.zeros(n_slots, N_HEADS, max_len, HEAD_DIM) for _ in range(N_LAYERS)]

    def access(self, block_tables: list[list[int]], starts: list[int], ns: list[int]) -> SlotAccess:
        # For slot-backed requests the "block table" is a one-element list holding the slot.
        return SlotAccess(self, [bt[0] for bt in block_tables], starts, ns)


class PagedAccess(BatchAccess):
    """Reads and writes K/V through per-request block tables (M4)."""

    def __init__(self, pool: "PagedPool", block_tables: list[list[int]], starts: list[int],
                 ns: list[int]) -> None:
        super().__init__(starts, ns)
        self.pool, self.tables = pool, block_tables
        bs = pool.block_size
        nb = -(-self.lk // bs)                      # blocks covering the longest row
        # Rows with fewer blocks are padded with block 0: it is a real block whose contents
        # are simply masked out (`key < total`), so it never influences a result.
        padded = [bt[:nb] + [0] * (nb - len(bt[:nb])) for bt in block_tables]
        self.bt_t = torch.tensor(padded)
        # Same masks as the contiguous path, at the exact key width `lk`, so the attention
        # kernels (and therefore the numerics) are identical.
        self.mask, self.is_causal = self.build_mask(self.lk)
        if self.t == 1:
            self.dec_blocks = torch.tensor([bt[s // bs] for bt, s in zip(block_tables, starts)])
            self.dec_offs = torch.tensor(starts) % bs

    def write(self, layer: int, k: torch.Tensor, v: torch.Tensor) -> None:
        pk, pv = self.pool.k[layer], self.pool.v[layer]
        if self.t == 1:  # decode: one vectorised scatter, one token per row
            pk[self.dec_blocks, :, self.dec_offs] = k[:, :, 0]
            pv[self.dec_blocks, :, self.dec_offs] = v[:, :, 0]
            return
        bs = self.pool.block_size
        for i, (bt, s, n) in enumerate(zip(self.tables, self.starts, self.ns)):
            pos = torch.arange(s, s + n)
            blocks = torch.tensor(bt)[pos // bs]
            offs = pos % bs
            pk[blocks, :, offs] = k[i, :, :n].transpose(0, 1)
            pv[blocks, :, offs] = v[i, :, :n].transpose(0, 1)

    def gather(self, layer: int) -> tuple[torch.Tensor, torch.Tensor]:
        # LIMITATION: attention needs K/V that live in scattered blocks. vLLM's PagedAttention
        # is a fused CUDA kernel that walks the block table inside the attention computation.
        # We cannot write that here, so every layer of every step copies the needed blocks
        # into a temporary contiguous buffer and runs ordinary attention on the copy. Correct,
        # but it moves roughly the whole KV cache through memory once per token.
        b, nb = self.bt_t.shape
        bs = self.pool.block_size
        out = []
        for pool_t in (self.pool.k[layer], self.pool.v[layer]):
            g = pool_t[self.bt_t]                                   # [B, nb, H, bs, D]
            g = g.permute(0, 2, 1, 3, 4).reshape(b, N_HEADS, nb * bs, HEAD_DIM)
            out.append(g[:, :, :self.lk])                           # drop the tail of the last block
        return out[0], out[1]


class PagedPool:
    """One flat pool of fixed-size blocks per layer: [num_blocks, heads, block_size, head_dim]."""

    def __init__(self, num_blocks: int, block_size: int) -> None:
        self.num_blocks, self.block_size = num_blocks, block_size
        # zeros so pages are touched at startup (see SlotPool).
        self.k = [torch.zeros(num_blocks, N_HEADS, block_size, HEAD_DIM) for _ in range(N_LAYERS)]
        self.v = [torch.zeros(num_blocks, N_HEADS, block_size, HEAD_DIM) for _ in range(N_LAYERS)]

    def access(self, block_tables: list[list[int]], starts: list[int], ns: list[int]) -> PagedAccess:
        return PagedAccess(self, block_tables, starts, ns)
