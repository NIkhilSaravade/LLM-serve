import { motion, useReducedMotion } from 'motion/react'
import LineChart from './LineChart.jsx'
import Reveal from './Reveal.jsx'
import { f2 } from '../lib.js'

const EASE = [0.16, 1, 0.3, 1]

export const SYSTEMS = [
  { key: 'm0_naive', label: 'Naive', color: 'var(--s-naive)' },
  { key: 'm2_static', label: 'Static batching', color: 'var(--s-static)' },
  { key: 'm3_continuous', label: 'Continuous, contiguous KV', color: 'var(--s-cont)' },
  { key: 'm5_full', label: 'Continuous + paged KV', color: 'var(--s-paged)' },
]

export const seriesFor = (data, metric) =>
  SYSTEMS.map((s) => ({
    ...s,
    points: data.load.systems[s.key].filter((p) => p[metric]).map((p) => ({ x: p.rate, y: p[metric].median, min: p[metric].min, max: p[metric].max })),
  }))

/** The one authored moment: the headline rises out of a clip, line by line. */
function Line({ children, i }) {
  const reduce = useReducedMotion()
  return (
    <span className="clip">
      <motion.span
        initial={reduce ? false : { y: '105%' }}
        animate={{ y: 0 }}
        transition={{ duration: 1, delay: 0.08 + i * 0.11, ease: EASE }}
      >
        {children}
      </motion.span>
    </span>
  )
}

export default function Hero({ data }) {
  const at4 = (k) => data.load.systems[k].find((p) => p.rate === 4).goodput.median
  return (
    <section className="hero" id="top">
      <div className="wrap hero-grid">
        <h1>
          <Line i={0}>What continuous</Line>
          <Line i={1}>batching <em>actually</em></Line>
          <Line i={2}>buys on a CPU.</Line>
        </h1>
        <Reveal delay={0.55} className="hero-sub">
          <p className="lede">
            A from-scratch GPT-2 inference server. The scheduler and the KV-cache memory manager are written from the ground up,
            then measured under Poisson load, including the results that do not flatter them.
          </p>
          <p className="hero-line">
            At 4 requests per second, continuous batching with a paged KV cache served <b className="num">{f2(at4('m5_full'))}</b> requests
            per second within the latency target. Static batching served <b className="num">{f2(at4('m2_static'))}</b>. The naive server
            served <b className="num">{f2(at4('m0_naive'))}</b>.
          </p>
        </Reveal>
        <Reveal delay={0.75} y={22}>
          <LineChart
            title="Goodput against offered load"
            sub={`Requests per second that finish and meet the SLO (first token under ${data.meta.slo.ttft_s} s, ${data.meta.slo.tpot_s * 1000} ms per token). Workload B, median of 3 seeds.`}
            tag="Measured"
            series={seriesFor(data, 'goodput')}
            xs={data.load.rates}
            xFormat={(v) => `${v}`}
            yFormat={(v) => f2(v)}
            xLabel="Offered load, requests / s"
            height={380}
            readoutFormat={(k, p) => `${f2(p.y)} req/s${p.min !== p.max ? `  (${f2(p.min)} to ${f2(p.max)})` : ''}`}
            ariaLabel="Line chart of goodput against offered load for four systems."
          />
          <p className="hero-note" style={{ marginTop: '1.4rem' }}>
            CPU only, fp32, one machine. Absolute numbers are far below any GPU system, and batching gains are smaller than GPU papers
            report because a CPU runs out of compute before it runs out of memory bandwidth. Naive was measured up to 4 requests per
            second; past that it is hopelessly saturated.
          </p>
        </Reveal>
      </div>
    </section>
  )
}
