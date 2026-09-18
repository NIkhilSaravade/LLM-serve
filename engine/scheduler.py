"""The scheduler: decides, every iteration, who runs.

M2: static batching only. Admission happens ONLY when the previous batch has completely
drained; finished rows leave the compute but their slots stay empty until the whole batch
is done. That idle capacity is what slot utilisation measures.
"""
from __future__ import annotations

import time
import uuid

from engine.block_manager import SlotManager
from engine.cache import SlotPool
from engine.config import EngineConfig
from engine.metrics import EngineMetrics
from engine.model_runner import EOS_TOKEN_ID, MAX_CONTEXT, ModelRunner
from engine.request import Request, RequestState


class Scheduler:
    def __init__(self, cfg: EngineConfig, runner: ModelRunner, pool, manager,
                 metrics: EngineMetrics | None = None) -> None:
        self.cfg, self.runner, self.pool, self.manager = cfg, runner, pool, manager
        self.metrics = metrics or EngineMetrics(max_slots=cfg.max_batch)
        self.waiting: list[Request] = []
        self.running: list[Request] = []
        self._admit_counter = 0

    # ------------------------------------------------------------------ intake
    def submit(self, req: Request) -> None:
        # Position 1023 is the last usable position, so cap the output accordingly.
        req.max_new_tokens = min(req.max_new_tokens, MAX_CONTEXT - len(req.prompt_token_ids))
        req.state = RequestState.WAITING
        self.waiting.append(req)

    def has_work(self) -> bool:
        return bool(self.waiting or self.running)

    # ------------------------------------------------------------------ the loop body
    def step(self) -> None:
        self._retire()
        self._admit()
        self._decode()

    def _retire(self) -> None:
        keep = []
        for req in self.running:
            if req.finished:
                req.state = RequestState.FINISHED
                self.manager.free(req)
                self.metrics.record_request(req)
            else:
                keep.append(req)
        self.running = keep

    def _admit(self) -> None:
        # Static batching: nothing new joins until the batch has fully drained.
        if self.running:
            return
        batch: list[Request] = []
        while (self.waiting and len(batch) < self.cfg.max_batch
               and self.manager.can_allocate(self.waiting[0])):
            req = self.waiting.pop(0)
            self.manager.allocate(req)
            req.admit_seq = self._admit_counter
            self._admit_counter += 1
            batch.append(req)
        if not batch:
            return
        t0 = time.perf_counter()
        # One padded prefill for the whole batch.
        toks = [r.prompt_token_ids + r.output_token_ids for r in batch]
        nxt = self.runner.step_tokens(toks, [0] * len(batch), self.pool,
                                      [r.block_table for r in batch])
        self.metrics.prefills += len(batch)
        self.metrics.prefill_seconds += time.perf_counter() - t0
        for req, tok in zip(batch, nxt):
            req.state = RequestState.RUNNING
            self._emit(req, tok)
        self.running = batch

    def _decode(self) -> None:
        batch = [r for r in self.running if not r.finished]
        if not batch:
            return
        t0 = time.perf_counter()
        # The token fed in is the last one produced; it sits at position seq_len - 1.
        nxt = self.runner.step_tokens([[r.output_token_ids[-1]] for r in batch],
                                      [r.seq_len - 1 for r in batch], self.pool,
                                      [r.block_table for r in batch])
        self.metrics.decode_seconds += time.perf_counter() - t0
        st = self.manager.stats()
        live, cap = st["live_tokens"], st["capacity_tokens"]
        self.metrics.record_step(
            occupied=len(batch), queue_depth=len(self.waiting),
            kv_used=st["used"] / st["total"], kv_eff=(live / cap if cap else 0.0),
            pad_frac=self.runner.last_pad_frac)
        for req, tok in zip(batch, nxt):
            self._emit(req, tok)

    def _emit(self, req: Request, tok: int) -> None:
        now = time.perf_counter()
        req.output_token_ids.append(tok)
        if req.first_token_time is None:
            req.first_token_time = now
        if len(req.output_token_ids) >= req.max_new_tokens:
            req.finish_reason = "length"
        elif tok == EOS_TOKEN_ID and not req.ignore_eos:
            req.finish_reason = "stop"
        if req.finished:
            req.finish_time = now
        if req.sink:
            req.sink(tok, req.finished)


class Engine:
    """Synchronous facade used by tests and offline benchmarks."""

    def __init__(self, cfg: EngineConfig, runner: ModelRunner | None = None) -> None:
        self.cfg = cfg
        self.runner = runner or ModelRunner(cfg.num_threads)
        n_slots = cfg.max_batch
        self.pool = SlotPool(n_slots)
        self.manager = SlotManager(n_slots)
        self.sched = Scheduler(cfg, self.runner, self.pool, self.manager)

    def generate_batch(self, prompts: list[list[int]], max_new: list[int]) -> list[list[int]]:
        reqs = [Request(uuid.uuid4().hex, list(p), n) for p, n in zip(prompts, max_new)]
        for r in reqs:
            self.sched.submit(r)
        while self.sched.has_work():
            self.sched.step()
        return [r.output_token_ids for r in reqs]

    def generate_greedy(self, prompt: list[int], max_new_tokens: int) -> list[int]:
        return self.generate_batch([prompt], [max_new_tokens])[0]
