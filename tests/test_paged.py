"""M4: paged KV cache. Same golden contract, plus block-boundary and block-table checks."""
from __future__ import annotations

import random
import uuid

import pytest
from conftest import BATCHES, FIXTURES, make_engine

from engine.block_manager import BlockManager
from engine.request import Request

BLOCK_SIZES = [4, 16]  # 4 crosses many boundaries; 16 is the fixtures' design point
ARRIVALS = [0, 0, 3, 5, 8, 13, 21, 34]


def paged(engine, bs, **kw):
    kw.setdefault("batching", "continuous")
    kw.setdefault("max_batch", 8)
    return make_engine(engine, backend="paged", block_size=bs, kv_budget_mib=256, **kw)


# ---------------------------------------------------------------- allocator unit tests
def _req(prompt_len: int, max_new: int = 10, out: int = 0) -> Request:
    r = Request(uuid.uuid4().hex, [1] * prompt_len, max_new)
    r.output_token_ids = [2] * out
    return r


@pytest.mark.parametrize("prompt_len,blocks", [(1, 1), (15, 1), (16, 1), (17, 2), (32, 2), (33, 3)])
def test_allocate_takes_ceil_blocks(prompt_len, blocks):
    m = BlockManager(num_blocks=16, block_size=16, reserve_max_new=False)
    r = _req(prompt_len)
    m.allocate(r)
    assert len(r.block_table) == blocks


def test_append_slot_grows_exactly_at_block_boundary():
    """A 16-token prompt needs one block; the first generated token (fed at position 16)
    needs a second. The off-by-one that allocates one block too few lives here."""
    m = BlockManager(num_blocks=16, block_size=16, reserve_max_new=False)
    r = _req(16)
    m.allocate(r)
    assert len(r.block_table) == 1
    r.output_token_ids.append(7)            # seq_len 17: the token at position 16 comes next
    assert m.append_slot(r) and len(r.block_table) == 2
    for _ in range(15):                      # positions 17..31 stay inside block 2
        r.output_token_ids.append(7)
        assert m.append_slot(r) and len(r.block_table) == 2
    r.output_token_ids.append(7)            # position 32 opens block 3
    assert m.append_slot(r) and len(r.block_table) == 3


def test_free_returns_every_block_and_append_fails_when_empty():
    m = BlockManager(num_blocks=2, block_size=4, reserve_max_new=False)
    r = _req(8)
    m.allocate(r)
    assert not m.free_blocks
    r.output_token_ids.append(1)
    assert m.append_slot(r) is False
    m.free(r)
    assert len(m.free_blocks) == 2 and r.block_table == []


def test_reserve_mode_bounds_admission_by_worst_case():
    m = BlockManager(num_blocks=10, block_size=16, reserve_max_new=True)
    a, b = _req(16, max_new=100), _req(16, max_new=100)   # each worst case 8 blocks
    assert m.can_allocate(a)
    m.allocate(a)
    assert not m.can_allocate(b)   # 8 + 8 > 10, though only 1 block is physically used


# ---------------------------------------------------------------- golden through paged
@pytest.mark.parametrize("bs", BLOCK_SIZES)
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_paged_single_matches_reference(name, bs, engine):
    fx = FIXTURES[name]
    eng = paged(engine, bs)
    assert eng.generate_greedy(fx["prompt_token_ids"], fx["max_new_tokens"]) == fx["expected_token_ids"]


@pytest.mark.parametrize("mode", ["static", "continuous"])
@pytest.mark.parametrize("batch", sorted(BATCHES))
def test_paged_batch_independence(batch, mode, engine):
    eng = paged(engine, 16, batching=mode)
    fxs = [FIXTURES[n] for n in BATCHES[batch]]
    outs = eng.generate_batch([f["prompt_token_ids"] for f in fxs], [f["max_new_tokens"] for f in fxs])
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"]


@pytest.mark.parametrize("bs", BLOCK_SIZES)
@pytest.mark.parametrize("max_batch", [2, 5])
def test_paged_join_and_leave_with_scattered_blocks(max_batch, bs, engine):
    eng = paged(engine, bs, max_batch=max_batch)
    # Shuffle the free list so a sequence's blocks are genuinely non-adjacent in the pool.
    random.Random(0).shuffle(eng.manager.free_blocks)
    fxs = [FIXTURES[n] for n in BATCHES["mixed_8"]]
    outs = eng.run_schedule([(f["prompt_token_ids"], f["max_new_tokens"], a)
                             for f, a in zip(fxs, ARRIVALS)])
    for fx, out in zip(fxs, outs):
        assert out == fx["expected_token_ids"], fx["name"]


# ---------------------------------------------------------------- inspect the pool itself
def test_block_table_points_at_the_right_kv(engine):
    """Debug step 5 from docs/03: physical blocks must hold what the logical positions claim.
    Prefill the same prompt into a contiguous slot and into scattered paged blocks, then
    compare K and V for every layer and position."""
    import torch
    prompt = FIXTURES["long_400_out20"]["prompt_token_ids"][:70]   # 70 tokens: 5 blocks of 16
    contig = make_engine(engine, backend="contiguous", max_batch=2)
    pg = paged(engine, 16)
    random.Random(1).shuffle(pg.manager.free_blocks)
    for eng in (contig, pg):
        r = Request(uuid.uuid4().hex, list(prompt), 1)
        eng.manager.allocate(r)
        eng.runner.step_tokens([prompt], [0], eng.pool, [r.block_table])
        eng._r = r
    assert len(pg._r.block_table) == 5 and pg._r.block_table != sorted(pg._r.block_table)
    slot = contig._r.block_table[0]
    for layer in range(12):
        for pool_c, pool_p in ((contig.pool.k, pg.pool.k), (contig.pool.v, pg.pool.v)):
            for pos in range(70):
                blk, off = pg._r.block_table[pos // 16], pos % 16
                assert torch.equal(pool_p[layer][blk, :, off], pool_c[layer][slot, :, pos])


def test_memory_tracks_tokens_actually_generated(engine):
    eng = paged(engine, 16)
    r = Request(uuid.uuid4().hex, [5] * 20, 30, ignore_eos=True)
    eng.sched.submit(r)
    while eng.sched.has_work():
        eng.sched.step()
        if r.output_token_ids and not r.finished:
            # Blocks follow tokens, not the max. The newest token has been emitted but not yet
            # fed, so it owns no storage until the next decode step: stored tokens = seq_len - 1.
            assert len(r.block_table) == -(-(r.seq_len - 1) // 16)
    assert len(eng.manager.free_blocks) == eng.manager.num_blocks   # everything returned
