import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { niceTicks } from '../lib/format'
import { useWidth } from '../lib/hooks'
import { EASE_OUT } from './Reveal'

export interface Point {
  x: number
  y: number
  min?: number
  max?: number
}

export interface Series {
  key: string
  label: string
  color: string
  dash?: string
  points: Point[]
}

interface Props {
  series: Series[]
  xs: number[]
  xFormat?: (v: number) => string
  yFormat?: (v: number) => string
  xLabel?: string
  height?: number
  logY?: boolean
  yMin?: number
  yMax?: number
  xMode?: 'linear' | 'point'
  refLine?: { y: number; label: string }
  annotations?: { x: number; text: string }[]
  title: string
  sub?: string
  tag?: 'Measured' | 'Illustration'
  ariaLabel: string
  readoutFormat?: (seriesKey: string, p: Point) => string
  extra?: ReactNode
}

const M_LEFT = 46
const M_TOP = 14
const M_BOTTOM = 40

/**
 * Hand-drawn SVG line chart. Medians are lines, the range across seeds is a whisker. Hover, touch or
 * arrow keys move a crosshair; the readout lists every series at that x. A table view is one click away.
 */
export default function LineChart({
  series, xs, xFormat = String, yFormat = String, xLabel, height = 340, logY = false, yMin, yMax,
  xMode = 'linear', refLine, annotations = [], title, sub, tag, ariaLabel, readoutFormat, extra,
}: Props) {
  const [boxRef, w] = useWidth<HTMLDivElement>()
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const inView = useInView(boxRef, { once: true, margin: '0px 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [active, setActive] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)

  const narrow = w < 620
  const mRight = narrow ? 14 : 178
  const iw = w - M_LEFT - mRight
  const ih = height - M_TOP - M_BOTTOM

  const allY = series.flatMap((s) => s.points.flatMap((p) => [p.y, p.max ?? p.y]))
  const dMax = yMax ?? Math.max(...allY) * 1.08
  const ticks = useMemo(() => (logY ? [0.1, 1, 10, 100].filter((t) => t <= dMax * 1.5) : niceTicks(dMax, 5)), [logY, dMax])
  const top = Math.max(...ticks)
  const lo = logY ? (yMin ?? 0.05) : 0

  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const X = (x: number): number =>
    M_LEFT + (xMode === 'point' ? (xs.indexOf(x) / Math.max(1, xs.length - 1)) * iw : ((x - xMin) / (xMax - xMin || 1)) * iw)
  const Y = (y: number): number => {
    if (logY) return M_TOP + ih - ((Math.log10(Math.max(y, lo)) - Math.log10(lo)) / (Math.log10(top) - Math.log10(lo))) * ih
    return M_TOP + ih - (y / top) * ih
  }
  const path = (pts: Point[]): string => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('')

  function move(e: PointerEvent<SVGRectElement>): void {
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left + (M_LEFT - 10)
    let best = 0
    let bd = Infinity
    xs.forEach((x, i) => {
      const d = Math.abs(X(x) - px)
      if (d < bd) { bd = d; best = i }
    })
    setActive(best)
    const c = wrapRef.current
    if (c) {
      const cr = c.getBoundingClientRect()
      c.style.setProperty('--mx', `${e.clientX - cr.left}px`)
      c.style.setProperty('--my', `${e.clientY - cr.top}px`)
    }
  }
  function key(e: KeyboardEvent<SVGRectElement>): void {
    if (e.key === 'ArrowRight') { setActive((a) => Math.min(xs.length - 1, (a ?? -1) + 1)); e.preventDefault() }
    if (e.key === 'ArrowLeft') { setActive((a) => Math.max(0, (a ?? 1) - 1)); e.preventDefault() }
    if (e.key === 'Escape') setActive(null)
  }

  // Direct labels at the end of each line, nudged apart so they never overlap.
  const labels = useMemo(() => {
    if (narrow) return []
    const ends = series.flatMap((s) => {
      const p = s.points[s.points.length - 1]
      if (!p) return []
      const early = p.x < xMax
      return [{ key: s.key, label: s.label, color: s.color, y: Y(p.y), x: early ? X(p.x) + 12 : w - mRight + 12 }]
    }).sort((a, b) => a.y - b.y)
    for (let i = 1; i < ends.length; i++) {
      const a = ends[i - 1]
      const b = ends[i]
      if (a && b && a.x === b.x && b.y - a.y < 15) b.y = a.y + 15
    }
    return ends
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, w, narrow, top])

  const ax = active != null ? xs[active] : undefined

  return (
    <div className="chart" ref={wrapRef}>
      <div className="chart-top">
        <div>
          <div className="chart-title">{title}</div>
          {sub && <div className="chart-sub">{sub}</div>}
        </div>
        <div className="row gap-4">
          {tag && <span className={`tag ${tag.toLowerCase()}`}>{tag}</span>}
          <button className="link-btn" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
            {asTable ? 'View as chart' : 'View as table'}
          </button>
        </div>
      </div>
      {extra}
      <div className="legend">
        {series.map((s) => (
          <span key={s.key}>
            <svg width="22" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="22" y2="4" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dash} strokeLinecap="round" />
              <circle cx="11" cy="4" r="3.2" fill={s.color} />
            </svg>
            {s.label}
          </span>
        ))}
      </div>

      <div ref={boxRef}>
        {asTable ? (
          <div className="tscroll" style={{ paddingBlock: '.5rem' }}>
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{xLabel}</th>
                  {series.map((s) => <th scope="col" key={s.key} className="r">{s.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {xs.map((x) => (
                  <tr key={x}>
                    <th scope="row" className="num">{xFormat(x)}</th>
                    {series.map((s) => {
                      const p = s.points.find((q) => q.x === x)
                      const range = p && p.min != null && p.max != null && p.min !== p.max ? ` (${yFormat(p.min)} to ${yFormat(p.max)})` : ''
                      return <td key={s.key} className="r num">{p ? `${yFormat(p.y)}${range}` : '-'}</td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <svg className="svg-chart" width={w} height={height} viewBox={`0 0 ${w} ${height}`} role="img" aria-label={ariaLabel}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="tick" x1={M_LEFT} x2={w - mRight} y1={Y(t)} y2={Y(t)} />
                <text x={M_LEFT - 8} y={Y(t) + 4} textAnchor="end">{yFormat(t)}</text>
              </g>
            ))}
            <line className="axis" x1={M_LEFT} x2={w - mRight} y1={M_TOP + ih} y2={M_TOP + ih} />
            {xs.map((x) => <text key={x} x={X(x)} y={height - 18} textAnchor="middle">{xFormat(x)}</text>)}
            {xLabel && <text x={M_LEFT + iw / 2} y={height - 2} textAnchor="middle">{xLabel}</text>}
            {refLine && (
              <g>
                <line x1={M_LEFT} x2={w - mRight} y1={Y(refLine.y)} y2={Y(refLine.y)} stroke="var(--muted)" strokeDasharray="4 4" />
                <text x={w - mRight - 4} y={Y(refLine.y) - 6} textAnchor="end">{refLine.label}</text>
              </g>
            )}
            {annotations.map((a) => (
              <g key={a.text}>
                <line x1={X(a.x)} x2={X(a.x)} y1={M_TOP} y2={M_TOP + ih} stroke="var(--line-strong)" strokeDasharray="2 4" />
                <text x={X(a.x) + 6} y={M_TOP + 12} style={{ fill: 'var(--ink-2)' }}>{a.text}</text>
              </g>
            ))}
            {ax != null && <line x1={X(ax)} x2={X(ax)} y1={M_TOP} y2={M_TOP + ih} stroke="var(--ink-2)" strokeWidth="1" />}
            {series.map((s) => (
              <g key={s.key}>
                {s.points.map((p) =>
                  p.min != null && p.max != null && p.max !== p.min ? (
                    <line key={`w${p.x}`} x1={X(p.x)} x2={X(p.x)} y1={Y(p.min)} y2={Y(p.max)} stroke={s.color} strokeWidth="1.5" opacity=".5" />
                  ) : null,
                )}
                <motion.path
                  d={path(s.points)} fill="none" stroke={s.color} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round"
                  strokeDasharray={s.dash}
                  initial={reduce ? false : { pathLength: 0, opacity: 0.4 }}
                  animate={inView || reduce ? { pathLength: 1, opacity: 1 } : {}}
                  transition={{ duration: 1.1, ease: EASE_OUT }}
                />
                {s.points.map((p) => (
                  <circle key={p.x} cx={X(p.x)} cy={Y(p.y)} r={ax === p.x ? 5.5 : 3.6} fill={s.color} stroke="var(--bg)" strokeWidth="2"
                    style={{ transition: 'r 140ms cubic-bezier(0.23,1,0.32,1)' }} />
                ))}
              </g>
            ))}
            {labels.map((l) => <text key={l.key} className="lbl" x={l.x} y={l.y + 4} style={{ fill: l.color }}>{l.label}</text>)}
            <rect
              x={M_LEFT - 10} y={M_TOP} width={iw + 20} height={ih} fill="transparent" tabIndex={0} role="group"
              aria-label={`${ariaLabel} Use left and right arrow keys to read values.`}
              onPointerMove={move} onPointerDown={move} onPointerLeave={() => setActive(null)}
              onKeyDown={key} onFocus={() => setActive((a) => a ?? 0)} onBlur={() => setActive(null)}
              style={{ outline: 'none', cursor: 'crosshair' }}
            />
          </svg>
        )}
      </div>

      {!asTable && (
        <div className="readout" aria-live="polite">
          {ax == null ? (
            <span className="x">Move across the chart, or focus it and use the arrow keys, to read exact values.</span>
          ) : (
            <>
              <span className="x num">{xLabel ? `${xLabel}: ` : ''}{xFormat(ax)}</span>
              {series.map((s) => {
                const p = s.points.find((q) => q.x === ax)
                return (
                  <span className="k" key={s.key}>
                    <i className="dot" style={{ background: s.color }} />
                    {s.label}
                    <b className="num ink">{p ? (readoutFormat ? readoutFormat(s.key, p) : yFormat(p.y)) : 'not run'}</b>
                  </span>
                )
              })}
            </>
          )}
        </div>
      )}
    </div>
  )
}
