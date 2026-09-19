import { useMemo, useRef, useState } from 'react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { niceTicks, useWidth } from '../lib.js'

const EASE = [0.16, 1, 0.3, 1]

/**
 * Hand-drawn SVG line chart. Medians are lines, min to max across seeds are whiskers.
 * Hover, touch or arrow keys move a crosshair; the readout below lists every series at that x.
 * series: [{ key, label, color, dash, points: [{ x, y, min, max }] }]
 */
export default function LineChart({
  series, xs, xFormat = (v) => v, yFormat = (v) => v, xLabel, yLabel, height = 340,
  logY = false, yMin, yMax, xMode = 'linear', refLine, annotations = [], title, sub, tag,
  ariaLabel, readoutFormat, extra,
}) {
  const [boxRef, w] = useWidth()
  const wrapRef = useRef(null)
  const inView = useInView(boxRef, { once: true, margin: '0px 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [active, setActive] = useState(null)
  const [asTable, setAsTable] = useState(false)

  const narrow = w < 620
  const m = { l: 46, r: narrow ? 14 : 132, t: 14, b: 40 }
  const iw = w - m.l - m.r
  const ih = height - m.t - m.b

  const allY = series.flatMap((s) => s.points.flatMap((p) => [p.y, p.max].filter((v) => v != null)))
  const dMax = yMax ?? Math.max(...allY) * 1.08
  const ticks = useMemo(() => (logY ? [0.1, 1, 10, 100].filter((t) => t <= dMax * 1.5) : niceTicks(dMax, 5)), [logY, dMax])
  const top = logY ? Math.max(...ticks) : ticks[ticks.length - 1]
  const lo = logY ? (yMin ?? 0.05) : 0

  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const X = (x) => m.l + (xMode === 'point' ? (xs.indexOf(x) / (xs.length - 1)) * iw : ((x - xMin) / (xMax - xMin)) * iw)
  const Y = (y) => {
    if (logY) return m.t + ih - ((Math.log10(Math.max(y, lo)) - Math.log10(lo)) / (Math.log10(top) - Math.log10(lo))) * ih
    return m.t + ih - (y / top) * ih
  }

  const path = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('')

  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left
    let best = 0, bd = Infinity
    xs.forEach((x, i) => { const d = Math.abs(X(x) - (px + m.l - 10)); if (d < bd) { bd = d; best = i } })
    setActive(best)
    const c = wrapRef.current
    if (c) {
      const cr = c.getBoundingClientRect()
      c.style.setProperty('--mx', `${e.clientX - cr.left}px`)
      c.style.setProperty('--my', `${e.clientY - cr.top}px`)
    }
  }
  function key(e) {
    if (e.key === 'ArrowRight') { setActive((a) => Math.min(xs.length - 1, (a ?? -1) + 1)); e.preventDefault() }
    if (e.key === 'ArrowLeft') { setActive((a) => Math.max(0, (a ?? 1) - 1)); e.preventDefault() }
    if (e.key === 'Escape') setActive(null)
  }

  // Direct labels at the right edge, nudged apart so they never overlap.
  const labels = useMemo(() => {
    if (narrow) return []
    const ends = series.map((s) => {
      const p = s.points[s.points.length - 1]
      const early = p.x < xMax   // a line that stops early is labelled where it stops
      return { key: s.key, label: s.label, color: s.color, y: Y(p.y), x: early ? X(p.x) + 12 : w - m.r + 12 }
    }).sort((a, b) => a.y - b.y)
    for (let i = 1; i < ends.length; i++) if (ends[i].x === ends[i - 1].x && ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15
    return ends
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, w, narrow, top])

  const ax = active != null ? xs[active] : null

  return (
    <div className="chart" ref={wrapRef}>
      <div className="chart-top">
        <div>
          <div className="chart-title">{title}</div>
          {sub && <div className="chart-sub">{sub}</div>}
        </div>
        <div style={{ display: 'flex', gap: '.9rem', alignItems: 'center' }}>
          {tag && <span className={`tag ${tag.toLowerCase()}`}>{tag}</span>}
          <button className="link-btn" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
            {asTable ? 'View as chart' : 'View as table'}
          </button>
        </div>
      </div>
      {extra}
      <div className="legend" style={{ display: 'flex', flexWrap: 'wrap', gap: '.3rem 1.2rem', fontSize: '.8125rem', color: 'var(--ink-2)', margin: '0 0 .4rem' }}>
        {series.map((s) => (
          <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: '.45rem' }}>
            <svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dash || undefined} strokeLinecap="round" /><circle cx="11" cy="4" r="3.2" fill={s.color} /></svg>
            {s.label}
          </span>
        ))}
      </div>

      <div ref={boxRef}>
        {asTable ? (
          <div className="tscroll" style={{ paddingBlock: '.5rem' }}>
            <table className="data">
              <thead><tr><th>{xLabel}</th>{series.map((s) => <th key={s.key} className="r">{s.label}</th>)}</tr></thead>
              <tbody>
                {xs.map((x) => (
                  <tr key={x}>
                    <td className="num">{xFormat(x)}</td>
                    {series.map((s) => {
                      const p = s.points.find((q) => q.x === x)
                      return <td key={s.key} className="r num">{p ? `${yFormat(p.y)}${p.min != null && p.max != null && p.min !== p.max ? ` (${yFormat(p.min)} to ${yFormat(p.max)})` : ''}` : '-'}</td>
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
                <line className="tick" x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} />
                <text x={m.l - 8} y={Y(t) + 4} textAnchor="end">{yFormat(t)}</text>
              </g>
            ))}
            <line className="axis" x1={m.l} x2={w - m.r} y1={m.t + ih} y2={m.t + ih} />
            {xs.map((x) => (
              <text key={x} x={X(x)} y={height - 18} textAnchor="middle">{xFormat(x)}</text>
            ))}
            {xLabel && <text x={m.l + iw / 2} y={height - 2} textAnchor="middle">{xLabel}</text>}
            {yLabel && <text x={0} y={10} textAnchor="start">{yLabel}</text>}
            {refLine != null && (
              <g>
                <line x1={m.l} x2={w - m.r} y1={Y(refLine.y)} y2={Y(refLine.y)} stroke="var(--muted)" strokeDasharray="4 4" />
                <text x={w - m.r - 4} y={Y(refLine.y) - 6} textAnchor="end">{refLine.label}</text>
              </g>
            )}
            {annotations.map((a, i) => (
              <g key={i}>
                <line x1={X(a.x)} x2={X(a.x)} y1={m.t} y2={m.t + ih} stroke="var(--line-strong)" strokeDasharray="2 4" />
                <text x={X(a.x) + 6} y={m.t + 12} style={{ fill: 'var(--ink-2)' }}>{a.text}</text>
              </g>
            ))}
            {ax != null && <line x1={X(ax)} x2={X(ax)} y1={m.t} y2={m.t + ih} stroke="var(--ink-2)" strokeWidth="1" />}
            {series.map((s) => (
              <g key={s.key}>
                {s.points.map((p) => p.min != null && p.max != null && p.max !== p.min && (
                  <line key={`w${p.x}`} x1={X(p.x)} x2={X(p.x)} y1={Y(p.min)} y2={Y(p.max)} stroke={s.color} strokeWidth="1.5" opacity=".5" />
                ))}
                <motion.path
                  d={path(s.points)} fill="none" stroke={s.color} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round"
                  strokeDasharray={s.dash || undefined}
                  initial={reduce ? false : { pathLength: 0, opacity: 0.4 }}
                  animate={inView || reduce ? { pathLength: 1, opacity: 1 } : {}}
                  transition={{ duration: 1.1, ease: EASE }}
                />
                {s.points.map((p) => (
                  <circle key={p.x} cx={X(p.x)} cy={Y(p.y)} r={ax === p.x ? 5.5 : 3.6} fill={s.color} stroke="var(--bg)" strokeWidth="2"
                    style={{ transition: 'r 140ms cubic-bezier(0.23,1,0.32,1)' }} />
                ))}
              </g>
            ))}
            {labels.map((l) => (
              <text key={l.key} className="lbl" x={l.x} y={l.y + 4} style={{ fill: l.color }}>{l.label}</text>
            ))}
            <rect x={m.l - 10} y={m.t} width={iw + 20} height={ih} fill="transparent" tabIndex={0}
              aria-label={`${ariaLabel} Use left and right arrow keys to read values.`}
              onPointerMove={move} onPointerDown={move} onPointerLeave={() => setActive(null)}
              onKeyDown={key} onFocus={() => setActive((a) => a ?? 0)} onBlur={() => setActive(null)}
              style={{ outline: 'none', cursor: 'crosshair' }} />
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
                    <b className="num ink" style={{ fontWeight: 500 }}>
                      {p ? (readoutFormat ? readoutFormat(s.key, p) : yFormat(p.y)) : 'not run'}
                    </b>
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
