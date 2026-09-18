"""KV cache storage.

M1: one contiguous cache for ONE sequence, shaped [layers, 2, heads, max_len, head_dim].
Later milestones add a slot pool (M2/M3) and a paged block pool (M4) in this file.
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
    """Single-sequence cache. The layout M4 will replace."""

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
