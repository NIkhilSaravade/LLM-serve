import { useEffect, useRef, useState, type RefObject } from 'react'

/** Track an element's width, so SVG charts can be drawn at their real size. */
export function useWidth<T extends HTMLElement>(initial = 720): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [w, setW] = useState(initial)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = (width: number) => setW(Math.max(280, Math.round(width)))
    const ro = new ResizeObserver((entries) => {
      const e = entries[0]
      if (e) measure(e.contentRect.width)
    })
    ro.observe(el)
    measure(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

/** Highlight the section nearest the top of the viewport. */
export function useScrollSpy(ids: readonly string[]): string {
  const [active, setActive] = useState(ids[0] ?? '')
  useEffect(() => {
    const els = ids.map((id) => document.getElementById(id)).filter((e): e is HTMLElement => e !== null)
    if (!els.length) return
    const visible = new Map<string, number>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) visible.set(e.target.id, e.isIntersecting ? e.intersectionRatio : 0)
        // the first listed section that is on screen wins, so the highlight follows reading order
        const first = ids.find((id) => (visible.get(id) ?? 0) > 0)
        if (first) setActive(first)
      },
      { rootMargin: '-15% 0px -70% 0px', threshold: [0, 0.01, 0.25, 1] },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [ids])
  return active
}

/** Fraction of the page scrolled, 0 to 1. */
export function useScrollProgress(): number {
  const [p, setP] = useState(0)
  useEffect(() => {
    let raf = 0
    const on = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const max = document.documentElement.scrollHeight - window.innerHeight
        setP(max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0)
      })
    }
    on()
    window.addEventListener('scroll', on, { passive: true })
    window.addEventListener('resize', on)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', on)
      window.removeEventListener('resize', on)
    }
  }, [])
  return p
}

/** setInterval that pauses when `active` is false and always cleans up. */
export function useTicker(callback: () => void, ms: number, active: boolean): void {
  const cb = useRef(callback)
  cb.current = callback
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => cb.current(), ms)
    return () => window.clearInterval(id)
  }, [ms, active])
}
