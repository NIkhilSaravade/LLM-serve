# 00 — Project brief

## The one-line version

Build an LLM inference server from scratch, so that the throughput gains from
continuous batching and paged KV cache can be measured, isolated, and published.

## Why this project exists

This is a portfolio project. Its job is to prove one specific claim to a hiring
manager:

> This person understands why LLM serving is hard, and can build the systems
> parts that make it fast.

That claim is about **scheduling, memory management, and behaviour under load**.
It is not about machine learning. No model is trained here. No model is
fine-tuned here. The model is a fixed, boring workload that the engine has to
carry.

This matters because the AI infrastructure job market pays well for exactly this
skill and there are few people who have actually done it.

## The core idea, in plain words

When a language model generates text, it produces one token at a time. To
produce a single token, the machine must read the entire set of model weights
out of memory.

That is an appalling ratio. Gigabytes are read to do a tiny amount of arithmetic.
The processor spends most of its time waiting for memory, not computing.

The fix is to process many requests in the same step. Those requests share the
one weight read. So going from 1 sequence to 16 sequences costs almost nothing
extra in memory traffic, and produces 16 times the tokens.

So the whole problem becomes: **keep the batch as full as possible, all the
time.** Two things stop you.

1. **Static batching wastes slots.** A normal batch runs until every sequence in
   it is finished. One request wants 20 tokens, another wants 800. The short one
   finishes and its slot sits empty for the next 780 steps.
   Fix: **continuous batching** — reschedule at every step, not every batch.

2. **The KV cache wastes memory.** Each sequence needs somewhere to store the
   Keys and Values it has computed so far. Reserve the maximum possible length
   up front and most of it is never used. Less memory means smaller batches
   means less throughput.
   Fix: **paged KV cache** — fixed-size blocks and a block table, exactly like
   operating system virtual memory.

Both fixes are systems engineering. Neither is machine learning.

## What success looks like

A public page containing:

- Throughput versus offered load, for naive / static batching / continuous
  batching / continuous + paged.
- Latency percentiles (p50, p95, p99) for time-to-first-token and
  inter-token latency.
- An **ablation table** showing what each mechanism contributed on its own.
- The measured slot utilisation and KV memory utilisation for each variant.
- A clearly written limitations section.
- A repo where `./scripts/run_bench.sh` reproduces every number on the page.

A reader who knows this field should be able to look at the ablation table and
immediately tell that the work is real.

## Non-goals

State these plainly on the results page. Naming your own boundaries reads as
competence.

- **Not competing with vLLM, TGI, or TensorRT-LLM.** Those are production
  systems with years of kernel work. This is a demonstration of the mechanisms
  they use.
- **No GPU.** Everything is CPU. This lowers the absolute numbers and changes
  the shape of some curves. It is stated openly, not hidden.
- **No custom kernels.** Where paged attention would need a fused CUDA kernel,
  this uses a slow gather into a temporary buffer.
- **No distributed serving.** Single process, single machine. No tensor
  parallelism, no multi-node.
- **No quantisation.** fp32 on CPU.
- **Not a general model server.** GPT-2 only. Supporting many architectures adds
  code and proves nothing extra.

## The honest caveat about CPU

The reason batching helps is memory bandwidth. That reason is still true on a
CPU: the weights still have to be read from RAM every step.

But a CPU has far fewer parallel arithmetic units than a GPU. So as batch size
grows, a CPU runs out of compute sooner than a GPU runs out of memory bandwidth.
The batching win is real but smaller.

Expect roughly 3–6x from continuous batching on CPU, where GPU papers report
much larger numbers. **Say this on the results page.** A reader who knows the
field will trust every other number more because this one was not oversold.

## Audience for the results page

Two readers, and the page must serve both.

- **A recruiter or founder** who will spend 30 seconds. They need one chart at
  the top, one sentence explaining it, and a sense that this is serious.
- **A staff engineer** who will spend 10 minutes. They need the ablation table,
  the methodology section, and the limitations. They are looking for a reason to
  disbelieve the numbers. Give them none.

---

## Status (2026-09-19)

Built and measured. On this CPU, continuous batching gave 3.5x the goodput of static batching
(2.83 vs 0.80 requests/s within the latency SLO, workload B), and the paged KV cache raised memory
efficiency from 0.12 to 0.95 tokens stored per token reserved, which converts into throughput only
when KV memory is the constraint (128 MiB: 2.73 vs 0.18 req/s). The uniform workload, the least
flattering one, shows no separation between the batching systems at the load tested, and preemption
almost never fired at this scale. All of that is published as measured.

The success criteria above were met with these exceptions: workload lengths were scaled about 3x down,
and runs are shorter than "a few hundred requests per point" (`docs/04`, "As run"). A reader can
reproduce every number with `make bench`. Beyond the brief, the server is also packaged to be
operated (`docs/07-operations.md`). Read `docs/06-build-log.md` for the story, including what broke.

**Delivery (2026-09-19).** The results page is live at https://llm-serve.nikhilsaravade.com (Cloudflare Pages). Every
commit that passes CI is built into one image, published to GHCR, deployed to a Kubernetes cluster in CI, and put
through a bad-release drill, an SLO canary with automatic abort, and a performance gate before it is tagged `stable`
(`docs/09-release-pipeline.md`). A production deployment (one k3s VM behind a Cloudflare Tunnel) is prepared as code
and validated in CI, but **it has not been deployed**: no live inference service exists.
