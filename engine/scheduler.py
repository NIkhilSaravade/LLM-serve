"""The scheduler: decides, every iteration, who runs.

Static batching (M2): admission happens ONLY when the previous batch has completely
drained; finished rows leave the compute but their slots stay empty until the whole batch
is done. That idle capacity is what slot utilisation measures.

Continuous batching (M3): the same loop, but admission happens EVERY iteration, so a slot
freed this step is refilled next step and a new request never waits for a batch to drain.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid

from engine.block_manager import BlockManager, SlotManager
from engine.cache import PagedPool, SlotPool
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
        self._retire()   # 1. finished requests leave and free their memory
        self._admit()    # 2. waiting requests move in
        self._decode()   # 3. one decode step for everyone running

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

    def _pop_admissible(self, limit: int) -> list[Request]:
        """FCFS: stop at the first request that does not fit, so big requests are not starved."""
        # Starvation guard: requests that were preempted before go first, worst-treated first.
        self.waiting.sort(key=lambda r: (-r.preempt_count, r.arrival_time))
        batch: list[Request] = []
        # Headroom: every running or just-admitted request may need a fresh block next step.
        # Admitting into a completely full pool would only force an immediate preemption.
        while (self.waiting and len(batch) < limit
               and self.manager.can_allocate(self.waiting[0],
                                             headroom=len(self.running) + len(batch))):
            req = self.waiting.pop(0)
            self.manager.allocate(req)
            req.admit_seq = self._admit_counter
            self._admit_counter += 1
            batch.append(req)
        return batch

    def _admit(self) -> None:
        if self.cfg.batching == "static":
            if self.running:      # nothing joins until the batch has fully drained
                return
            batch = self._pop_admissible(self.cfg.max_batch)
            if batch:
                self._prefill(batch)   # one padded prefill for the whole batch
        else:
            # Continuous: every iteration. Prefill runs as its own forward pass per request
            # and the request joins the decode batch straight after.
            # LIMITATION: a long prefill blocks the decode loop for every running request.
            # Production systems chunk the prefill and interleave it with decode steps.
            room = self.cfg.max_batch - len(self.running)
            for req in self._pop_admissible(max(room, 0)):
                self._prefill([req])

    def _prefill(self, batch: list[Request]) -> None:
        t0 = time.perf_counter()
        # Prompt plus any tokens already generated (non-empty only after a preemption).
        toks = [r.prompt_token_ids + r.output_token_ids for r in batch]
        nxt = self.runner.step_tokens(toks, [0] * len(batch), self.pool,
                                      [r.block_table for r in batch])
        self.metrics.prefills += len(batch)
        self.metrics.prefill_seconds += time.perf_counter() - t0
        for req, tok in zip(batch, nxt):
            req.state = RequestState.RUNNING
            self._emit(req, tok)
        self.running.extend(batch)

    def _decode(self) -> None:
        batch = [r for r in self.running if not r.finished]
        if not batch:
            return
        batch = self._ensure_capacity(batch)
        if not batch:
            return
        self.metrics.peak_batch = max(self.metrics.peak_batch, len(batch))
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

    # ------------------------------------------------------------------ preemption (M5)
    def _ensure_capacity(self, batch: list[Request]) -> list[Request]:
        """Give every row the block its next token needs; preempt when the pool is full.

        Older requests are served first. When a block cannot be found, evict a victim:
        the most recently admitted request among those preempted the fewest times, so the
        least work is thrown away and nobody is evicted forever.
        """
        active = sorted(batch, key=lambda r: r.admit_seq)
        i = 0
        while i < len(active):
            req = active[i]
            if self.manager.append_slot(req):
                i += 1
                continue
            if not self.cfg.preemption:
                raise RuntimeError("out of KV blocks and preemption is disabled")
            victim = min(active, key=lambda r: (r.preempt_count, -r.admit_seq))
            vi = active.index(victim)
            active.pop(vi)
            if vi < i:
                i -= 1
            self._preempt(victim)
            # If the victim was `req` itself, active[i] is now the next request; otherwise we
            # retry `req` with the memory just freed.
        return active

    def _preempt(self, req: Request) -> None:
        # Preempt-and-recompute: throw the KV away and re-prefill prompt + generated tokens
        # on readmission. LIMITATION: recomputation wastes the work already done; swapping the
        # blocks to host RAM would avoid that at the cost of copy traffic and more code.
        self.manager.free(req)
        self.running.remove(req)
        req.state = RequestState.WAITING
        req.preempt_count += 1
        self.metrics.preemptions += 1
        self.waiting.append(req)

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


class NaiveScheduler:
    """M0: one request at a time, full recompute every token, no cache. Same interface."""

    def __init__(self, cfg: EngineConfig, runner: ModelRunner) -> None:
        self.cfg, self.runner = cfg, runner
        self.metrics = EngineMetrics(max_slots=1)
        self.waiting: list[Request] = []
        self.running: list[Request] = []

    def submit(self, req: Request) -> None:
        req.max_new_tokens = min(req.max_new_tokens, MAX_CONTEXT - len(req.prompt_token_ids))
        self.waiting.append(req)

    def has_work(self) -> bool:
        return bool(self.waiting)

    def step(self) -> None:
        if not self.waiting:
            return
        req = self.waiting.pop(0)
        self.running = [req]

        def on_token(tok: int) -> None:
            if req.sink:
                done = (len(req.output_token_ids) >= req.max_new_tokens
                        or (tok == EOS_TOKEN_ID and not req.ignore_eos)
                        or req.seq_len >= MAX_CONTEXT)
                req.sink(tok, done)

        self.runner.run(req, on_token)
        req.finish_reason = req.finish_reason or "length"
        self.running = []


class Engine:
    """Synchronous facade used by tests and offline benchmarks."""

    def __init__(self, cfg: EngineConfig, runner: ModelRunner | None = None) -> None:
        self.cfg = cfg
        self.runner = runner or ModelRunner(cfg.num_threads)
        if cfg.backend == "naive":
            self.sched: Scheduler | NaiveScheduler = NaiveScheduler(cfg, self.runner)
            return
        budget = cfg.kv_budget_mib * 1024 * 1024
        if cfg.backend == "paged":
            n_blocks = BlockManager.blocks_for_budget(budget, cfg.block_size)
            self.pool = PagedPool(n_blocks, cfg.block_size)
            self.manager = BlockManager(n_blocks, cfg.block_size,
                                        reserve_max_new=not cfg.preemption)
        else:
            # LIMITATION: contiguous slots each reserve the full 1024-token context up front.
            n_slots = min(cfg.max_batch, SlotManager.slots_for_budget(budget))
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

    def run_schedule(self, specs: list[tuple[list[int], int, int]]) -> list[list[int]]:
        """Requests arrive at given scheduler iterations: (prompt, max_new, arrival_step).

        Used to prove batch independence when neighbours join and leave mid-generation.
        """
        reqs = [Request(uuid.uuid4().hex, list(p), n) for p, n, _ in specs]
        it = 0
        while True:
            for r, (_, _, at) in zip(reqs, specs):
                if at == it:
                    self.sched.submit(r)
            if it > max(a for _, _, a in specs) and not self.sched.has_work():
                break
            self.sched.step()
            it += 1
        return [r.output_token_ids for r in reqs]


class EngineLoop:
    """Runs the scheduler on its own thread. The scheduler is only ever touched from that
    thread; other threads hand requests over through a thread-safe inbox."""

    def __init__(self, engine: Engine) -> None:
        self.engine, self.sched = engine, engine.sched
        self.inbox: queue.Queue[Request] = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="engine-loop", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)

    def queue_depth(self) -> int:
        return self.inbox.qsize() + len(self.sched.waiting)

    def submit(self, req: Request) -> bool:
        """Front-door admission control: refuse work we cannot serve rather than let the queue
        (and every request's latency) grow without bound. Returns False if rejected."""
        cap = self.engine.cfg.max_queue
        if cap is not None and self.queue_depth() >= cap:
            self.sched.metrics.rejected += 1
            return False
        self.inbox.put(req)
        self._wake.set()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            while True:
                try:
                    self.sched.submit(self.inbox.get_nowait())
                except queue.Empty:
                    break
            if self.sched.has_work():
                self.sched.step()
            else:
                self._wake.wait(0.05)
                self._wake.clear()
