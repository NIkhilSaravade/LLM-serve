import { ArrowRight, CircleAlert, CircleCheck } from 'lucide-react'
import Reveal from './Reveal'
import Section, { Sub } from './Section'
import { data } from '../data'
import verificationRaw from '../content/verification.json'
import type { VerificationItem } from '../types'

const verification = verificationRaw as VerificationItem[]

const SLO: { sli: string; target: string; why: string }[] = [
  { sli: 'Time to first token', target: '99% of requests under 2 s', why: 'What a user feels as "did it hang".' },
  { sli: 'Time per output token', target: 'p99 under 200 ms', why: 'Reading speed.' },
  { sli: 'Admission', target: 'under 5% answered 429', why: 'Sustained rejection means under-provisioned, not "working as designed".' },
  { sli: 'Availability', target: '99.9% scrapable with a live scheduler thread', why: 'A process that is up but serving nothing must page.' },
]

export default function Operations() {
  const f = data.facts
  const ok = verification.filter((v) => v.status === 'verified')
  const no = verification.filter((v) => v.status === 'not-verified')
  return (
    <Section
      id="operations"
      title="How it is operated"
      intro="A model server is only useful if someone can run it. The engine ships as a hardened container with metrics, dashboards, alerts and runbooks, and the page you are reading is built and deployed by the same pipeline."
    >
      <Reveal>
        <ol className="flow" aria-label="From commit to alert">
          <li><b>Commit</b><span>golden tests, lint, generated files current, Go vet, manifests render</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li><b>Image</b><span>non-root, weights baked in, runs offline, tag = model version</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li><b>Rollout</b><span>no downtime, ready only once the model is warm, one-command rollback</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li className="gate"><b>Watch</b><span>{f.dashboard_panels} panels and {f.alert_rules} alerts, each with a runbook</span></li>
        </ol>
      </Reveal>

      <div className="split gap-top">
        <Reveal className="prose">
          <h3>What is instrumented</h3>
          <p className="body">
            Prometheus metrics for request outcomes, time to first token, time per token and end-to-end latency as histograms, queue depth,
            running batch, KV blocks in use, preemptions, and whether the scheduler thread is alive. Readiness is separate from liveness. Every
            request has an id, echoed back and written to a JSON log line.
          </p>
          <p className="body">
            The {f.alert_rules} alerts include a multi-window error-budget burn-rate alert. They live in one source file: the Kubernetes rule
            resource and the Grafana dashboard are generated from code, and a test fails if any metric they query is missing from the live output.
          </p>
          <p className="body">
            HTTP 429 is deliberate load shedding, so it is excluded from the latency indicators and tracked by its own.
          </p>
        </Reveal>
        <Reveal delay={0.08}>
          <h3 className="table-h">Service level objectives</h3>
          <div className="tscroll">
            <table className="data">
              <thead><tr><th scope="col">Indicator</th><th scope="col">Objective</th></tr></thead>
              <tbody>
                {SLO.map((s) => (
                  <tr key={s.sli}><th scope="row">{s.sli}<span className="small block">{s.why}</span></th><td>{s.target}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      </div>

      <Sub title="What has been verified, and what has not">
        Saying plainly what was not proven is part of the work. Everything below is written down in the repository&rsquo;s operations guide.
      </Sub>
      <div className="split">
        <Reveal>
          <ul className="verify ok" aria-label="Verified">
            {ok.map((v) => (
              <li key={v.claim}>
                <CircleCheck size={18} aria-hidden="true" />
                <div><b>{v.claim}</b><span className="small block">{v.how}</span></div>
                <span className="sr-only">Verified</span>
              </li>
            ))}
          </ul>
        </Reveal>
        <Reveal delay={0.08}>
          <ul className="verify no" aria-label="Not verified">
            {no.map((v) => (
              <li key={v.claim}>
                <CircleAlert size={18} aria-hidden="true" />
                <div><b>{v.claim}</b><span className="small block">{v.how}</span></div>
                <span className="sr-only">Not verified</span>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </Section>
  )
}
