# 05 — Glossary, explained from first principles

No skipped steps. If a term in the other docs is unclear, it is explained here.

---

## Why generating text is slow — the core fact

A language model generates one token at a time. Each new token depends on all the
tokens before it, so they cannot be produced in parallel.

To produce **one** token, the processor must read **all** the model weights out
of memory and multiply them against the current state.

GPT-2 small has 124 million parameters. At 4 bytes each that is about 500 MB of
weights read, to produce one token of maybe a few thousand arithmetic operations
per parameter used. The ratio of useful arithmetic to bytes moved is terrible.

The term for this ratio is **arithmetic intensity**. When it is low, the
processor sits idle waiting for memory. The work is **memory bandwidth bound**.

Now the key observation:

> If you process 16 sequences in the same step, you read the weights **once** and
> use them 16 times.

The memory cost barely changes. The token output is 16 times higher. This is why
batching is the central lever in LLM serving, and why almost everything in this
project is about keeping the batch full.

This scaling continues until one of two things stops it:

- you run out of **KV cache memory** to hold more sequences, or
- you run out of **compute** — the arithmetic units saturate.

On a GPU the memory limit usually comes first, so batching gains are huge. On a
CPU, which has far fewer arithmetic units, the compute limit comes sooner. So
this project's gains are real but smaller. That is stated openly in the results.

---

## KV cache

Inside attention, every token is turned into three vectors: a Query, a Key and a
Value.

When generating token 50, the model's attention compares token 50's Query against
the Keys of tokens 1 through 49, and uses the result to blend their Values.

Here is the important part: the Keys and Values of tokens 1 through 49 **do not
change**. They were computed when those tokens were processed and they are fixed
forever.

So recomputing them every step is pure waste. Store them instead. That store is
the **KV cache**.

With a cache, each decode step only computes K and V for the single new token,
and reads everything else. This turns the cost of a step from "proportional to
sequence length" into "roughly constant".

**Cost:** memory. For GPT-2 small,

```
2 (K and V) × 12 layers × 768 hidden dims × 4 bytes = 73,728 bytes ≈ 72 KiB per token
```

So a 1024-token sequence needs about 73.7 MB of cache. Multiply by the number of
concurrent sequences and cache memory becomes the thing that limits your batch
size — which is exactly why paging it properly matters so much.

---

## Prefill and decode

Two different phases, with different performance characteristics.

**Prefill** processes the whole prompt in one forward pass. A 200-token prompt
does 200 tokens of work at once, filling the cache for all of them. There is
plenty of arithmetic per byte of weights read, so prefill is **compute bound**.

**Decode** processes exactly one new token per sequence per step. Very little
arithmetic per byte of weights read, so decode is **memory bandwidth bound**.

Batching helps decode enormously and helps prefill much less, because prefill was
already using the hardware well.

Because their shapes differ, mixing prefill and decode in a single batch is
fiddly. This project keeps them separate for simplicity, and measures the
downside (a long prefill stalls the decode loop).

---

## Static batching, and why it wastes slots

The naive way to batch: collect N requests, run them together, wait for **all** of
them to finish, return them, start the next batch.

The problem is that requests do not finish together. Suppose a batch of 4:

```
step:      1    100   200   ...   800
req A:     ████  done
req B:     ████████████ done
req C:     ████ done
req D:     ██████████████████████████ done
```

After step 200, three of the four slots are empty. But the batch cannot end and
new requests cannot join, so those slots do nothing for the remaining 600 steps.

**Slot utilisation** measures this: occupied slots divided by total slots,
averaged over every step. In a workload with varied output lengths, static
batching often lands well below 50%. Half the hardware is producing nothing.

---

## Continuous batching (iteration-level scheduling)

The fix. Instead of scheduling once per batch, schedule **once per step**.

At every decode step:

1. Any sequence that finished is removed and its cache freed.
2. Any waiting request is admitted into the freed space.
3. One step is run for whatever is currently in the batch.

The same picture now looks like:

```
step:      1    100   200   ...   800
req A:     ████ done
req E:          ████████ done
req G:                  ████████████ done
req B:     ████████████ done
req F:                 ██████ done
...
```

The slots stay full. Utilisation approaches 100%, and throughput follows.

There is a second benefit that matters to users: a new request no longer waits
for the current batch to drain before it starts. Time-to-first-token drops
sharply, not just throughput.

This idea comes from the Orca paper (2022) and is what vLLM, TGI and every modern
serving stack do.

---

## Paged KV cache

The memory problem. When a request arrives you do not know how many tokens it
will generate. The safe thing is to reserve the maximum. If the limit is 1024
tokens, you reserve 73.7 MB.

If it then generates 100 tokens, it uses 7.2 MB. **Ninety percent of the
reservation is wasted** and cannot be used by anyone else. Less usable memory
means fewer concurrent sequences means lower throughput.

This is exactly the fragmentation problem operating systems solved decades ago,
and the solution transfers directly.

Cut the cache into fixed-size **blocks** — say 16 tokens each. Give each sequence
a **block table**, a list saying which physical block holds each of its logical
blocks:

```
sequence X, 40 tokens, block_size 16:
  logical block 0 (tokens  0–15) → physical block 7
  logical block 1 (tokens 16–31) → physical block 2
  logical block 2 (tokens 32–39) → physical block 9   (partly empty, that's fine)
```

A sequence takes a new block only when it actually needs one. The blocks do not
have to sit next to each other. Waste is now bounded by at most one partly-filled
block per sequence, instead of a huge unused reservation.

**The cost:** attention now has to read K and V from scattered locations. Real
systems handle this with a custom fused GPU kernel (this is PagedAttention, from
the vLLM paper). This project cannot, so it gathers blocks into a temporary
contiguous buffer first. Slower, but correct — and the limitation is documented
rather than hidden.

**Bonus:** the block table makes prefix sharing natural. If two requests start
with the same system prompt, they can point at the *same* physical blocks. That
is prefix caching, listed as a stretch goal.

---

## Preemption

Once memory is packed tightly, a running sequence will eventually ask for a block
when none are free. Something must give.

- **Preempt and recompute** — evict a sequence, discard its cache, put it back in
  the queue, redo its prefill later. Simple; wastes the recomputation.
- **Preempt and swap** — copy its blocks to ordinary RAM and bring them back
  later. More code; avoids recompute.

The *policy* — which sequence to evict — matters more than the mechanism.
Evicting the most recently admitted request is a reasonable default, because it
has done the least work, so the least is thrown away.

**Starvation** is the risk: a request that keeps getting evicted may never
finish. Track how many times each request has been preempted and give repeat
victims priority.

---

## Admission control

Deciding not to accept work you cannot serve.

Without it, an overloaded server accepts everything, the queue grows without
bound, and every request gets a terrible latency. With it, the server serves what
it can at good latency and rejects or delays the rest.

This is ordinary backend engineering, and it is why a fintech background is
relevant here.

---

## Latency terms

- **TTFT — time to first token.** From arrival to the first token reaching the
  client. This is what the user experiences as "is it stuck?". Continuous
  batching improves it dramatically, because requests no longer wait for a batch
  to drain.
- **TPOT — time per output token.** The average gap between tokens after the
  first. This is what the user experiences as reading speed. Larger batches
  usually make this slightly *worse* while making throughput much better — a real
  trade-off, worth charting.
- **Goodput at SLO.** Requests per second completed while meeting a stated
  latency target. The honest headline number, because raw throughput can always
  be inflated by letting latency explode.

---

## Why greedy decoding is used for all tests

Greedy decoding always picks the single highest-probability token. It is fully
deterministic, so two correct implementations must produce byte-identical output.

Sampling with a temperature is random. Even with a fixed seed, the order of
random draws changes when batching changes, so outputs diverge legitimately. That
makes sampling useless as a correctness signal.

Hence: greedy everywhere in tests. Sampling, if added at all, is a feature, never
a test.

---

## Terms added while building and operating it

**Open-loop load.** Requests are sent at scheduled times whether or not earlier ones have finished.
A slow server then builds a queue, as in production. The opposite, closed-loop (send the next request
when the previous returns), quietly slows the generator down when the server is slow and hides
overload. The benchmark is open-loop.

**Poisson arrivals.** Gaps between requests are exponentially distributed, giving the random mix of
busy and idle moments real traffic has. A fixed gap or a single burst is easier on the server than
either.

**Goodput.** Requests per second that finish *and* meet the latency target. Requests that were
rejected or finished too slowly do not count, so it cannot be inflated by letting latency explode.

**Slot utilisation (measured under saturation).** Only meaningful when work is always waiting: at low
load an empty slot is not waste, there was simply nothing to run. It was measured separately with a
saturating burst.

**KV token efficiency.** Live tokens divided by allocated token capacity. About 0.12 for contiguous
slots (each reserves 1024 tokens) and about 0.95 for paged blocks: the number that shows what paging
saves.

**Padding waste.** Attention width spent on padding when rows in a batch have different lengths. The
price of a padded (not ragged) batch; 0.39 under continuous batching in the burst measurement.

**Worst-case commit.** Admit a request only if the maximum memory every running request could ever
need still fits. Never runs out of memory, but limits concurrency to the worst case. Replaced in M5
by optimistic admission plus preemption.

**Headroom.** Free blocks kept back at admission (one per running request) so that admitting a new
request does not force an immediate eviction.

**Cancellation.** When a client disconnects the server stops the request and frees its memory.
Without it, abandoned requests keep consuming compute and KV blocks.

**Backpressure / load shedding.** Refusing work you cannot serve (HTTP 429 with `Retry-After`) rather
than queueing it without bound. Protects the latency of the requests you do accept.

**Liveness vs readiness.** Liveness asks "should this process be restarted?" (here: is the scheduler
thread alive). Readiness asks "should it receive traffic?" (here: model loaded and warmed up). Mixing
them up restarts pods that are merely busy.

**SLI, SLO, error budget.** An SLI is a measured quantity (share of requests with TTFT under 2 s), an
SLO is the target for it (99%), the error budget is the allowed miss (1%).

**Burn rate.** How fast the error budget is being spent relative to the rate that would exactly use it
up over the SLO window. The page-level alert fires when the burn rate is 14.4x over both an hour and
five minutes: fast enough to matter, sustained enough not to be noise.

**Histogram quantile.** Prometheus stores latency as counts per bucket, and `histogram_quantile`
estimates a percentile from them. Bucket edges are chosen around the SLO, so the estimate is accurate
where it matters (near 2 s) and coarse where it does not.

**Cardinality.** The number of distinct label combinations a metric has. Labelling by request id or
prompt would create unbounded series and take the metrics system down, so only bounded labels (outcome)
are used.

**Golden test.** A test that compares output to a stored reference exactly. Here the reference is the
HuggingFace greedy output, compared as token ids.
