import { useRef, useState, type PointerEvent } from 'react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import LineChart from './LineChart'
import Reveal, { EASE_OUT } from './Reveal'
import Section from './Section'
import { data } from '../data'
import { f0, f2, niceTicks } from '../lib/format'
import { useWidth } from '../lib/hooks'

type Pair = [number, number]

/** Largest gap between two tokens, per 0.25 s window, as seen by ordinary requests. */
function StallChart() {
  const [boxRef, w] = useWidth<HTMLDivElement>()
  const inView = useInView(boxRef, { once: true, margin: '0px 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [hover, setHover] = useState<{ t: number; b: number; i: number } | null>(null)
  const wrap = useRef<HTMLDivElement | null>(null)
  const base: Pair[] = data.stall.series.stall_baseline
  const inj: Pair[] = data.stall.series.stall_injected
  const m = { l: 46, r: 16, t: 16, b: 38 }
  const h = 300
  const iw = w - m.l - m.r
  const ih = h - m.t - m.b
  const tMax = Math.max(...base.map((p) => p[0]), ...inj.map((p) => p[0]))
  const gMax = Math.max(...base.map((p) => p[1]), ...inj.map((p) => p[1])) * 1.1
  const ticks = niceTicks(gMax, 4)
  const top = Math.max(...ticks)
  const X = (t: number) => m.l + (t / tMax) * iw
  const Y = (g: number) => m.t + ih - (g / top) * ih
  const line = (pts: Pair[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')
  const worstB = data.stall.worst_gap_s.stall_baseline ?? 0
  const worstI = data.stall.worst_gap_s.stall_injected ?? 0
  const peak = inj.reduce<Pair>((a, p) => (p[1] > a[1] ? p : a), inj[0] ?? [0, 0])

  function move(e: PointerEvent<SVGRectElement>): void {
    const r = e.currentTarget.getBoundingClientRect()
    const t = ((e.clientX - r.left) / r.width) * tMax
    const near = (s: Pair[]): Pair => s.reduce<Pair>((a, p) => (Math.abs(p[0] - t) < Math.abs(a[0] - t) ? p : a), s[0] ?? [0, 0])
    const i = near(inj)
    setHover({ t: i[0], b: near(base)[1], i: i[1] })
    const c = wrap.current
    if (c) {
      const cr = c.getBoundingClientRect()
      c.style.setProperty('--mx', `${e.clientX - cr.left}px`)
      c.style.setProperty('--my', `${e.clientY - cr.top}px`)
    }
  }
  const draw = (delay: number) => ({
    initial: reduce ? (false as const) : { pathLength: 0 },
    animate: inView || reduce ? { pathLength: 1 } : {},
    transition: { duration: 1.2, delay, ease: EASE_OUT },
  })

  return (
    <div className="chart" ref={wrap}>
      <div className="chart-top">
        <div>
          <div className="chart-title">The long-prefill stall</div>
          <div className="chart-sub">Largest gap between two tokens, per quarter second, seen by ordinary requests at a steady 2 requests / s. Seed 1.</div>
        </div>
        <span className="tag measured">Measured</span>
      </div>
      <div className="legend">
        <span><i className="dot" style={{ background: 'var(--s-naive)' }} />Steady load</span>
        <span><i className="dot" style={{ background: 'var(--s-static)' }} />One 800-token prompt arrives at 15 s</span>
      </div>
      <div ref={boxRef}>
        <svg className="svg-chart" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img"
          aria-label={`Largest inter-token gap over time. Without the long prompt the worst gap was ${Math.round(worstB * 1000)} milliseconds; with it, ${Math.round(worstI * 1000)} milliseconds.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="tick" x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} />
              <text x={m.l - 8} y={Y(t) + 4} textAnchor="end">{Math.round(t * 1000)}</text>
            </g>
          ))}
          <text x={0} y={10}>ms</text>
          <line className="axis" x1={m.l} x2={w - m.r} y1={m.t + ih} y2={m.t + ih} />
          {[0, 5, 10, 15, 20, 25, 30].filter((t) => t <= tMax).map((t) => <text key={t} x={X(t)} y={h - 18} textAnchor="middle">{t}</text>)}
          <text x={m.l + iw / 2} y={h - 2} textAnchor="middle">Time since start, s</text>
          <line x1={X(15)} x2={X(15)} y1={m.t} y2={m.t + ih} stroke="var(--line-strong)" strokeDasharray="2 4" />
          {hover && <line x1={X(hover.t)} x2={X(hover.t)} y1={m.t} y2={m.t + ih} stroke="var(--ink-2)" />}
          <motion.path d={line(base)} fill="none" stroke="var(--s-naive)" strokeWidth="1.75" strokeLinejoin="round" {...draw(0)} />
          <motion.path d={line(inj)} fill="none" stroke="var(--s-static)" strokeWidth="1.75" strokeLinejoin="round" {...draw(0.15)} />
          <circle cx={X(peak[0])} cy={Y(peak[1])} r="4.5" fill="var(--s-static)" stroke="var(--bg)" strokeWidth="2" />
          <text x={Math.min(X(peak[0]) + 10, w - m.r - 150)} y={Y(peak[1]) + 4} className="lbl" style={{ fill: 'var(--ink)' }}>{Math.round(peak[1] * 1000)} ms stall</text>
          <rect x={m.l} y={m.t} width={iw} height={ih} fill="transparent" onPointerMove={move} onPointerLeave={() => setHover(null)} style={{ cursor: 'crosshair' }} />
        </svg>
      </div>
      <div className="readout" aria-live="polite">
        {hover ? (
          <>
            <span className="x num">t = {hover.t.toFixed(2)} s</span>
            <span className="k">steady <b className="num ink">{Math.round(hover.b * 1000)} ms</b></span>
            <span className="k">with long prompt <b className="num ink">{Math.round(hover.i * 1000)} ms</b></span>
          </>
        ) : (
          <span className="x">Worst gap over {data.meta.seeds} seeds (median): {Math.round(worstB * 1000)} ms steady, {Math.round(worstI * 1000)} ms with one 800-token prompt.</span>
        )}
      </div>
    </div>
  )
}

export default function Cpu() {
  const mb = data.maxbatch
  const at8 = mb.find((r) => r.max_batch === 8)?.throughput?.median ?? 0
  const last = mb[mb.length - 1]?.throughput?.median ?? 0
  const gain = at8 ? Math.round(((last - at8) / at8) * 100) : 0
  return (
    <Section
      id="cpu"
      title="Where a CPU runs out"
      intro={
        <>
          Batching helps because the weights are read once per step and used for every row. On a CPU the arithmetic units saturate long
          before memory bandwidth does, so the curve flattens: going from a batch of 8 to a batch of 32 adds only {gain} percent throughput.
        </>
      }
    >
      <div className="split">
        <Reveal>
          <LineChart
            title="Throughput against maximum batch size" tag="Measured" xMode="point"
            sub="Offered 8 requests / s, so the batch cap is what limits the server. Continuous + paged."
            series={[{ key: 'tp', label: 'Tokens / s', color: 'var(--s-paged)', points: mb.flatMap((r) => (r.throughput ? [{ x: r.max_batch, y: r.throughput.median, min: r.throughput.min, max: r.throughput.max }] : [])) }]}
            xs={mb.map((r) => r.max_batch)} xFormat={String} yFormat={f0} xLabel="Max batch size, rows per step" height={300}
            ariaLabel="Throughput against maximum batch size, flattening above 8 rows."
            readoutFormat={(_k, p) => `${f0(p.y)} tokens / s`}
          />
        </Reveal>
        <Reveal delay={0.08}>
          <LineChart
            title="Memory efficiency against block size" tag="Measured" xMode="point"
            sub="Live tokens divided by allocated capacity. Smaller blocks waste less; the cost is more indirection."
            series={[{ key: 'eff', label: 'KV efficiency', color: 'var(--s-cont)', points: data.blocks.flatMap((r) => (r.kv_eff ? [{ x: r.block, y: r.kv_eff.median, min: r.kv_eff.min, max: r.kv_eff.max }] : [])) }]}
            xs={data.blocks.map((r) => r.block)} xFormat={String} yFormat={f2} yMax={1} xLabel="Block size, tokens" height={300}
            ariaLabel="KV memory efficiency against block size."
            readoutFormat={(_k, p) => f2(p.y)}
          />
        </Reveal>
      </div>
      <div className="split wide-left gap-top">
        <Reveal><StallChart /></Reveal>
        <Reveal delay={0.1} className="prose aside">
          <p className="body">
            Prefill is not chunked, so one long prompt blocks every running request while it is processed. It shows up as a single spike,
            not a shift in the whole distribution. Chunked prefill is the obvious next step, and this chart is its &ldquo;before&rdquo;.
          </p>
        </Reveal>
      </div>
    </Section>
  )
}
