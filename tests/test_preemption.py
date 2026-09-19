"""M5: preempt-and-recompute, starvation guard, admission control. The golden contract still
holds: a request that was evicted and recomputed must produce exactly the reference tokens."""
from __future__ import annotations

import uuid

from conftest import BATCHES, FIXTURES, make_engine

from engine.config import EngineConfig
from engine.request import Request
from engine.scheduler import Engine, EngineLoop

ARRIVALS = [0, 0, 3, 5, 8, 13, 21, 34]


def tight(engine, **kw):
    # block_size 4, 40 MiB -> 142 blocks = 568 tokens. The longest fixture (420 tokens) fits
    # alone, but the eight together need ~1700 tokens, so preemption is forced.
    kw.setdefault("max_batch", 8)
    kw.setdefault("kv_budget_mib", 40)
    return make_engine(engine, backend="paged", block_size=4,
                       preemption=True, batching="continuous", **kw)


def test_preemption_happens_and_outputs_stay_exact(engine):
    eng = tight(engine)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    outs = eng.generate_batch([f["prompt_token_ids"] for f in fxs], [f["max_new_tokens"] for f in fxs])
    assert eng.sched.metrics.preemptions > 0, "test is meaningless unless something was evicted"
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"], fx["name"]
    assert len(eng.manager.free_blocks) == eng.manager.num_blocks   # nothing leaked


def test_preemption_with_arrivals_joining_and_leaving(engine):
    # 30 MiB = 106 blocks of 4: just enough for the longest fixture (105 blocks) alone.
    eng = tight(engine, max_batch=5, kv_budget_mib=30)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    close = [0, 0, 1, 2, 3, 4, 5, 6]   # neighbours still join and leave, but demand overlaps
    outs = eng.run_schedule([(f["prompt_token_ids"], f["max_new_tokens"], a)
                             for f, a in zip(fxs, close)])
    assert eng.sched.metrics.preemptions > 0
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"], fx["name"]


def test_every_request_finishes_under_heavy_overcommit(engine):
    """No request stuck forever, and the starvation guard keeps repeat victims moving."""
    eng = tight(engine)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]] * 2
    reqs = [Request(uuid.uuid4().hex, list(f["prompt_token_ids"]), f["max_new_tokens"]) for f in fxs]
    for r in reqs:
        eng.sched.submit(r)
    steps = 0
    while eng.sched.has_work():
        eng.sched.step()
        steps += 1
        assert steps < 20000, "livelock: requests are not making progress"
    assert all(r.finished for r in reqs)
    assert max(r.preempt_count for r in reqs) < 40   # nobody was evicted endlessly
    for r, f in zip(reqs, fxs):
        assert r.output_token_ids == f["expected_token_ids"]


def test_without_preemption_it_refuses_instead_of_overcommitting(engine):
    """M4 mode (reserve worst case): the same overload is served with zero preemptions."""
    eng = make_engine(engine, backend="paged", block_size=4, kv_budget_mib=40,
                      preemption=False, batching="continuous", max_batch=8)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    outs = eng.generate_batch([f["prompt_token_ids"] for f in fxs], [f["max_new_tokens"] for f in fxs])
    assert eng.sched.metrics.preemptions == 0
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"]


def test_admission_control_rejects_when_queue_is_full(engine):
    eng = Engine(EngineConfig(backend="contiguous", max_batch=2, max_queue=2), engine)
    loop = EngineLoop(eng)            # not started: the inbox simply fills up
    reqs = [Request(uuid.uuid4().hex, [1, 2, 3], 4) for _ in range(4)]
    assert [loop.submit(r) for r in reqs] == [True, True, False, False]
    assert eng.sched.metrics.rejected == 2


def test_api_returns_429_when_overloaded_and_413_when_request_can_never_fit(engine):
    from fastapi.testclient import TestClient
    from engine.api import create_app
    cfg = EngineConfig(backend="paged", block_size=16, kv_budget_mib=2, preemption=True, max_queue=1)
    with TestClient(create_app(cfg)) as c:
        r = c.post("/generate", json={"prompt_token_ids": [5] * 10, "max_new_tokens": 400})
        assert r.status_code == 413    # 2 MiB is ~1 block: 410 tokens can never fit


def test_cancelled_requests_stop_consuming_capacity_and_free_memory(engine):
    """A client that disconnects must not keep a slot, KV blocks or decode compute busy."""
    eng = make_engine(engine, backend="paged", block_size=16, kv_budget_mib=64,
                      batching="continuous", max_batch=4)
    keep = Request(uuid.uuid4().hex, [5] * 20, 40, ignore_eos=True)
    gone = Request(uuid.uuid4().hex, [6] * 20, 400, ignore_eos=True)
    queued = Request(uuid.uuid4().hex, [7] * 20, 400, ignore_eos=True)
    for r in (keep, gone, queued):
        eng.sched.submit(r)
    for _ in range(5):
        eng.sched.step()
    assert len(gone.block_table) > 0
    gone.cancelled = queued.cancelled = True
    while eng.sched.has_work():
        eng.sched.step()
    assert gone.finish_reason == "cancelled" and len(gone.output_token_ids) < 20
    assert queued.output_token_ids == [] or queued.finish_reason == "cancelled"
    assert len(keep.output_token_ids) == 40                      # the survivor is unaffected
    assert len(eng.manager.free_blocks) == eng.manager.num_blocks  # everything returned
    assert eng.sched.metrics.summary(1.0)["requests"] == 1        # abandoned work not counted


def test_client_sees_each_token_exactly_once_across_preemption(engine):
    """The stream a client receives must equal the final output: no duplicated or dropped tokens
    when a request is evicted and recomputed. Comparing only final outputs misses this, because
    greedy decoding regenerates the same tokens after a recompute."""
    eng = tight(engine)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    streams = [[] for _ in fxs]
    reqs = []
    for f, stream in zip(fxs, streams):
        r = Request(uuid.uuid4().hex, list(f["prompt_token_ids"]), f["max_new_tokens"])
        r.sink = lambda tok, fin, s=stream: s.append(tok)
        reqs.append(r)
        eng.sched.submit(r)
    while eng.sched.has_work():
        eng.sched.step()
    assert eng.sched.metrics.preemptions > 0
    for f, stream in zip(fxs, streams):
        assert stream == f["expected_token_ids"], f["name"]
