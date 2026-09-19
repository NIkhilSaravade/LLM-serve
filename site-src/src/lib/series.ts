import type { Series } from '../components/LineChart'
import type { LoadPoint, SiteData, SystemKey, MaybeStat } from '../types'

export interface SystemMeta {
  key: SystemKey
  label: string
  color: string
}

/** One colour per system, on every chart. Validated for colour-blind separation on both surfaces. */
export const SYSTEMS: readonly SystemMeta[] = [
  { key: 'm0_naive', label: 'Naive', color: 'var(--s-naive)' },
  { key: 'm2_static', label: 'Static batching', color: 'var(--s-static)' },
  { key: 'm3_continuous', label: 'Continuous, contiguous KV', color: 'var(--s-cont)' },
  { key: 'm5_full', label: 'Continuous + paged KV', color: 'var(--s-paged)' },
]

type LoadMetric = 'goodput' | 'throughput' | 'ttft_p99'

export function loadSeries(data: SiteData, metric: LoadMetric): Series[] {
  return SYSTEMS.map((s) => ({
    key: s.key,
    label: s.label,
    color: s.color,
    points: data.load.systems[s.key].flatMap((p: LoadPoint) => {
      const m: MaybeStat = p[metric]
      return m ? [{ x: p.rate, y: m.median, min: m.min, max: m.max }] : []
    }),
  }))
}

export function goodputAt(data: SiteData, key: SystemKey, rate: number): number | null {
  const p = data.load.systems[key].find((q) => q.rate === rate)
  return p?.goodput?.median ?? null
}
