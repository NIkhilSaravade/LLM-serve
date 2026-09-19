import Reveal from './Reveal.jsx'
import { f1, f2 } from '../lib.js'

/** Every number below is read from data.json; the sentences are the honest reading of it. */
export default function Negatives({ data }) {
  const A = data.ablation.A.rows, B = data.ablation.B.rows
  const row = (rows, k) => rows.find((r) => r.key === k)
  const aBatch = ['m2_static', 'm3_continuous', 'm4_static_paged', 'm4_full', 'm5_full'].map((k) => row(A, k).goodput.median)
  const bCont = row(B, 'm3_continuous'), bPaged = row(B, 'm4_full')
  const bud = data.budget.series
  const tight = { c: bud.contiguous[0].goodput.median, p: bud.paged[0].goodput.median, mib: data.budget.budgets[0] }
  const mb = data.maxbatch
  const gain = Math.round(((mb[mb.length - 1].throughput.median - mb.find((r) => r.max_batch === 8).throughput.median) / mb.find((r) => r.max_batch === 8).throughput.median) * 100)
  const preempt = Math.max(...['m5_full'].map((k) => row(B, k).preemptions?.max ?? 0))
  const o = data.overload
  const items = [
    {
      h: 'On the uniform workload, the batching systems tie.',
      p: `At the load tested, static, continuous and both paged rows all reach ${Math.min(...aBatch) === Math.max(...aBatch) ? f2(aBatch[0]) : `${f2(Math.min(...aBatch))} to ${f2(Math.max(...aBatch))}`} requests per second on workload A. Static batching only loses on tail latency. That load is below everyone's capacity, so the table cannot show a difference the load never exposed.`,
    },
    {
      h: 'Paging did not change goodput at moderate memory.',
      p: `With ${data.meta.kv_budget_mib} MiB of KV memory, continuous batching reaches ${f2(bCont.goodput.median)} requests per second with contiguous slots and ${f2(bPaged.goodput.median)} with paged blocks. Paging improved p99 first-token latency (${f2(bCont.ttft_p99.median)} s to ${f2(bPaged.ttft_p99.median)} s) and memory efficiency (${f2(bCont.kv_eff.median)} to ${f2(bPaged.kv_eff.median)}). It converts into goodput only when memory is the constraint: ${f2(tight.p)} against ${f2(tight.c)} requests per second at ${tight.mib} MiB.`,
    },
    {
      h: 'Paging costs something when memory is plentiful.',
      p: `In a closed-loop burst with plenty of memory (1 and 2 GiB), the paged server was ${data.m4_burst.paged_slowdown_pct_min} to ${data.m4_burst.paged_slowdown_pct_max} percent slower than contiguous slots. Paged attention copies scattered blocks into a temporary buffer at every layer and every step, because a fused kernel is not possible here.`,
    },
    {
      h: 'Preemption barely fired.',
      p: `At this scale a sequence is a few hundred tokens against a KV pool measured in thousands, so optimistic admission almost never ran out of blocks (${preempt === 0 ? 'no evictions in any ablation run' : `at most ${f1(preempt)} evictions per run in the ablation`}, and at most one per run in the overload tests). It exists to make optimistic admission safe, and the tests prove it produces exact tokens when it does fire. It did not measurably improve throughput.`,
    },
    {
      h: 'Past saturation, latency degrades sharply.',
      p: `The full system holds p99 first-token latency at ${f2(o.p99_ttft_at_4)} s up to 4 requests per second, then ${f1(o.p99_ttft_at_max)} s at ${o.max_rate}. It stays bounded only because the queue cap sheds load; it does not become fast.`,
    },
    {
      h: 'The CPU stops scaling early.',
      p: `Going from a batch of 8 to 32 adds ${gain} percent throughput. This is the compute ceiling the project brief predicted, and the reason the gains here are smaller than GPU papers report.`,
    },
  ]
  return (
    <section id="negative-results">
      <div className="wrap">
        <Reveal className="sec-head">
          <h2>What did not go the way you would hope</h2>
          <p className="body">Published with the same weight as the wins. A number that only ever flatters is a number to distrust.</p>
        </Reveal>
        <div className="neg">
          {items.map((it, i) => (
            <Reveal key={it.h} className="neg-item" delay={Math.min(i * 0.04, 0.2)}>
              <h3>{it.h}</h3>
              <p>{it.p}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
