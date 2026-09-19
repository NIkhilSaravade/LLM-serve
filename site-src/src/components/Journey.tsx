import Reveal from './Reveal'
import Section from './Section'
import { data } from '../data'
import { f0, f1 } from '../lib/format'

interface Step { id: string; title: string; built: string; result: string }

export default function Journey() {
  const m = data.milestones
  const o = data.overload
  const f = data.facts
  const steps: Step[] = [
    { id: 'M0', title: 'Baseline', built: 'Recompute the whole sequence for every token, one request at a time. Deliberately the dumbest thing that works, so every later gain is measured against a real floor.', result: `${f1(m.naive_tok_s)} tok/s` },
    { id: 'M1', title: 'Own KV cache', built: 'A GPT-2 forward pass and a cache written from scratch. Keys and values are stored instead of recomputed.', result: `${f1(m.kv_tok_s)} tok/s, ${f1(m.kv_speedup)}x the baseline` },
    { id: 'M2', title: 'Static batching', built: 'A batch dimension, padding, and per-row positions and masks. Built in order to prove it wastes slots.', result: `${f0(m.static16_tok_s)} tok/s at batch 16, slots idle ${f0((1 - m.sat_static_util) * 100)}% of the time under load` },
    { id: 'M3', title: 'Continuous batching', built: 'Iteration-level scheduling: a freed slot is refilled on the next step. Streaming responses with a UTF-8-safe detokeniser.', result: `${f0(m.sat_cont_tok_s)} against ${f0(m.sat_static_tok_s)} tok/s in a saturating burst` },
    { id: 'M4', title: 'Paged KV cache', built: 'A block manager, block tables, and attention that gathers non-adjacent blocks. Memory tracks tokens generated, not the maximum.', result: `${f1(data.m4_burst.paged_speedup_at_128)}x throughput when memory is scarce` },
    { id: 'M5', title: 'Preemption and admission control', built: 'Evict-and-recompute, a starvation guard, and refusal at the front door instead of an unbounded queue.', result: `${f0(o.completed_at_max)} completed and ${f0(o.rejected_at_max)} shed at ${o.max_rate} requests / s, nothing stuck` },
    { id: 'M6', title: 'Benchmarks', built: 'An open-loop Go load generator, one script that reproduces every number, and the charts on this page.', result: `${data.meta.runs} runs, ${data.meta.seeds} seeds each, raw data committed` },
    { id: '+', title: 'Operations', built: 'Prometheus metrics, readiness, a Grafana dashboard, alert rules with runbooks, a hardened container, Kubernetes manifests, CI.', result: `${f.alert_rules} alerts, ${f.dashboard_panels} panels, ${f.k8s_manifests} manifests` },
  ]
  return (
    <Section
      id="journey"
      title="How it was built, in order"
      intro="One milestone at a time, each ending with a passing golden test and a number written down before the next began."
    >
      <ol className="timeline">
        {steps.map((s, i) => (
          <li key={s.id}>
            <Reveal delay={Math.min(i * 0.03, 0.15)} className="tl-row">
              <span className="tl-id num" aria-hidden="true">{s.id}</span>
              <div>
                <h3>{s.title}</h3>
                <p className="body">{s.built}</p>
                <p className="tl-result num">{s.result}</p>
              </div>
            </Reveal>
          </li>
        ))}
      </ol>
      <p className="small hint">Milestone numbers use different workloads and conditions, so read each line on its own; the ablation above is the like-for-like comparison.</p>
    </Section>
  )
}
