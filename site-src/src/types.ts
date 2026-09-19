/** Shape of site-src/src/data.json, written by scripts/build_site.py from the raw run files. */

export interface Stat {
  median: number
  min: number
  max: number
}

export type MaybeStat = Stat | null

export type WorkloadKey = 'A' | 'B' | 'C'

export interface AblationRow {
  key: string
  label: string
  kv: 'none' | 'contiguous' | 'paged'
  batching: 'none' | 'static' | 'continuous'
  paging: 'yes' | 'no'
  adds: string
  goodput: MaybeStat
  throughput: MaybeStat
  ttft_p99: MaybeStat
  slot_util: MaybeStat
  kv_eff: MaybeStat
  preemptions: MaybeStat
}

export interface LoadPoint {
  rate: number
  goodput: MaybeStat
  throughput: MaybeStat
  ttft_p99: MaybeStat
  rejected: MaybeStat
  completed: MaybeStat
}

export type SystemKey = 'm0_naive' | 'm2_static' | 'm3_continuous' | 'm5_full'
export type Backend = 'contiguous' | 'paged'
export type LengthSpec = readonly [kind: 'fixed', value: number] | readonly [kind: 'lognormal', median: number, sigma: number, lo: number, hi: number]

export interface SiteData {
  meta: {
    machine: { cpu?: string; logical_cores?: number; ram_gib?: number | null; torch?: string; os?: string; go?: string }
    runs: number
    seeds: number
    slo: { ttft_s: number; tpot_s: number }
    workloads: Record<WorkloadKey, { prompt: LengthSpec; output: LengthSpec }>
    ablation_rates: Record<WorkloadKey, number>
    queue_cap: number
    kv_budget_mib: number
    threads: number
  }
  milestones: {
    naive_tok_s: number
    kv_tok_s: number
    kv_speedup: number
    static16_tok_s: number
    sat_static_tok_s: number
    sat_cont_tok_s: number
    sat_static_util: number
    sat_cont_util: number
    padding_waste_cont: number
  }
  ablation: Record<WorkloadKey, { rate: number; rows: AblationRow[] }>
  load: { rates: number[]; systems: Record<SystemKey, LoadPoint[]> }
  budget: {
    budgets: number[]
    series: Record<Backend, { mib: number; goodput: MaybeStat; throughput: MaybeStat; kv_eff: MaybeStat }[]>
  }
  maxbatch: { max_batch: number; throughput: MaybeStat }[]
  blocks: { block: number; kv_eff: MaybeStat; throughput: MaybeStat }[]
  overload: {
    p99_ttft_at_4: number
    p99_ttft_at_max: number
    max_rate: number
    rejected_at_max: number
    completed_at_max: number
  }
  m4_burst: { paged_slowdown_pct_min: number; paged_slowdown_pct_max: number; paged_speedup_at_128: number }
  facts: {
    tests: number | null
    loc: { engine_python: number; tests_python: number; scripts: number; load_generator_go: number; site_typescript: number }
    alert_rules: number
    recording_rules: number
    dashboard_panels: number
    k8s_manifests: number
    docs_pages: number
    golden_fixtures: number
  }
  stall: {
    series: { stall_baseline: [number, number][]; stall_injected: [number, number][] }
    worst_gap_s: { stall_baseline: number | null; stall_injected: number | null }
  }
  limitations: { file: string; text: string }[]
}

/** One entry in the engineering log. `source` is a quote that must appear in docs/06-build-log.md. */
export type ProblemTag = 'measurement' | 'correctness' | 'harness' | 'operations' | 'process'
export interface Problem {
  id: string
  tag: ProblemTag
  when: string
  title: string
  symptom: string
  wrong_model: string
  cause: string
  fix: string
  lesson: string
  evidence: string
  source: string
}

/** One row of the honest verification matrix. `source` must appear in docs/07-operations.md. */
export type VerificationStatus = 'verified' | 'not-verified'
export interface VerificationItem {
  area: string
  claim: string
  status: VerificationStatus
  how: string
  source: string
  /** Document the quote is checked against; defaults to docs/07-operations.md. */
  doc?: string
}
