import Reveal from './Reveal'
import Section from './Section'
import { data } from '../data'
import { repoFile } from '../config'
import type { LengthSpec, WorkloadKey } from '../types'

const spec = (v: LengthSpec): string => (v[0] === 'fixed' ? `${v[1]} fixed` : `median ${v[1]}, sigma ${v[2]}, clipped to ${v[3]} to ${v[4]}`)

const LIMITS: [string, string][] = [
  ['CPU only, fp32.', 'Absolute numbers are far below any GPU system, and batching gains are smaller than GPU papers report, because a CPU hits its compute limit before its memory-bandwidth limit.'],
  ['Paged attention gathers into a temporary buffer.', 'A production system uses a fused kernel that walks the block table inside attention. Here every layer of every step copies the needed blocks first.'],
  ['Batches are padded, not ragged.', 'Attention width spent on padding is wasted compute. It was measured, not hidden.'],
  ['GPT-2 only.', 'No grouped-query attention, no RoPE, no quantisation.'],
  ['Prefill is not chunked.', 'A long prompt stalls every running request, as the stall chart shows.'],
  ['Preemption recomputes.', 'Evicted requests are recomputed rather than swapped to host memory.'],
  ['One process, one machine.', 'The load generator and the server share one CPU.'],
  ['Scaled-down workloads and short runs.', 'Lengths are about a third of the original methodology, and each run is 60 to 90 requests, compensated by repeating with several seeds.'],
  ['The machine drifts.', 'This desktop was about twice as slow hours after the benchmark. Numbers are compared within a session, never across days.'],
  ['Operations are only partly proven.', 'The Kubernetes manifests have not been applied to a live cluster and no alert has fired for real.'],
]

export function Method() {
  const M = data.meta
  const cpu = (M.machine.cpu ?? '').replace(/\s+/g, ' ').trim()
  return (
    <Section
      id="methodology"
      title="How it was measured"
      intro="Load comes from a Go generator that sends open-loop Poisson arrivals: each request is sent at its scheduled time whether or not earlier ones have finished, so a slow server builds a queue exactly as it would in production. Time to first token is measured from the scheduled arrival, so the generator cannot hide server latency."
    >
      <div className="split">
        <Reveal className="prose">
          <p className="body"><b className="ink">Goodput</b> is requests per second that finish and meet both targets: first token within {M.slo.ttft_s} s and under {M.slo.tpot_s * 1000} ms per token afterwards. Rejected and unfinished requests count against it, so it cannot be inflated by letting latency explode. The targets were set before measuring.</p>
          <p className="body"><b className="ink">Runs.</b> {M.runs} runs in total: a 30-second arrival window plus 20 seconds to drain, every configuration repeated with {M.seeds} seeds (sweeps 2). A discarded warmup precedes each. Every variant uses {M.threads} torch threads and the same admission cap of {M.queue_cap} queued requests.</p>
          <p className="body"><b className="ink">The static baseline is generous.</b> Finished rows leave the compute and tokens stream as produced, which a naive server would not do. The gain over it is conservative.</p>
          <p className="small">Machine: {cpu || 'not recorded'}, {M.machine.logical_cores} logical cores, {M.machine.ram_gib ? `${M.machine.ram_gib} GiB, ` : ''}torch {M.machine.torch}.</p>
        </Reveal>
        <Reveal delay={0.08}>
          <h3 className="table-h">Workloads</h3>
          <div className="tscroll">
            <table className="data">
              <thead><tr><th scope="col">Workload</th><th scope="col">Prompt tokens</th><th scope="col">Output tokens</th><th scope="col" className="r">Offered</th></tr></thead>
              <tbody>
                {(Object.keys(M.workloads) as WorkloadKey[]).map((k) => (
                  <tr key={k}><th scope="row">{k}</th><td>{spec(M.workloads[k].prompt)}</td><td>{spec(M.workloads[k].output)}</td><td className="r num">{M.ablation_rates[k]} req/s</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small hint">Prompts are random token ids and every request ignores the end-of-text token, so output length is exactly the sampled value. Output-length variance is the largest lever on the result, which is why all three are published, least flattering first.</p>
        </Reveal>
      </div>
    </Section>
  )
}

export function Limitations() {
  return (
    <Section id="limitations" title="Limitations" intro={<>Stated plainly, and not tucked away. Every <code>LIMITATION</code> comment in the engine code is listed underneath.</>}>
      <Reveal>
        <ul className="limits">{LIMITS.map(([h, t]) => <li key={h}><b>{h}</b> {t}</li>)}</ul>
      </Reveal>
      <Reveal delay={0.05} className="gap-top">
        <h3 className="table-h">From the code</h3>
        <ul className="limits">
          {data.limitations.map((l, i) => {
            const href = repoFile(`engine/${l.file}`)
            return <li key={i}>{href ? <a href={href} target="_blank" rel="noopener noreferrer"><code>{l.file}</code></a> : <code>{l.file}</code>} {l.text}</li>
          })}
        </ul>
      </Reveal>
    </Section>
  )
}

export function Reproduce() {
  const f = data.facts
  const loc = f.loc
  const total = loc.engine_python + loc.tests_python + loc.scripts + loc.load_generator_go + loc.site_typescript
  const n = (v: number) => v.toLocaleString('en-US')
  return (
    <Section id="reproduce" title="Reproduce every number" intro={`The raw per-request data for all ${data.meta.runs} runs is committed next to the code, and this page is generated from it: nothing here is typed by hand. The repository also holds the build log with what broke and why, and an operations guide covering SLOs, alerts and runbooks.`}>
      <div className="split wide-left">
        <Reveal>
          <div className="codeblock" aria-label="Commands">
            <div><span className="c"># tests, including the golden ones</span></div>
            <div>make test</div>
            <div><span className="c"># about two hours, writes results/bench/</span></div>
            <div>make bench</div>
            <div><span className="c"># regenerates this page&rsquo;s data and builds it</span></div>
            <div>make site</div>
          </div>
        </Reveal>
        <Reveal delay={0.08}>
          <h3 className="table-h">What is in the repository</h3>
          <table className="data compact">
            <tbody>
              <tr><th scope="row">Engine (Python)</th><td className="r num">{n(loc.engine_python)} lines</td></tr>
              <tr><th scope="row">Tests (Python)</th><td className="r num">{n(loc.tests_python)} lines, {f.tests ?? '?'} tests</td></tr>
              <tr><th scope="row">Load generator (Go)</th><td className="r num">{n(loc.load_generator_go)} lines</td></tr>
              <tr><th scope="row">Scripts and benchmarks</th><td className="r num">{n(loc.scripts)} lines</td></tr>
              <tr><th scope="row">This page (TypeScript)</th><td className="r num">{n(loc.site_typescript)} lines</td></tr>
              <tr><th scope="row">Deployment</th><td className="r num">{f.k8s_manifests} manifests, {f.alert_rules} alerts</td></tr>
              <tr><th scope="row">Total code</th><td className="r num">{n(total)} lines</td></tr>
            </tbody>
          </table>
        </Reveal>
      </div>
    </Section>
  )
}
