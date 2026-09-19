import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import LineChart from './LineChart.jsx'
import Reveal from './Reveal.jsx'
import { SYSTEMS, seriesFor } from './Hero.jsx'
import { f0, f1, f2 } from '../lib.js'

const EASE = [0.16, 1, 0.3, 1]
const WL = {
  A: { name: 'A · uniform', note: 'Every request is 64 tokens in, 64 out. The near-worst case for continuous batching, so it comes first.' },
  B: { name: 'B · realistic', note: 'Lognormal lengths. The main result.' },
  C: { name: 'C · high variance', note: 'Heavy-tailed output lengths. The best case for continuous batching, labelled as such.' },
}

function Ablation({ data }) {
  const [wl, setWl] = useState('A')
  const [open, setOpen] = useState(null)
  const reduce = useReducedMotion()
  const block = data.ablation[wl]
  const max = Math.max(...block.rows.map((r) => r.goodput.max)) * 1.05
  return (
    <div>
      <div className="chart-top" style={{ paddingTop: 0 }}>
        <div>
          <div className="chart-title">Ablation: what each mechanism contributed</div>
          <div className="chart-sub">Offered load {block.rate} requests / s, KV budget {data.meta.kv_budget_mib} MiB, median of 3 seeds with min to max. {WL[wl].note}</div>
        </div>
        <div className="seg" role="tablist" aria-label="Workload">
          {Object.keys(WL).map((k) => (
            <button key={k} role="tab" aria-selected={wl === k} onClick={() => { setWl(k); setOpen(null) }}>{WL[k].name}</button>
          ))}
        </div>
      </div>
      <div className="tscroll">
        <table className="data" key={wl}>
          <thead>
            <tr>
              <th>Configuration</th><th>KV cache</th><th>Batching</th><th>Paged</th>
              <th style={{ minWidth: 220 }}>Goodput at SLO, req / s</th><th className="r">p99 first token</th><th className="r">KV efficiency</th>
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r, i) => {
              const hero = r.key === 'm4_full' || r.key === 'm5_full'
              const exp = open === r.key
              return (
                <motion.tr
                  key={r.key} className={`arow ${hero ? 'hero-row' : ''}`} tabIndex={0} aria-expanded={exp}
                  onClick={() => setOpen(exp ? null : r.key)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(exp ? null : r.key) } }}
                  initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: i * 0.035, ease: EASE }}
                >
                  <td style={{ fontWeight: 500 }}>{r.label}</td>
                  <td>{r.kv}</td><td>{r.batching}</td><td>{r.paging}</td>
                  <td>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '.8rem', alignItems: 'center' }}>
                      <div className="gbar" aria-hidden="true">
                        <motion.i style={{ width: `${(r.goodput.median / max) * 100}%` }} initial={reduce ? false : { scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 0.9, delay: 0.1 + i * 0.05, ease: EASE }} />
                        <b style={{ left: `${(r.goodput.min / max) * 100}%` }} /><b style={{ left: `${(r.goodput.max / max) * 100}%` }} />
                      </div>
                      <span className="num" style={{ whiteSpace: 'nowrap' }}>
                        <span className="ink">{f2(r.goodput.median)}</span> <span className="small">({f2(r.goodput.min)} to {f2(r.goodput.max)})</span>
                      </span>
                    </div>
                  </td>
                  <td className="r num">{r.ttft_p99 ? `${f2(r.ttft_p99.median)} s` : '-'}</td>
                  <td className="r num">{r.kv === 'none' || !r.kv_eff ? '-' : f2(r.kv_eff.median)}</td>
                </motion.tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="small" style={{ marginTop: '1rem', minHeight: '2.6rem', maxWidth: '60ch' }} aria-live="polite">
        {open
          ? <><b className="ink" style={{ fontWeight: 500 }}>{block.rows.find((r) => r.key === open).label}.</b> {block.rows.find((r) => r.key === open).adds}</>
          : 'Select a row to see what it adds over the one above. Compare “Continuous batching” with “Continuous + paged” to isolate paging, and “Static batching” with “Continuous batching” to isolate the scheduler.'}
      </p>
    </div>
  )
}

export default function Results({ data }) {
  const [metric, setMetric] = useState('goodput')
  const M = {
    goodput: { label: 'Goodput', y: (v) => f2(v), title: 'Goodput against offered load', sub: 'Requests per second that finish and meet the SLO.' },
    ttft_p99: { label: 'p99 first token', y: (v) => (v >= 10 ? f0(v) : v >= 1 ? f1(v) : f2(v)), title: 'p99 time to first token against offered load', sub: 'Log scale. The dashed line is the 2 s target.', log: true },
    throughput: { label: 'Throughput', y: (v) => f0(v), title: 'Throughput against offered load', sub: 'Output tokens per second, all requests.' },
  }[metric]
  const b = data.budget
  const budgetSeries = [
    { key: 'contiguous', label: 'Contiguous slots', color: 'var(--s-cont)', points: b.series.contiguous.map((p) => ({ x: p.mib, y: p.goodput.median, min: p.goodput.min, max: p.goodput.max })) },
    { key: 'paged', label: 'Paged blocks', color: 'var(--s-paged)', points: b.series.paged.map((p) => ({ x: p.mib, y: p.goodput.median, min: p.goodput.min, max: p.goodput.max })) },
  ]
  const o = data.overload
  // First budget at which contiguous slots match paged blocks (within 2 percent).
  const tie = b.budgets.find((m, i) => b.series.contiguous[i].goodput.median >= b.series.paged[i].goodput.median * 0.98)
  return (
    <section id="results">
      <div className="wrap">
        <Reveal className="sec-head">
          <h2>The results, mechanism by mechanism</h2>
          <p className="body">
            One table isolates each idea. Every row is a configuration the code can run, measured with the same load generator, the same
            seeds and the same latency target.
          </p>
        </Reveal>
        <Reveal><Ablation data={data} /></Reveal>

        <div style={{ height: 'clamp(3rem, 6vw, 5rem)' }} />
        <Reveal className="sec-head">
          <h2>Under load</h2>
          <p className="body">
            Goodput rises with offered load until the server saturates, then falls as requests start missing the target. Continuous
            batching saturates later and degrades more gently. Past saturation the full system stays up: p99 first-token latency goes
            from {f2(o.p99_ttft_at_4)} s at 4 requests per second to {f1(o.p99_ttft_at_max)} s at {o.max_rate}, and the queue cap turns
            away a median of {f0(o.rejected_at_max)} requests per run instead of letting the queue grow without bound.
          </p>
        </Reveal>
        <Reveal>
          <LineChart
            key={metric}
            title={M.title} sub={M.sub} tag="Measured"
            series={seriesFor(data, metric)} xs={data.load.rates} xFormat={(v) => `${v}`} yFormat={M.y}
            xLabel="Offered load, requests / s" logY={!!M.log} yMin={0.05} refLine={metric === 'ttft_p99' ? { y: 2, label: 'target 2 s' } : undefined}
            ariaLabel={`${M.title}, four systems.`}
            readoutFormat={(k, p) => `${M.y(p.y)}${metric === 'ttft_p99' ? ' s' : ''}`}
            extra={
              <div className="seg" role="group" aria-label="Metric" style={{ marginBottom: '.9rem' }}>
                {Object.entries({ goodput: 'Goodput', ttft_p99: 'p99 first token', throughput: 'Throughput' }).map(([k, l]) => (
                  <button key={k} aria-pressed={metric === k} onClick={() => setMetric(k)}>{l}</button>
                ))}
              </div>
            }
          />
        </Reveal>

        <div style={{ height: 'clamp(3rem, 6vw, 5rem)' }} />
        <div className="split wide-left">
          <Reveal>
            <LineChart
              title="Goodput against KV memory budget" tag="Measured" xMode="point"
              sub="3 requests per second, workload B. Contiguous slots reserve the full context, so scarce memory strangles them."
              series={budgetSeries} xs={b.budgets} xFormat={(v) => `${v}`} yFormat={(v) => f2(v)} xLabel="KV budget, MiB" height={320}
              annotations={tie ? [{ x: tie, text: 'from here they tie' }] : []}
              ariaLabel="Goodput against KV memory budget for contiguous slots and paged blocks."
              readoutFormat={(k, p) => `${f2(p.y)} req/s`}
            />
          </Reveal>
          <Reveal delay={0.1} className="prose" style={{ alignSelf: 'start', paddingTop: '3.4rem' }}>
            <p className="body">
              Paging does not make the server faster. It makes the same memory go further. At {b.budgets[0]} MiB there is room for a single
              full-length slot, so contiguous requests queue behind one another while the paged server keeps serving. From {tie} MiB up,
              memory is no longer the constraint and the two are the same.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  )
}
