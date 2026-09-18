"""Model loading, the M0 naive loop, and (M1+) our own cached forward pass.

M0 is deliberately the dumbest thing possible: every step re-runs the forward pass
over the ENTIRE sequence so far. No KV cache. Do not optimise; this is the floor
every later milestone is measured against.

M1 adds our own GPT-2 forward pass (weights taken from HuggingFace, math written here)
so the KV cache layout is ours to change in M4.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import torch
import torch.nn.functional as F
from transformers import GPT2LMHeadModel, GPT2TokenizerFast

from engine.cache import HEAD_DIM, N_HEADS, N_LAYERS, ContiguousKVCache
from engine.metrics import EngineMetrics
from engine.request import Request, RequestState

EOS_TOKEN_ID = 50256
MAX_CONTEXT = 1024
HIDDEN = N_HEADS * HEAD_DIM
# Pinned explicitly: leaving torch's default makes numbers machine-dependent
# (docs/04-benchmark-methodology.md). The same value must be used for every variant.
DEFAULT_NUM_THREADS = int(os.environ.get("LLM_SERVE_THREADS", "4"))


def _linear(x: torch.Tensor, w: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """GPT-2 'Conv1D': weight is [in, out]. addmm matches the HF kernel choice."""
    return torch.addmm(b, x.reshape(-1, x.shape[-1]), w).reshape(*x.shape[:-1], w.shape[1])


class ModelRunner:
    def __init__(self, num_threads: int = DEFAULT_NUM_THREADS) -> None:
        torch.set_num_threads(num_threads)
        self.num_threads = num_threads
        # transformers supplies weights and tokenizer ONLY. The loops below are ours.
        self.tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")
        self.model = GPT2LMHeadModel.from_pretrained("gpt2", dtype=torch.float32)
        self.model.eval()
        self.metrics = EngineMetrics(max_slots=1)
        self._load_weights()

    # ------------------------------------------------------------------ M0 (naive)
    @torch.inference_mode()
    def forward_logits(self, token_ids: list[int]) -> torch.Tensor:
        """HF forward over the whole sequence; returns [seq_len, vocab] logits."""
        ids = torch.tensor([token_ids], dtype=torch.long)
        return self.model(input_ids=ids).logits[0]

    def run(self, req: Request, on_token: Callable[[int], None] | None = None) -> Request:
        """Greedy decode one request to completion, recomputing everything each step."""
        req.state = RequestState.RUNNING
        while len(req.output_token_ids) < req.max_new_tokens:
            if req.seq_len >= MAX_CONTEXT:
                break
            logits = self.forward_logits(req.prompt_token_ids + req.output_token_ids)
            next_id = int(torch.argmax(logits[-1]).item())
            req.output_token_ids.append(next_id)
            if req.first_token_time is None:
                req.first_token_time = time.perf_counter()
            self.metrics.record_step(occupied=1)
            if on_token:
                on_token(next_id)
            if next_id == EOS_TOKEN_ID and not req.ignore_eos:  # EOS kept in output, as HF does
                break
        req.finish_time = time.perf_counter()
        req.state = RequestState.FINISHED
        self.metrics.record_request(req)
        return req

    def generate_greedy(self, prompt_token_ids: list[int], max_new_tokens: int) -> list[int]:
        req = Request(request_id="local", prompt_token_ids=list(prompt_token_ids),
                      max_new_tokens=max_new_tokens)
        return self.run(req).output_token_ids

    # ------------------------------------------------------------------ M1 (own forward)
    def _load_weights(self) -> None:
        sd = self.model.state_dict()
        g = lambda k: sd[k].detach().contiguous()  # noqa: E731
        self.wte = g("transformer.wte.weight")
        self.wpe = g("transformer.wpe.weight")
        self.ln_f = (g("transformer.ln_f.weight"), g("transformer.ln_f.bias"))
        self.layers = []
        for i in range(N_LAYERS):
            p = f"transformer.h.{i}."
            self.layers.append({n: g(p + n) for n in (
                "ln_1.weight", "ln_1.bias", "attn.c_attn.weight", "attn.c_attn.bias",
                "attn.c_proj.weight", "attn.c_proj.bias", "ln_2.weight", "ln_2.bias",
                "mlp.c_fc.weight", "mlp.c_fc.bias", "mlp.c_proj.weight", "mlp.c_proj.bias")})

    @torch.inference_mode()
    def _forward_single(self, ids: list[int], start: int, cache: ContiguousKVCache) -> torch.Tensor:
        """Forward for ONE sequence. Writes K/V for these tokens into the cache and returns
        the logits of the LAST token, shape [vocab].

        Prefill: start == 0, len(ids) == prompt length (causal mask over the prompt).
        Decode:  len(ids) == 1, start == position of that token (= seq_len - 1).
        Position ids are explicit: the model only sees one token in decode, but that token
        sits at position `start`, and GPT-2 has learned absolute position embeddings.
        """
        t = len(ids)
        tok = torch.tensor([ids], dtype=torch.long)
        pos = torch.arange(start, start + t, dtype=torch.long).unsqueeze(0)
        x = self.wte[tok] + self.wpe[pos]                       # [1, T, 768]
        for li, w in enumerate(self.layers):
            h = F.layer_norm(x, (HIDDEN,), w["ln_1.weight"], w["ln_1.bias"], 1e-5)
            qkv = _linear(h, w["attn.c_attn.weight"], w["attn.c_attn.bias"])
            q, k, v = qkv.split(HIDDEN, dim=-1)
            q, k, v = (a.reshape(1, t, N_HEADS, HEAD_DIM).transpose(1, 2) for a in (q, k, v))
            cache.write(li, start, k, v)
            k_all, v_all = cache.read(li, start + t)            # [1, H, start+T, D]
            # Prefill needs the causal mask; a single decode token may see everything.
            a = F.scaled_dot_product_attention(q, k_all, v_all, is_causal=(t > 1))
            a = a.transpose(1, 2).reshape(1, t, HIDDEN)
            x = x + _linear(a, w["attn.c_proj.weight"], w["attn.c_proj.bias"])
            h = F.layer_norm(x, (HIDDEN,), w["ln_2.weight"], w["ln_2.bias"], 1e-5)
            h = F.gelu(_linear(h, w["mlp.c_fc.weight"], w["mlp.c_fc.bias"]), approximate="tanh")
            x = x + _linear(h, w["mlp.c_proj.weight"], w["mlp.c_proj.bias"])
        x = F.layer_norm(x[:, -1], (HIDDEN,), self.ln_f[0], self.ln_f[1], 1e-5)
        return (x @ self.wte.T)[0]

    def generate_cached(self, prompt_token_ids: list[int], max_new_tokens: int,
                        ignore_eos: bool = False) -> list[int]:
        """M1: single sequence with our own contiguous KV cache."""
        cache = ContiguousKVCache()
        out: list[int] = []
        logits = self._forward_single(prompt_token_ids, 0, cache)          # prefill
        while True:
            nxt = int(torch.argmax(logits).item())
            out.append(nxt)
            seq_len = len(prompt_token_ids) + len(out)
            if len(out) >= max_new_tokens or seq_len >= MAX_CONTEXT:
                break
            if nxt == EOS_TOKEN_ID and not ignore_eos:
                break
            # The token just produced sits at position seq_len - 1 (P + N - 1 on decode step N).
            logits = self._forward_single([nxt], seq_len - 1, cache)
        return out
