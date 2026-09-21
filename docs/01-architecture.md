# 01 — Architecture

## The shape of the system

```
   HTTP request
        │
        ▼
  ┌───────────┐
  │  api.py   │  FastAPI. Turns a request into a Request object. Returns a stream.
  └─────┬─────┘
        │ push
        ▼
  ┌───────────┐
  │   queue   │  Requests waiting to be admitted.
  └─────┬─────┘
        │ pull
        ▼
  ┌──────────────────────────────────────────────┐
  │              scheduler.py                    │  ← THE CORE
  │  runs a loop. every iteration it decides:    │
  │   - which requests finish and free their KV  │
  │   - which waiting requests get admitted      │
  │   - which requests get preempted (M5)        │
  │   - what the batch for this step looks like  │
  └───────┬──────────────────────────┬───────────┘
          │ asks for/frees blocks    │ hands a batch to
          ▼                          ▼
  ┌────────────────┐         ┌──────────────────┐
  │ block_manager  │◄────────│  model_runner    │  one forward step for the batch
  │   (M4)         │  reads  │  (PyTorch, CPU)  │
  └───────┬────────┘         └────────┬─────────┘
          │ owns                      │ writes new K,V
          ▼                           │
  ┌────────────────┐                  │
  │   cache.py     │◄─────────────────┘
  │ the KV tensors │
  └────────────────┘
```

The scheduler loop is the heartbeat. Everything else reacts to it.

## The request lifecycle

A request moves through states. Keep this state machine explicit in code — it
makes the scheduler far easier to reason about and to log.

```
WAITING ──admit──► RUNNING ──finish──► FINISHED
   ▲                  │
   └───preempt────────┘        (M5 only)
```

- **WAITING** — accepted by the API, sitting in the queue, holds no KV memory.
- **RUNNING** — has KV blocks allocated, is in the batch each step.
- **PREEMPTED** — was running, got kicked out because memory ran out, KV thrown
  away, sent back to the queue. Only exists from M5 onwards.
- **FINISHED** — hit a stop token or the max token limit. KV freed.

## Key data structures

### Request

```python
@dataclass
class Request:
    request_id: str
    prompt_token_ids: list[int]
    output_token_ids: list[int]       # grows by one each decode step
    max_new_tokens: int
    state: RequestState
    arrival_time: float               # for latency metrics
    first_token_time: float | None    # for TTFT
    block_table: list[int]            # M4: which physical blocks are mine
```

`len(prompt_token_ids) + len(output_token_ids)` is the sequence's current
length. This number drives position IDs, mask construction, and how many blocks
it needs. Get it wrong and everything downstream is subtly wrong.

### BlockManager (M4)

```python
class BlockManager:
    block_size: int          # tokens per block, e.g. 16
    num_blocks: int          # total physical blocks that fit in the memory budget
    free_blocks: list[int]   # free list

    def can_allocate(self, req) -> bool
    def allocate(self, req) -> None          # initial blocks for the prompt
    def append_slot(self, req) -> bool       # one more token; may need a new block
    def free(self, req) -> None
```

The block table is the whole trick. A sequence's tokens live in blocks that are
**not next to each other in memory**. `block_table[i]` says where logical block
`i` physically lives.

## Prefill versus decode — read this before M3

These are two different kinds of work and confusing them causes real bugs.

**Prefill** happens once per request. The whole prompt is processed in a single
forward pass, and K and V are computed for every prompt token at once. If the
prompt is 200 tokens, this step does 200 tokens of work. It is **compute
bound** — there is plenty of arithmetic per byte of weights read.

**Decode** happens once per generated token. It processes exactly one new token
per sequence. It is **memory bandwidth bound** — this is the step that batching
rescues.

They have different shapes, so mixing them in one batch is awkward. The design
decision for this project:

- **M3: keep it simple.** Run prefill for each newly admitted request as its own
  forward pass. Then that request joins the decode batch from the next step.
- **Stretch (optional, after M6): chunked prefill.** Break a long prompt into
  pieces and interleave those pieces with decode steps, so a long prompt does
  not stall everyone else. Only attempt this if M0–M6 are complete.

The simple version has a known weakness: a very long prompt blocks the decode
loop while it prefills. **Measure that weakness and report it.** A measured
weakness is worth more than a hidden one.

## The scheduler loop, in words

This is the pseudocode for M3. Do not write it as code yet — understand it first.

```
loop forever:
    # 1. retire
    for each running request that hit a stop token or its token limit:
        mark FINISHED, free its KV, send the final response

    # 2. admit
    while queue is not empty and there is room (slot budget and KV memory):
        pop a request, allocate its KV, run its prefill, mark RUNNING

    # 3. step
    if no running requests:
        sleep briefly, continue
    build a batch from all RUNNING requests
    run ONE decode step for that batch
    append the new token to each request, stream it out

    # 4. record
    update metrics: slot utilisation, tokens produced, timings
```

Step 2 is the difference between static and continuous batching. In static
batching, admission only happens when the previous batch has completely drained.
Here it happens **every iteration**.

## The hard part: per-row positions and masks

Once the batch holds sequences at different lengths, every row of the batch
needs its own treatment.

GPT-2 uses **learned position embeddings**. Position `p` is a lookup into the
`wpe` table. So the model runner must pass a per-row position index: sequence A
might be at position 12 while sequence B is at position 400.

The attention mask likewise differs per row. Sequence A may attend to 12 past
tokens; sequence B to 400. Any padding in the batch must be masked out so it
contributes nothing.

**Why this is dangerous:** if you get positions or masks slightly wrong, the
model still produces fluent, plausible English. It just produces the *wrong*
fluent English. You cannot catch this by reading the output. Only the golden
test catches it. See `docs/03-correctness.md`.

(Note: GPT-2's learned position embeddings make this easier than a modern model
using RoPE. That is one of the reasons GPT-2 was chosen.)

## Memory arithmetic — know these numbers

GPT-2 small: 12 layers, 12 heads, hidden size 768, head dim 64, max context 1024.

KV cache per token:

```
2 (K and V) × 12 layers × 768 dims × 4 bytes (fp32) = 73,728 bytes ≈ 72 KiB
```

So:

- One token of one sequence costs ~72 KiB of cache.
- A full 1024-token sequence costs ~73.7 MB.
- With a block size of 16 tokens, one block is ~1.18 MB.

Now the point of M4 becomes obvious. If you preallocate 1024 tokens for a
request that only produces 100 tokens, you have reserved 73.7 MB and used
7.2 MB. **Ninety percent of that reservation is wasted.** Paging recovers it,
and recovered memory becomes more concurrent sequences, which becomes
throughput.

Set an explicit KV memory budget in config, for example 2 GB. Then
`num_blocks = budget / bytes_per_block`. Making the budget a knob lets you show
throughput as a function of available cache memory, which is a good chart.

## Metrics the engine must emit

Collect these from M0 onwards, even when they are boring. Adding them later
means re-running everything.

| Metric | Meaning |
|---|---|
| TTFT | Time to first token. Arrival → first token streamed. |
| TPOT / ITL | Time per output token, after the first. |
| E2E latency | Arrival → final token. |
| Throughput | Output tokens per second, across all requests. |
| Slot utilisation | Occupied batch slots ÷ max batch slots, averaged over steps. |
| KV utilisation | Blocks in use ÷ total blocks. |
| Queue depth | Requests in WAITING. |
| Preemption count | M5 only. |

Write them to `results/<run-name>.json`. Never compute a published number by
hand.

---

# As built (2026-09-19)

Everything above is the plan. This section records what the code actually does where it differs
or adds detail. The plan is kept unedited so the differences are visible.

## Data structures

**Request** (`engine/request.py`) gained: `ignore_eos` (benchmarks fix the output length exactly),
`finish_reason` (`length`, `stop`, `cancelled`), `admit_seq` (admission order, used to pick eviction
victims), `preempt_count` (starvation guard), `cancelled` (set when the client disconnects) and
`sink` (callback with `(token_id, finished)` invoked from the engine thread for every token).

**States.** There is no separate `PREEMPTED` state. A preempted request goes back to `WAITING`,
keeps its generated tokens, and carries `preempt_count > 0`. `FINISHED` is reached by any finish
reason. The implementation never needed a fourth state, and the counter is what the scheduler uses.

**Memory.** `engine/cache.py` holds three storage layouts behind one interface, `BatchAccess`:

| Class | Layout | Used by |
|---|---|---|
| `ContiguousKVCache` | `[layers, 2, heads, max_len, head_dim]`, one sequence | M1 |
| `SlotPool` | one full 1024-token slot per request | M2 and M3 |
| `PagedPool` | `[num_blocks, heads, block_size, head_dim]` per layer, addressed by block tables | M4 and later |

`engine/block_manager.py` has `SlotManager` and `BlockManager`. Both expose `can_allocate`,
`allocate`, `append_slot`, `free`, `fits_ever` and `stats`, so the scheduler does not know which one
it is talking to.

## One forward function for prefill and decode

`ModelRunner.step_tokens(token_lists, starts, pool, block_tables)` runs both. Row `i` already holds
`starts[i]` tokens and receives `len(token_lists[i])` new ones: prefill is `start=0, n=prompt length`,
decode is `start=seq_len-1, n=1`. New tokens are right-padded to the longest row; pad positions are
never written and never attended to by a real row. Query `t` of row `i` sits at position
`start_i + t` and may attend key `j` iff `j <= start_i + t` and `j < total_i`. Single-row cases keep
the exact M1 kernels (no mask, or `is_causal`) so numerics match the single-sequence path. Only the
last real token of each row goes through the language-model head.

## The scheduler as built (`engine/scheduler.py`)

```
step():
  retire   drop cancelled waiting requests; finish cancelled running ones; free memory of finished
  admit    static:     only when nothing is running, one padded prefill for the whole batch
           continuous: while there is room, prefill each admitted request on its own
  decode   ensure capacity for every row (preempting if needed), then one batched decode step
```

- **Admission is strict FCFS**, except that previously preempted requests go first, most-preempted
  first. It stops at the first request that does not fit, so a large request is never starved by a
  stream of small ones.
- **Two admission rules for paged memory** (`EngineConfig.preemption`):
  worst-case commit (M4: admit only if the worst-case block count of every running request still
  fits, blocks are still allocated lazily) or optimistic (M5: admit if the prompt plus one block of
  headroom per running request fits, and evict when memory runs out).
- **Eviction (M5):** the most recently admitted request among those preempted the fewest times.
  Recompute preemption: free the blocks, keep the generated tokens, re-prefill prompt plus generated
  tokens on readmission, which yields the next token directly.
- **`EngineLoop`** runs the scheduler on its own thread. Only that thread touches scheduler state;
  other threads hand requests over through a thread-safe inbox. It is also the front-door admission
  control: when the queue reaches `max_queue` it refuses the request (HTTP 429).
- **Cancellation:** the streaming handler sets `request.cancelled` when the client goes away; the
  scheduler then drops it (waiting) or finishes and frees it (running). Without this, requests the
  load generator abandoned kept generating and slowed every later run.
- **`NaiveScheduler`** exists only so the M0 baseline can be served over HTTP with the same
  interface: one request at a time, full recompute.

## Position of a decode token (the M1 off-by-one, settled)

Prompt length `P`, decode step `N` (1-indexed): the token fed is output token `N`, which sits at
position `P + N - 1 = seq_len - 1`. It writes its K/V at index `P + N - 1` and attends to `P + N`
keys. Prefill produces output token 1. The block a token needs is allocated just before the step
that feeds it (`append_slot`), so a sequence of exactly `block_size` tokens holds one block and its
next token opens a second.

## HTTP surface (`engine/api.py`)

`POST /generate` (streaming NDJSON or a single JSON body; 400 bad input, 413 request larger than the
whole KV pool, 429 queue full), `GET /health` (liveness, fails if the scheduler thread died),
`GET /ready` (model loaded and warmed), `GET /metrics` (Prometheus), `GET /version`, `GET /stats`
and `POST /stats/reset` (the JSON summary the benchmark harness reads). Run one uvicorn worker per
process: the process owns the model and the KV pool.

## Metrics: two consumers, two mechanisms

The table in the plan above is implemented in `engine/metrics.py` (per decode step, written into
the benchmark JSON) with two additions: `kv_token_efficiency` (live tokens / allocated capacity,
the number that shows what paging saves) and `attn_padding_waste` (the cost of padding). Operators
get a separate set in `engine/observability.py`: request outcomes, TTFT/TPOT/E2E histograms, queue
depth, running batch, KV use, preemptions. The benchmark never reads Prometheus, so its numbers do
not depend on the operations layer. See `docs/07-operations.md`.

## Memory arithmetic, checked against the running server

The plan's numbers hold: 72 KiB of KV per token, 1.18 MB per 16-token block. Measured in a container
with a 1 GiB KV budget: the server process holds 1.95 GiB resident, so the model and runtime cost
about 0.9 GiB and the pool is resident from start-up (it is zero-filled on purpose, so page faults
never land on a request).
