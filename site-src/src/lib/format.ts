import type { MaybeStat, Stat } from '../types'

export const f0 = (v: number | null | undefined): string => (v == null ? '-' : Math.round(v).toString())
export const f1 = (v: number | null | undefined): string => (v == null ? '-' : v.toFixed(1))
export const f2 = (v: number | null | undefined): string => (v == null ? '-' : v.toFixed(2))

/** "0.03 to 0.07", or an empty string when the seeds agree. */
export const spread = (s: MaybeStat, f: (v: number) => string = f2): string =>
  s && s.min !== s.max ? `${f(s.min)} to ${f(s.max)}` : ''

export const med = (s: MaybeStat): number | null => (s ? s.median : null)

export function need(s: MaybeStat, what: string): Stat {
  if (!s) throw new Error(`missing data: ${what}`)
  return s
}

/** Deterministic PRNG so illustrations replay identically. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Axis ticks from 0 up to and including the first tick that covers `max`. */
export function niceTicks(max: number, count = 5): number[] {
  const raw = max / count
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = ([1, 2, 2.5, 5, 10] as const).map((m) => m * mag).find((s) => s >= raw) ?? mag * 10
  const ticks = [0]
  for (let v = step; ; v += step) {
    ticks.push(+v.toFixed(10))
    if (v >= max - 1e-9) break
  }
  return ticks
}
