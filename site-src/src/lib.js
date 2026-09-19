import { useEffect, useRef, useState } from 'react'

export const f1 = (v) => (v == null ? '-' : v.toFixed(1))
export const f2 = (v) => (v == null ? '-' : v.toFixed(2))
export const f0 = (v) => (v == null ? '-' : Math.round(v).toString())
export const range = (s, f = f2) => (s ? `${f(s.min)} to ${f(s.max)}` : '')

/** Measure an element's width and keep it current. */
export function useWidth(initial = 720) {
  const ref = useRef(null)
  const [w, setW] = useState(initial)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))))
    ro.observe(el)
    setW(Math.max(280, Math.round(el.getBoundingClientRect().width)))
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

/** Deterministic PRNG so illustrations replay identically. */
export function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** "Nice" axis ticks from 0 to max. */
export function niceTicks(max, count = 5) {
  const raw = max / count
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10
  const ticks = [0]
  for (let v = step; ; v += step) { ticks.push(+v.toFixed(10)); if (v >= max - 1e-9) break }  // last tick covers the data
  return ticks
}
