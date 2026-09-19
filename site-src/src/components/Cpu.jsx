import { useRef, useState } from 'react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import LineChart from './LineChart.jsx'
import Reveal from './Reveal.jsx'
import { f0, f1, f2, niceTicks, useWidth } from '../lib.js'

const EASE = [0.16, 1, 0.3, 1]

/** Largest gap between two tokens, per 0.25 s window, as seen by ordinary requests. */
function StallChart({ data }) {
  const [boxRef, w] = useWidth()
  const inView = useInView(boxRef, { once: true, margin: '0px 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [hover, setHover] = useState(null)
  const wrap = useRef(null)
  const base = data.stall.series.stall_baseline
  const inj = data.stall.series.stall_injected
  const m = { l: 46, r: 16, t: 16, b: 38 }
  const h = 300
  const iw = w - m.l - m.r, ih = h - m.t - m.b
  const tMax = Math.max(...base.map((p) => p[0]), ...inj.map((p) => p[0]))
  const gMax = Math.max(...base.map((p) => p[1]), ...inj.map((p) => p[1])) * 1.1
  const ticks = niceTicks(gMax, 4)
  const top = ticks[ticks.length - 1]
  const X = (t) => m.l + (t / tMax) * iw
  const Y = (g) => m.t + ih - (g / top) * ih
  const line = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')
  const worstB = data.stall.worst_gap_s.stall_baseline, worstI = data.stall.worst_gap_s.stall_injected
  const peak = inj.reduce((a, p) => (p[1] > a[1] ? p : a), inj[0])

  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const t = ((e.clientX - r.left) / r.width) * tMax
    const near = (s) => s.reduce((a, p) => (Math.abs(p[0] - t) < Math.abs(a[0] - t) ? p : a), s[0])
    setHover({ t: near(inj)[0], b: near(base)[1], i: near(inj)[1] })
    const c = wrap.current
    if (c) { const cr = c.getBoundingClientRect(); c.style.setProperty('--mx', `${e.clientX - cr.left}px`); c.style.setProperty('--my', `${e.clientY - cr.top}px`) }
  }

  return (
    <div className="chart" ref={wrap}>
      <div className="chart-top">
        <div>
          <div className="chart-title">The long-prefill stall</div>
          <div className="chart-sub">Largest gap between two tokens, per quarter second, seen by ordinary requests at steady 2 requests / s. Seed 1.</div>
        </div>
        <span className="tag measured">Measured</span>
      </div>
      <div style={{ display: 'flex', gap: '1.2rem', fontSize: '.8125rem', color: 'var(--ink-2)', marginBottom: '.4rem', flexWrap: 'wrap' }}>
        <span><i className="dot" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--s-naive)', marginRight: 6 }} />Steady load</span>
        <span><i className="dot" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--s-static)', marginRight: 6 }} />One 800-token prompt arrives at 15 s</span>
      </div>
      <div ref={boxRef}>
        <svg className="svg-chart" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img"
          aria-label={`Largest inter-token gap over time. Without the long prompt the worst gap was ${Math.round(worstB * 1000)} milliseconds; with it, ${Math.round(worstI * 1000)} milliseconds.`}>
          {ticks.map((t) => (
            <g key={t}><line className="tick" x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} /><text x={m.l - 8} y={Y(t) + 4} textAnchor="end">{Math.round(t * 1000)}</text></g>
          ))}
          <text x={0} y={10}>ms</text>
          <line className="axis" x1={m.l} x2={w - m.r} y1={m.t + ih} y2={m.t + ih} />
          {[0, 5, 10, 15, 20, 25, 30].filter((t) => t <= tMax).map((t) => <text key={t} x={X(t)} y={h - 18} textAnchor="middle">{t}</text>)}
          <text x={m.l + iw / 2} y={h - 2} textAnchor="middle">Time since start, s</text>
          <line x1={X(15)} x2={X(15)} y1={m.t} y2={m.t + ih} stroke="var(--line-strong)" strokeDasharray="2 4" />
          {hover && <line x1={X(hover.t)} x2={X(hover.t)} y1={m.t} y2={m.t + ih} stroke="var(--ink-2)" />}
          <motion.path d={line(base)} fill="none" stroke="var(--s-naive)" strokeWidth="1.75" strokeLinejoin="round" initial={reduce ? false : { pathLength: 0 }} animate={inView || reduce ? { pathLength: 1 } : {}} transition={{ duration: 1.2, ease: EASE }} />
          <motion.path d={line(inj)} fill="none" stroke="var(--s-static)" strokeWidth="1.75" strokeLinejoin="round" initial={reduce ? false : { pathLength: 0 }} animate={inView || reduce ? { pathLength: 1 } : {}} transition={{ duration: 1.2, delay: 0.15, ease: EASE }} />
          <circle cx={X(peak[0])} cy={Y(peak[1])} r="4.5" fill="var(--s-static)" stroke="var(--bg)" strokeWidth="2" />
          <text x={Math.min(X(peak[0]) + 10, w - m.r - 150)} y={Y(peak[1]) + 4} style={{ fill: 'var(--ink)', fontFamily: 'var(--font-sans)', fontSize: 12 }}>{Math.round(peak[1] * 1000)} ms stall</text>
          <rect x={m.l} y={m.t} width={iw} height={ih} fill="transparent" onPointerMove={move} onPointerLeave={() => setHover(null)} style={{ cursor: 'crosshair' }} />
        </svg>
      </div>
      <div className="readout" aria-live="polite">
        {hover
          ? <><span className="x num">t = {hover.t.toFixed(2)} s</span><span className="k">steady <b className="num ink" style={{ fontWeight: 500 }}>{Math.round(hover.b * 1000)} ms</b></span><span className="k">with long prompt <b className="num ink" style={{ fontWeight: 500 }}>{Math.round(hover.i * 1000)} ms</b></span></>
          : <span className="x">Worst gap over 3 seeds (median): {Math.round(worstB * 1000)} ms steady, {Math.round(worstI * 1000)} ms with one 800-token prompt.</span>}
      </div>
    </div>
  )
}

export default function Cpu({ data }) {
  const mb = data.maxbatch
  const first8 = mb.find((r) => r.max_batch === 8).throughput.median
  const last = mb[mb.length - 1].throughput.median
  return (
    <section id="cpu">
      <div className="wrap">
        <Reveal className="sec-head">
          <h2>Where a CPU runs out</h2>
          <p className="body">
            Batching helps because the weights are read once per step and used for every row. On a CPU the arithmetic units saturate
            long before memory bandwidth does, so the curve flattens: going from a batch of 8 to a batch of 32 adds only{' '}
            {Math.round(((last - first8) / first8) * 100)} percent throughput.
          </p>
        </Reveal>
        <div className="split">
          <Reveal>
            <LineChart
              title="Throughput against maximum batch size" tag="Measured" xMode="point"
              sub="Offered 8 requests / s, so the batch cap is what limits the server. Continuous + paged."
              series={[{ key: 'tp', label: 'Tokens / s', color: 'var(--s-paged)', points: mb.map((r) => ({ x: r.max_batch, y: r.throughput.median, min: r.throughput.min, max: r.throughput.max })) }]}
              xs={mb.map((r) => r.max_batch)} xFormat={(v) => `${v}`} yFormat={(v) => f0(v)} xLabel="Max batch size, rows per step" height={300}
              ariaLabel="Throughput against maximum batch size, flattening above 8 rows."
              readoutFormat={(k, p) => `${f0(p.y)} tokens / s`}
            />
          </Reveal>
          <Reveal delay={0.08}>
            <LineChart
              title="Memory efficiency against block size" tag="Measured" xMode="point"
              sub="Live tokens divided by allocated capacity. Smaller blocks waste less; the cost is more indirection."
              series={[{ key: 'eff', label: 'KV efficiency', color: 'var(--s-cont)', points: data.blocks.map((r) => ({ x: r.block, y: r.kv_eff.median, min: r.kv_eff.min, max: r.kv_eff.max })) }]}
              xs={data.blocks.map((r) => r.block)} xFormat={(v) => `${v}`} yFormat={(v) => f2(v)} yMax={1} xLabel="Block size, tokens" height={300}
              ariaLabel="KV memory efficiency against block size."
              readoutFormat={(k, p) => f2(p.y)}
            />
          </Reveal>
        </div>
        <div style={{ height: 'clamp(3rem, 6vw, 5rem)' }} />
        <div className="split wide-left">
          <Reveal><StallChart data={data} /></Reveal>
          <Reveal delay={0.1} className="prose" style={{ alignSelf: 'start', paddingTop: '3.4rem' }}>
            <p className="body">
              Prefill is not chunked, so one long prompt blocks every running request while it is processed. It shows up as a single
              spike, not a shift in the whole distribution. Chunked prefill is the obvious next step, and this chart is its “before”.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  )
}
