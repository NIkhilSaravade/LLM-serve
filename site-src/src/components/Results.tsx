import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import LineChart, { type Series } from './LineChart'
import Reveal, { EASE_OUT } from './Reveal'
import Section from './Section'
import { data } from '../data'
import type { WorkloadKey } from '../types'
import { f0, f1, f2, need } from '../lib/format'
import { loadSeries } from '../lib/series'

const WL: Record<WorkloadKey, { name: string; note: string }> = {
  A: { name: 'A · uniform', note: 'Every request is 64 tokens in and 64 out. The near-worst case for continuous batching, so it comes first.' },
  B: { name: 'B · realistic', note: 'Lognormal lengths. The main result.' },
  C: { name: 'C · high variance', note: 'Heavy-tailed output lengths. The best case for continuous batching, labelled as such.' },
}

function Ablation() {
  const [wl, setWl] = useState<WorkloadKey>('A')
  const [open, setOpen] = useState<string | null>(null)
  const reduce = useReducedMotion()
  const block = data.ablation[wl]
  const max = Math.max(...block.rows.map((r) => r.goodput?.max ?? 0)) * 1.05
  const opened = block.rows.find((r) => r.key === open)

  return (
    <div>
      <div className="chart-top top-0">
        <div>
          <div className="chart-title">Ablation: what each mechanism contributed</div>
          <div className="chart-sub">
            Offered load {block.rate} requests / s, KV budget {data.meta.kv_budget_mib} MiB, median of {data.meta.seeds} seeds with min to max. {WL[wl].note}
          </div>
        </div>
        <div className="seg" role="tablist" aria-label="Workload">
          {(Object.keys(WL) as WorkloadKey[]).map((k) => (
            <button key={k} role="tab" aria-selected={wl === k} onClick={() => { setWl(k); setOpen(null) }}>{WL[k].name}</button>
          ))}
        </div>
      </div>
      <div className="tscroll">
        <table className="data" key={wl}>
          <thead>
            <tr>
              <th scope="col">Configuration</th><th scope="col">KV cache</th><th scope="col">Batching</th><th scope="col">Paged</th>
              <th scope="col" style={{ minWidth: 230 }}>Goodput at target, req / s</th>
              <th scope="col" className="r">p99 first token</th><th scope="col" className="r">KV efficiency</th>
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r, i) => {
              const hero = r.key === 'm4_full' || r.key === 'm5_full'
              const exp = open === r.key
              const g = r.goodput
              return (
                <motion.tr
                  key={r.key} className={`arow ${hero ? 'hero-row' : ''} ${exp ? 'open' : ''}`}
                  onClick={() => setOpen(exp ? null : r.key)}
                  initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: i * 0.035, ease: EASE_OUT }}
                >
                  <th scope="row"><button className="row-btn" aria-expanded={exp}>{r.label}</button></th>
                  <td>{r.kv}</td><td>{r.batching}</td><td>{r.paging}</td>
                  <td>
                    {g ? (
                      <div className="gcell">
                        <div className="gbar" aria-hidden="true">
                          <motion.i style={{ width: `${(g.median / max) * 100}%` }} initial={reduce ? false : { scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 0.9, delay: 0.1 + i * 0.05, ease: EASE_OUT }} />
                          <b style={{ left: `${(g.min / max) * 100}%` }} /><b style={{ left: `${(g.max / max) * 100}%` }} />
                        </div>
                        <span className="num nowrap"><span className="ink">{f2(g.median)}</span> <span className="small">({f2(g.min)} to {f2(g.max)})</span></span>
                      </div>
                    ) : '-'}
                  </td>
                  <td className="r num">{r.ttft_p99 ? `${f2(r.ttft_p99.median)} s` : '-'}</td>
                  <td className="r num">{r.kv === 'none' || !r.kv_eff ? '-' : f2(r.kv_eff.median)}</td>
                </motion.tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="small hint" aria-live="polite">
        {opened
          ? <><b className="ink">{opened.label}.</b> {opened.adds}</>
          : 'Select a row to see what it adds over the one above. Compare “Continuous batching” with “Continuous + paged” to isolate paging, and “Static batching” with “Continuous batching” to isolate the scheduler.'}
      </p>
    </div>
  )
}

type LoadMetric = 'goodput' | 'ttft_p99' | 'throughput'
const LOAD_META: Record<LoadMetric, { title: string; sub: string; y: (v: number) => string; log?: boolean; label: string }> = {
  goodput: { label: 'Goodput', title: 'Goodput against offered load', sub: 'Requests per second that finish and meet the target.', y: f2 },
  ttft_p99: { label: 'p99 first token', title: 'p99 time to first token against offered load', sub: 'Log scale. The dashed line is the 2 s target.', y: (v) => (v >= 10 ? f0(v) : v >= 1 ? f1(v) : f2(v)), log: true },
  throughput: { label: 'Throughput', title: 'Throughput against offered load', sub: 'Output tokens per second, all requests.', y: f0 },
}

export function Results() {
  return (
    <Section
      id="results"
      title="What each mechanism contributed"
      intro="One table isolates each idea. Every row is a configuration the code can run, measured with the same load generator, the same seeds and the same latency target."
    >
      <Reveal><Ablation /></Reveal>
    </Section>
  )
}

export function Load() {
  const [metric, setMetric] = useState<LoadMetric>('goodput')
  const M = LOAD_META[metric]
  const b = data.budget
  const o = data.overload
  const budgetSeries: Series[] = (['contiguous', 'paged'] as const).map((k) => ({
    key: k,
    label: k === 'contiguous' ? 'Contiguous slots' : 'Paged blocks',
    color: k === 'contiguous' ? 'var(--s-cont)' : 'var(--s-paged)',
    points: b.series[k].flatMap((p) => (p.goodput ? [{ x: p.mib, y: p.goodput.median, min: p.goodput.min, max: p.goodput.max }] : [])),
  }))
  // First budget at which contiguous slots match paged blocks (within 2 percent).
  const tie = b.budgets.find((_m, i) => {
    const c = b.series.contiguous[i]?.goodput
    const p = b.series.paged[i]?.goodput
    return c && p && c.median >= p.median * 0.98
  })
  const first = b.budgets[0]

  return (
    <Section
      id="load"
      title="Under load, and past it"
      intro={
        <>
          Goodput rises with offered load until the server saturates, then falls as requests start missing the target. Continuous
          batching saturates later and degrades more gently. Past saturation the full system stays up: p99 first-token latency goes from{' '}
          {f2(o.p99_ttft_at_4)} s at 4 requests per second to {f1(o.p99_ttft_at_max)} s at {o.max_rate}, and the queue cap turns away a
          median of {f0(o.rejected_at_max)} requests per run instead of letting the queue grow without bound.
        </>
      }
    >
      <Reveal>
        <LineChart
          key={metric}
          title={M.title} sub={M.sub} tag="Measured"
          series={loadSeries(data, metric)} xs={data.load.rates} xFormat={String} yFormat={M.y}
          xLabel="Offered load, requests / s" logY={!!M.log} yMin={0.05}
          refLine={metric === 'ttft_p99' ? { y: 2, label: 'target 2 s' } : undefined}
          ariaLabel={`${M.title}, four systems.`}
          readoutFormat={(_k, p) => `${M.y(p.y)}${metric === 'ttft_p99' ? ' s' : ''}`}
          extra={
            <div className="seg mb-3" role="group" aria-label="Metric">
              {(Object.keys(LOAD_META) as LoadMetric[]).map((k) => (
                <button key={k} aria-pressed={metric === k} onClick={() => setMetric(k)}>{LOAD_META[k].label}</button>
              ))}
            </div>
          }
        />
      </Reveal>

      <div className="split wide-left gap-top">
        <Reveal>
          <LineChart
            title="Goodput against KV memory budget" tag="Measured" xMode="point"
            sub="3 requests per second, workload B. Contiguous slots reserve the full context, so scarce memory strangles them."
            series={budgetSeries} xs={b.budgets} xFormat={String} yFormat={f2} xLabel="KV budget, MiB" height={320}
            annotations={tie ? [{ x: tie, text: 'from here they tie' }] : []}
            ariaLabel="Goodput against KV memory budget for contiguous slots and paged blocks."
            readoutFormat={(_k, p) => `${f2(p.y)} req/s`}
          />
        </Reveal>
        <Reveal delay={0.1} className="prose aside">
          <p className="body">
            Paging does not make the server faster. It makes the same memory go further. At {first} MiB there is room for a single
            full-length slot ({f2(need(b.series.contiguous[0]?.goodput ?? null, 'contiguous 128').median)} req/s), so requests queue behind
            one another, while the paged server keeps serving ({f2(need(b.series.paged[0]?.goodput ?? null, 'paged 128').median)}). From{' '}
            {tie} MiB up, memory is no longer the constraint and the two are the same.
          </p>
        </Reveal>
      </div>
    </Section>
  )
}
