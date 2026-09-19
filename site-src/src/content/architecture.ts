/** The system map: what each component is for, the decisions inside it, and where it lives. */

export type NodeGroup = 'client' | 'service' | 'core' | 'ops' | 'ship'

export interface ArchNode {
  id: string
  title: string
  sub: string
  group: NodeGroup
  x: number
  y: number
  w: number
  h: number
  role: string
  decisions: string[]
  files: string[]
  limitation?: string
  proof?: string
}

export interface ArchEdge {
  id: string
  from: string
  to: string
  d: string
  label?: string
  lx?: number
  ly?: number
  anchor?: 'start' | 'middle'
  kind: 'request' | 'control' | 'metrics' | 'return'
}

/** Text may contain {runs}, {slow_min}, {slow_max}, {speedup}; the component fills them from data.json. */
export const ARCH_VIEW = { x: 0, y: -14, w: 1040, h: 512 } as const

const W = 190
const H = 88
const C = [20, 290, 560, 830] as const
const R = [30, 214, 398] as const

export const NODES: ArchNode[] = [
  {
    id: 'loadgen', title: 'Load generator', sub: 'Go · open-loop Poisson', group: 'client', x: C[0], y: R[0], w: W, h: H,
    role: 'Sends requests at scheduled times whether or not earlier ones have finished, so a slow server builds a queue exactly as it would in production.',
    decisions: [
      'Time to first token is measured from the scheduled arrival, not from when the goroutine got round to sending, so generator lateness cannot hide server latency.',
      'Goodput counts requests that finish and meet both latency targets. Rejected and unfinished requests count against it.',
      'Warmup is discarded, seeds are fixed, and the run refuses to start if another run holds the port.',
    ],
    files: ['bench/main.go', 'bench/report.go', 'scripts/run_bench.sh'],
    proof: 'Drove all {runs} published runs.',
  },
  {
    id: 'api', title: 'HTTP API', sub: 'FastAPI · NDJSON', group: 'service', x: C[1], y: R[0], w: W, h: H,
    role: 'Turns an HTTP request into a Request object and streams tokens back as they are produced, with a detokeniser that never emits half a UTF-8 character.',
    decisions: [
      'Cancels the request when the client disconnects, so abandoned work stops consuming compute and KV memory.',
      '400 for bad input, 413 for a request larger than the whole KV pool, 429 with Retry-After when the queue is full.',
      'One worker per process: the process owns the model and the KV pool, so scale out by replicas.',
      'Readiness is separate from liveness: ready only after the model is loaded and warmed up.',
    ],
    files: ['engine/api.py', 'engine/detokenizer.py'],
    proof: 'Streamed text is tested to equal the decoded token ids, including emoji and CJK.',
  },
  {
    id: 'loop', title: 'Engine loop', sub: 'thread · admission cap', group: 'service', x: C[2], y: R[0], w: W, h: H,
    role: 'Runs the scheduler on a dedicated thread. Only this thread ever touches scheduler state; everything else hands work over through a thread-safe inbox.',
    decisions: [
      'No locks around scheduler state, because nothing else is allowed to reach it.',
      'Front-door admission control: when the queue reaches its cap the request is refused instead of queued without bound.',
    ],
    files: ['engine/scheduler.py'],
    proof: 'Queue-cap behaviour is unit tested, and observed under overload at twice capacity.',
  },
  {
    id: 'sched', title: 'Scheduler', sub: 'continuous · preemption', group: 'core', x: C[3], y: R[0], w: W, h: H,
    role: 'The heart of the project. Every iteration it retires finished requests, admits waiting ones, makes room for the next token of every row, and runs one decode step.',
    decisions: [
      'Continuous batching: a slot freed this step is refilled next step, instead of waiting for the whole batch to drain.',
      'Strict first-come first-served admission, so a large request is never starved by a stream of small ones.',
      'Preempt and recompute when memory runs out: evict the most recently admitted request among those evicted the fewest times, keep its generated tokens, re-prefill later.',
      'Starvation guard: evicted requests re-enter at the front and are the last to be evicted again.',
    ],
    files: ['engine/scheduler.py', 'engine/request.py'],
    limitation: 'Prefill is not chunked, so one long prompt stalls every running request while it is processed.',
    proof: 'Requests joining, leaving and being evicted mid-generation produce token-identical output.',
  },
  {
    id: 'obs', title: 'Observability', sub: 'Prometheus · Grafana', group: 'ops', x: C[1], y: R[1], w: W, h: H,
    role: 'Operators get latency histograms, queue depth, running batch, KV use, preemptions and outcomes, plus a JSON log line per request with its request id.',
    decisions: [
      'State gauges are read from the scheduler at scrape time, so they are never stale and cost the engine thread nothing.',
      'No request id or prompt in any label: unbounded cardinality would take Prometheus down.',
      'Alerts are generated from one source file, and a test checks that every metric a panel or alert queries really exists in the live output.',
    ],
    files: ['engine/observability.py', 'deploy/prometheus/alerts.yml', 'scripts/build_dashboard.py'],
    proof: 'promtool accepts the rules, and every dashboard query returned data under real load.',
  },
  {
    id: 'runner', title: 'Model runner', sub: 'own GPT-2 forward', group: 'core', x: C[2], y: R[1], w: W, h: H,
    role: 'A GPT-2 forward pass written from scratch (Hugging Face supplies weights and tokenizer only). One function handles both prefill and decode, for a batch where every row sits at a different length.',
    decisions: [
      'Every row has its own positions and its own mask: query t of row i sits at position start_i + t and may see key j only if j is at most that position and inside the row.',
      'Only the last real token of each row goes through the language-model head.',
      'Single-row cases keep the exact kernels of the first implementation, so numerics match.',
    ],
    files: ['engine/model_runner.py'],
    proof: 'Greedy tokens are identical to the Hugging Face reference for every fixture, alone or in any batch.',
  },
  {
    id: 'blocks', title: 'Block manager', sub: 'free list · tables', group: 'core', x: C[3], y: R[1], w: W, h: H,
    role: 'Hands out fixed-size KV blocks from a free list and keeps a block table per request, so a sequence grows one block at a time and its blocks need not be adjacent.',
    decisions: [
      'A block is taken exactly when a token first lands in it: a 16-token sequence holds one block, and the 17th token opens a second.',
      'Worst-case commit admission when preemption is off, so it can never over-commit. Optimistic admission with headroom when preemption is on.',
      'A request that could never fit even in an empty pool is refused up front, otherwise it would be evicted and readmitted forever.',
    ],
    files: ['engine/block_manager.py'],
    proof: 'Boundary cases (15, 16, 17 and 32 tokens) are fixtures, and a test dumps the block table and compares every K and V bit for bit.',
  },
  {
    id: 'kv', title: 'KV cache storage', sub: 'slot pool · paged pool', group: 'core', x: C[2], y: R[2], w: 460, h: H,
    role: 'One flat pool of blocks per layer. Attention gathers the blocks a request owns into a temporary contiguous buffer and runs ordinary attention on the copy.',
    decisions: [
      'Three interchangeable layouts behind one interface: a single cache, a slot pool that reserves the full context per request, and the paged pool.',
      'The pool is zero-filled at start-up so page faults never land on a request.',
      'The cost of a token is 72 KiB across 12 layers, which is why memory decides how many requests can be in flight at once, even though on a CPU the arithmetic sets the ceiling on speed.',
    ],
    files: ['engine/cache.py'],
    limitation: 'Attention copies scattered blocks every layer and every step. A production system uses a fused kernel that walks the block table inside attention, which is not possible on a CPU.',
    proof: 'Paged was {slow_min} to {slow_max} percent slower than contiguous when memory was plentiful, and {speedup} times faster when it was scarce (closed-loop burst).',
  },
  {
    id: 'gate', title: 'Correctness gate', sub: 'golden tests · CI', group: 'ship', x: C[0], y: R[1], w: W, h: H,
    role: 'Greedy decoding is deterministic, so every configuration must reproduce the Hugging Face reference token for token. Wrong output from this kind of system is fluent, so it can only be caught mechanically.',
    decisions: [
      'Comparison is exact token-id equality. No test has a tolerance.',
      'Fixtures cover the block boundaries, long prompts, long outputs, mixed batches and neighbours joining and leaving.',
      'Bugs were injected on purpose to check the tests can fail. One got through, which exposed a real gap.',
    ],
    files: ['tests/test_golden.py', 'tests/test_paged.py', 'tests/test_preemption.py', 'scripts/make_fixtures.py'],
    proof: 'Runs on every push, and nothing ships unless it is green.',
  },
  {
    id: 'deploy', title: 'Delivery', sub: 'Docker · K8s · Cloudflare', group: 'ship', x: C[0], y: R[2], w: W, h: H,
    role: 'A non-root image with the weights baked in that runs offline, Kubernetes manifests with probes, zero-downtime rollout, autoscaling and a disruption budget, and this page served from Cloudflare with strict security headers.',
    decisions: [
      'Image tag is the model version, so a rollback is a redeploy.',
      'CPU limit equals torch thread count, because threads beyond the quota are throttled and make tail latency worse.',
    ],
    files: ['Dockerfile', 'deploy/k8s/', '.github/workflows/'],
    limitation: 'The Kubernetes manifests have not been applied to a live cluster.',
    proof: 'The image runs under the pod security restrictions and returns the golden tokens.',
  },
]

export const EDGES: ArchEdge[] = [
  { id: 'e1', from: 'loadgen', to: 'api', kind: 'request', d: 'M210,74 H290', label: 'POST', lx: 250, ly: 64, anchor: 'middle' },
  { id: 'e2', from: 'api', to: 'loop', kind: 'request', d: 'M480,74 H560', label: 'inbox', lx: 520, ly: 64, anchor: 'middle' },
  { id: 'e3', from: 'loop', to: 'sched', kind: 'request', d: 'M750,74 H830', label: 'submit', lx: 790, ly: 64, anchor: 'middle' },
  { id: 'e4', from: 'sched', to: 'runner', kind: 'request', d: 'M870,118 V166 H655 V214', label: 'step', lx: 762, ly: 158, anchor: 'middle' },
  { id: 'e5', from: 'sched', to: 'blocks', kind: 'control', d: 'M955,118 V214', label: 'allocate', lx: 962, ly: 172 },
  { id: 'e6', from: 'runner', to: 'kv', kind: 'request', d: 'M655,300 V398', label: 'write · gather', lx: 662, ly: 352 },
  { id: 'e7', from: 'blocks', to: 'kv', kind: 'control', d: 'M955,300 V398', label: 'block tables', lx: 962, ly: 352 },
  { id: 'e8', from: 'sched', to: 'api', kind: 'return', d: 'M925,30 V8 H385 V30', label: 'tokens stream back', lx: 655, ly: 0, anchor: 'middle' },
  { id: 'e9', from: 'api', to: 'obs', kind: 'metrics', d: 'M385,118 V214', label: '/metrics', lx: 392, ly: 172 },
  { id: 'e10', from: 'gate', to: 'deploy', kind: 'control', d: 'M115,300 V398', label: 'green only', lx: 122, ly: 352 },
]

/** The journey of one request, as a walk through the map. */
export const TRACE: { node: string; caption: string }[] = [
  { node: 'loadgen', caption: 'A request is scheduled at a Poisson arrival time and sent, whether or not earlier ones are done.' },
  { node: 'api', caption: 'The API validates it (400, 413) and hands it over. A full queue answers 429 instead.' },
  { node: 'loop', caption: 'It crosses a thread-safe inbox. Only the engine thread ever touches the scheduler.' },
  { node: 'sched', caption: 'It waits in the queue until admission: first come first served, evicted requests first.' },
  { node: 'blocks', caption: 'Enough KV blocks are allocated for the prompt, and a block table records where they are.' },
  { node: 'runner', caption: 'Prefill runs the whole prompt in one forward pass and yields the first token. Then it joins the decode batch.' },
  { node: 'kv', caption: 'Each decode step writes one token of K and V, then gathers the request’s blocks for attention.' },
  { node: 'sched', caption: 'Each step emits a token. If memory runs out, the newest admitted request is evicted and recomputed later.' },
  { node: 'api', caption: 'Tokens stream back as newline-delimited JSON. A closed connection cancels the request and frees its blocks.' },
  { node: 'obs', caption: 'On completion, latency histograms and counters are updated and one JSON log line is written.' },
]

export const GROUP_LABEL: Record<NodeGroup, string> = {
  client: 'Load',
  service: 'Service',
  core: 'Engine core',
  ops: 'Operations',
  ship: 'Proof and delivery',
}
