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
