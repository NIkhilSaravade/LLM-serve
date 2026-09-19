import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import LineChart from './LineChart'
import Reveal, { EASE_OUT } from './Reveal'
import { data } from '../data'
import { f2, need } from '../lib/format'
import { goodputAt, loadSeries } from '../lib/series'
import { problems } from './Problems'

/** The one authored moment: the headline rises out of a clip, line by line. */
function Line({ children, i }: { children: ReactNode; i: number }) {
  const reduce = useReducedMotion()
  return (
    <span className="clip">
      <motion.span
        initial={reduce ? false : { y: '108%' }}
        animate={{ y: 0 }}
        transition={{ duration: 1, delay: 0.1 + i * 0.12, ease: EASE_OUT }}
      >
        {children}
      </motion.span>
    </span>
  )
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="brief-row">
      <dt>{k}</dt>
      <dd>{children}</dd>
    </div>
  )
}

export default function Hero() {
  const B = data.ablation.B.rows
  const row = (key: string) => B.find((r) => r.key === key)
  const stat = need(row('m2_static')?.goodput ?? null, 'static goodput').median
  const cont = need(row('m3_continuous')?.goodput ?? null, 'continuous goodput').median
  const tight = data.budget.series
  const at4 = (k: 'm0_naive' | 'm2_static' | 'm5_full') => goodputAt(data, k, 4)
  const f = data.facts

  return (
    <section id="overview" className="hero" aria-labelledby="overview-h">
      <div className="hero-grid" aria-hidden="true" />
      <h1 id="overview-h">
        <Line i={0}>Serving LLMs is</Line>
        <Line i={1}>a <em>scheduling</em></Line>
        <Line i={2}>problem.</Line>
      </h1>

      <Reveal delay={0.55} className="hero-sub">
        <p className="lede">
          A from-scratch GPT-2 inference server that measures what continuous batching and a paged KV cache really buy on a CPU,
          including where they do not.
        </p>
      </Reveal>

      <Reveal delay={0.7} className="brief">
        <h2 className="brief-title">The whole page in thirty seconds</h2>
        <dl>
          <Row k="What it is">
            An LLM inference server whose scheduler and KV-cache memory manager are written from scratch. GPT-2 is only the workload.
            Built to be measured, then operated: containers, metrics, dashboards, alerts, Kubernetes, CI.
          </Row>
          <Row k="What it found">
            Continuous batching serves <b className="num">{(cont / stat).toFixed(1)}x</b> the goodput of static batching
            ({f2(cont)} against {f2(stat)} requests per second within the latency target). A paged KV cache does not add throughput
            by itself: it matters when KV memory is scarce, where at {data.budget.budgets[0]} MiB it serves{' '}
            <b className="num">{f2(need(tight.paged[0]?.goodput ?? null, 'paged 128').median)}</b> against{' '}
            <b className="num">{f2(need(tight.contiguous[0]?.goodput ?? null, 'contig 128').median)}</b>.
          </Row>
          <Row k="How it is proven">
            Every configuration must reproduce the Hugging Face reference <b>token for token</b>: {f.tests ?? '?'} tests, no tolerance.
            Performance comes from <b className="num">{data.meta.runs}</b> open-loop load runs with {data.meta.seeds} seeds each, and
            the raw data is committed.
          </Row>
          <Row k="What went wrong">
            {problems.length} real problems, from a benchmark that lied to a test that could not fail. Each one is written up with the wrong
            assumption behind it. <a href="#problems">Read the log</a>.
          </Row>
          <Row k="What is not proven">
            The Kubernetes manifests have never met a live cluster and no alert has fired for real.{' '}
            <a href="#operations">See the verification matrix</a>.
          </Row>
        </dl>
      </Reveal>

      <Reveal delay={0.1} y={22} className="hero-chart">
        <LineChart
          title="Goodput against offered load"
          sub={`Requests per second that finish and meet the target (first token under ${data.meta.slo.ttft_s} s, under ${data.meta.slo.tpot_s * 1000} ms per token after). Workload B, median of ${data.meta.seeds} seeds.`}
          tag="Measured"
          series={loadSeries(data, 'goodput')}
          xs={data.load.rates}
          xFormat={String}
          yFormat={f2}
          xLabel="Offered load, requests / s"
          height={380}
          readoutFormat={(_k, p) => `${f2(p.y)} req/s${p.min !== p.max && p.min != null && p.max != null ? `  (${f2(p.min)} to ${f2(p.max)})` : ''}`}
          ariaLabel="Line chart of goodput against offered load for four systems. Continuous batching with a paged KV cache peaks highest."
        />
        <p className="note">
          At 4 requests per second, continuous batching with a paged KV cache served <b className="num">{f2(at4('m5_full'))}</b> requests per
          second within the target. Static batching served <b className="num">{f2(at4('m2_static'))}</b>. The naive server served{' '}
          <b className="num">{f2(at4('m0_naive'))}</b>. CPU only and one machine: absolute numbers are far below any GPU system, and
          batching gains are smaller than GPU papers report, because a CPU runs out of compute before it runs out of memory bandwidth.
        </p>
      </Reveal>
    </section>
  )
}
