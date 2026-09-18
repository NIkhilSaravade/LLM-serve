"""Model loading and the M0 generation loop.

M0 is deliberately the dumbest thing possible: every step re-runs the forward pass
over the ENTIRE sequence so far. No KV cache. Do not optimise; this is the floor
every later milestone is measured against.
"""
from __future__ import annotations

import os
import time

import torch
from transformers import GPT2LMHeadModel, GPT2TokenizerFast

from engine.metrics import EngineMetrics
from engine.request import Request, RequestState

EOS_TOKEN_ID = 50256
MAX_CONTEXT = 1024
# Pinned explicitly: leaving torch's default makes numbers machine-dependent
# (docs/04-benchmark-methodology.md). The same value must be used for every variant.
DEFAULT_NUM_THREADS = int(os.environ.get("LLM_SERVE_THREADS", "4"))


class ModelRunner:
    def __init__(self, num_threads: int = DEFAULT_NUM_THREADS) -> None:
        torch.set_num_threads(num_threads)
        self.num_threads = num_threads
        # transformers supplies weights and tokenizer ONLY. The loop below is ours.
        self.tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")
        self.model = GPT2LMHeadModel.from_pretrained("gpt2", dtype=torch.float32)
        self.model.eval()
        self.metrics = EngineMetrics(max_slots=1)

    @torch.inference_mode()
    def forward_logits(self, token_ids: list[int]) -> torch.Tensor:
        """Full forward pass over the whole sequence; returns [seq_len, vocab] logits."""
        ids = torch.tensor([token_ids], dtype=torch.long)
        return self.model(input_ids=ids).logits[0]

    def run(self, req: Request) -> Request:
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
            if next_id == EOS_TOKEN_ID:  # EOS is kept in the output, as HF does
                break
        req.finish_time = time.perf_counter()
        req.state = RequestState.FINISHED
        self.metrics.record_request(req)
        return req

    def generate_greedy(self, prompt_token_ids: list[int], max_new_tokens: int) -> list[int]:
        req = Request(request_id="local", prompt_token_ids=list(prompt_token_ids),
                      max_new_tokens=max_new_tokens)
        return self.run(req).output_token_ids
