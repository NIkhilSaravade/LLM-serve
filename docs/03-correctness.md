# 03 — Correctness discipline

This is the most important document in the repo. Read it before writing engine
code.

## The problem

You are rewriting the generation loop of a language model. There are dozens of
places to make a small mistake: an off-by-one in position IDs, a mask that
allows one token too many, a KV block written at the wrong offset, a batch row
that picks up another row's cache.

Every one of those mistakes produces **fluent, grammatical, plausible text**.

That is what makes this project dangerous. In normal backend work a bug throws
an exception or returns the wrong number, and you notice. Here the bug returns a
nice paragraph. You will read it, think "looks fine", and keep building on top of
broken foundations for two weeks.

So correctness cannot be judged by looking. It has to be mechanical.

## The rule

> **Greedy decoding must produce token IDs that are byte-identical to the
> HuggingFace reference, for every fixture, at every milestone.**

Not "similar". Not "close". Identical. Same integers, same order, same length.

If the golden test fails, the milestone is not done. Speed is irrelevant until
it passes.

## Why greedy

Greedy decoding always picks the highest-probability token. It is fully
deterministic. Two correct implementations must produce exactly the same output.

Sampling with a temperature is not deterministic unless you control the random
seed *and* the exact order of random draws, which changes when you batch things
differently. So sampling is useless as a correctness signal.

Build and test everything with greedy. Add temperature sampling later, if at
all, and never use it in a correctness test.

## Building the fixtures

`scripts/make_fixtures.py` does this. Run it once, commit the output.

1. Load GPT-2 small through HuggingFace `transformers`.
2. For each prompt in the fixture list, generate N tokens with greedy decoding
   using the reference implementation.
3. Save prompt, prompt token IDs, and the full list of output token IDs to
   `tests/fixtures/*.json`.

**This is the only place `model.generate()` is allowed in the entire repo.**
Put a comment saying so, right above the call.

Commit the fixtures to git. They are the contract. If they ever change, that is
a deliberate act that shows up in a diff.

## What the fixtures must cover

A single happy-path prompt is not enough. The fixture set must include cases that
break the specific things you are building.

| Fixture | Why it exists |
|---|---|
| Short prompt (5 tokens), 20 output tokens | Basic sanity. |
| Long prompt (400 tokens), 20 output tokens | Catches prefill and position bugs. |
| Short prompt, long output (300 tokens) | Catches cache-growth bugs. |
| Prompt that is an exact multiple of block size | Catches the "allocate one block too few" bug in M4. |
| Prompt that is one token over a block boundary | Same, from the other side. |
| Output that crosses a block boundary mid-generation | Catches `append_slot` bugs. |
| Two prompts of very different lengths, run together | Catches per-row position and mask bugs in M3. |
| Same prompt submitted twice in one batch | Output must be identical for both rows. |
| Batch of 8 mixed lengths, all compared at once | The real M3 test. |

The last three only become meaningful at M3, but write them at M1 so they are
ready and already failing for the right reason.

## The batching invariant

This deserves its own statement because it is the heart of M3.

> **A request's output must not depend on what else was in the batch with it.**

Run a prompt alone. Then run it in a batch of 8 with wildly different neighbours.
Then run it in a batch where its neighbours join and leave halfway through. All
three runs must produce identical token IDs.

If they do not, some state is leaking between rows — usually the mask, the
position IDs, or a cache offset.

Write this as a parametrised test at M3 and never delete it.

## Test layout

```python
# tests/test_golden.py

@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_matches_reference(fixture, engine):
    out = engine.generate_greedy(fixture.prompt_token_ids,
                                 max_new_tokens=fixture.n)
    assert out == fixture.expected_token_ids   # exact list equality

@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_batch_independence(fixture, engine, noisy_neighbours):
    alone = engine.generate_greedy(...)
    batched = engine.generate_batch([fixture] + noisy_neighbours)[0]
    assert alone == batched
```

Compare **token IDs, not decoded strings**. Two different token sequences can
decode to the same-looking text, and a string comparison would let that pass.

## When a test fails

Do not start guessing. Work down this list in order. It is roughly ordered by
how often each cause is the real one.

1. **Print the position IDs for every row of the batch.** Most bugs are here.
2. **Print the attention mask shape and the row sums.** Row `i` should attend to
   exactly `current_length_of_row_i` positions. Not one more, not one fewer.
3. **Find the first differing token index.** If it differs at index 0, the
   problem is in prefill. If it differs later, the problem is in the cache or
   the decode step.
4. **Dump the logits for the first differing step** and compare against the
   reference logits. If the logits differ by a tiny float amount but the argmax
   flipped, that is a numerical-precision tie — note it, but it is rare in fp32
   and it is usually not your excuse.
5. **At M4: dump the block table** and check that the physical blocks actually
   contain what the logical positions claim.

Do not add a tolerance to make a test pass. The moment you allow "close enough",
the test stops protecting you.

## Performance regression guard

Add one more test, from M2 onwards: a small fixed benchmark that fails if
throughput drops more than 20% below the last recorded value in `results/`.

This catches the common accident of fixing a correctness bug by adding an
expensive copy in the hot loop.

---

# As built (2026-09-19)

## The fixtures

`scripts/make_fixtures.py` produced eight single-sequence fixtures (prompt length, output length):
`short_5_out20`, `long_400_out20`, `short_5_out300`, `block_exact_16` (16, 20), `block_exact_32`,
`block_plus1_17`, `block_minus1_15`, `cross_block_gen_10` (10, 40), plus `batches.json` with three
batch cases built from them: `two_different_lengths`, `same_prompt_twice`, `mixed_8`. Every reference
output ran its full length (no early EOS). This covers every row of the table above; the block
boundary cases were created in M0 so they were ready for M4.

## What runs, and what each part is for (102 tests, `make test`)

| File | Covers |
|---|---|
| `test_golden.py` | naive (M0) and own-cache (M1) output equals the reference; static and continuous engines equal the reference for every fixture; the three batch cases through both batchers; neighbours joining and leaving mid-generation (`max_batch` 2, 3, 5 with staggered arrivals); streaming detokeniser holds back partial UTF-8; streamed text equals decoded tokens |
| `test_paged.py` | every fixture at block sizes 4 and 16; batches static and continuous; join and leave with the free list shuffled so a sequence's blocks are not adjacent; allocator unit tests for the block-boundary off-by-one; a bit-exact comparison of K and V, all 12 layers and 70 positions, against a contiguous prefill (debug step 5 of the checklist, automated); blocks follow tokens, not the maximum |
| `test_preemption.py` | eviction is forced (asserted, otherwise the test would be vacuous) and outputs stay exact; the client receives each token exactly once across an eviction; every request finishes under 2x over-commit with no livelock and nobody evicted endlessly; queue cap returns 429; request that can never fit returns 413; cancelled requests free their memory and are not counted as served |
| `test_ops.py` | `/health`, `/ready`, `/version`, request-id echo, Prometheus counters and histograms after a request, warmup not counted; every metric a dashboard panel or alert queries exists in the live `/metrics`; generated dashboard and PrometheusRule are current; the ConfigMap is a valid `EngineConfig` consistent with the pod limits |
| `test_perf_guard.py` | fails if static-batching throughput drops more than 20% below the recorded value (marker `perf`, excluded from `make test` and CI because timing on a shared or drifting machine is too noisy; run it with `make perf` on a quiet machine) |

All comparisons are exact token-id list equality. No test has a tolerance.

## Do the tests catch the bugs they exist for?

The golden tests never failed against the engine during the build: every red result was a wrong test
expectation or a harness problem. A test that has never failed proves little, so bugs were injected
on purpose (2026-09-19) and the relevant tests run:

| Injected bug | Result |
|---|---|
| decode position off by one (`seq_len - 1` becomes `seq_len`) | caught by the single-sequence golden tests |
| mask lets a query see one position too many | caught by the batch-independence tests |
| block allocation one block short at a boundary | caught by the paged allocator tests |
| preemption drops the tokens already generated | **missed at first**: the final output was still exact because greedy decoding regenerates the same tokens, but the client would have received the early tokens twice |

The last one was a real gap: tests compared final outputs, never the stream a client sees.
`test_client_sees_each_token_exactly_once_across_preemption` was added and the same injected bug is now
caught. This was a manual exercise, not an automated mutation-testing suite; the script is not in the
repo. Four bugs is a spot check, not coverage.

## What the tests do not prove

- Correctness is checked against one model on one CPU in fp32. Rows of different batch sizes use
  different matrix-multiply shapes, so tiny float differences are possible; none flipped an argmax in
  102 tests, but that is empirical, not guaranteed. A near-tie would show up as a failing golden test
  and must be investigated, never absorbed by a tolerance.
- The dynamics under real traffic (thousands of requests, long prompts) are covered by the benchmark
  for performance, not by golden tests for output equality.

## As a gate

CI (`.github/workflows/ci.yml`) runs the whole suite except the perf guard on every push. A change
that alters token output cannot merge, which is what makes "image tag = model version" safe in
`docs/07-operations.md`.
