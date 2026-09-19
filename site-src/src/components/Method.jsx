import Reveal from './Reveal.jsx'

const spec = (v) => (v[0] === 'fixed' ? `${v[1]} fixed` : `median ${v[1]}, sigma ${v[2]}, clipped to ${v[3]} to ${v[4]}`)

const LIMITS = [
  ['CPU only, fp32.', 'Absolute numbers are far below any GPU system, and batching gains are smaller than GPU papers report, because a CPU hits its compute limit before its memory-bandwidth limit.'],
  ['Paged attention gathers into a temporary buffer.', 'A production system uses a fused kernel that walks the block table inside attention. Here every layer of every step copies the needed blocks first.'],
  ['Batches are padded, not ragged.', 'Attention width spent on padding is wasted compute. It was measured, not hidden.'],
  ['GPT-2 only.', 'No grouped-query attention, no RoPE, no quantisation.'],
  ['Prefill is not chunked.', 'A long prompt stalls every running request, as the stall chart shows.'],
  ['Preemption recomputes.', 'Evicted requests are recomputed rather than swapped to host memory.'],
  ['One process, one machine.', 'The load generator and the server share one CPU.'],
  ['Scaled-down workloads and short runs.', 'Lengths are about a third of the original methodology, and each run is 60 to 90 requests, compensated by repeating with 3 seeds. Sweeps use 2.'],
  ['The machine drifts.', 'This desktop was about twice as slow hours after the benchmark. Numbers are compared within a session, never across days.'],
]

export default function Method({ data }) {
  const M = data.meta
  const cpu = (M.machine.cpu || '').replace(/\s+/g, ' ').trim()
  return (
    <>
      <section id="methodology">
        <div className="wrap">
          <Reveal className="sec-head">
            <h2>How it was measured</h2>
            <p className="body">
              Load comes from a Go generator that sends open-loop Poisson arrivals: each request is sent at its scheduled time whether or not
              earlier ones have finished, so a slow server builds a queue exactly as it would in production. Time to first token is measured
              from the scheduled arrival, so the generator cannot hide server latency.
            </p>
          </Reveal>
          <div className="split">
            <Reveal className="prose">
              <h3 style={{ marginBottom: '.6rem' }}>Definitions</h3>
              <p className="body">
                <b className="ink" style={{ fontWeight: 500 }}>Goodput</b> is requests per second that finish and meet both targets: first
                token within {M.slo.ttft_s} s and under {M.slo.tpot_s * 1000} ms per token afterwards. Rejected and unfinished requests count
                against it, so it cannot be inflated by letting latency explode. The targets were set before measuring.
              </p>
              <p className="body">
                <b className="ink" style={{ fontWeight: 500 }}>Runs.</b> {M.runs} runs in total: a {30}-second arrival window plus {20} seconds to
                drain, every configuration repeated with 3 seeds (sweeps 2). A discarded warmup precedes each. Every variant uses {M.threads} torch
                threads and the same admission cap of {M.queue_cap} queued requests.
              </p>
              <p className="body">
                <b className="ink" style={{ fontWeight: 500 }}>Correctness.</b> Every configuration passes a golden test: greedy token ids identical
                to the Hugging Face reference, including batches where neighbours join and leave mid-generation and requests that were evicted and
                recomputed. Speed is irrelevant until that passes.
              </p>
              <p className="body">
                <b className="ink" style={{ fontWeight: 500 }}>The static baseline is generous.</b> Finished rows leave the compute and tokens
                stream as produced, which a naive server would not do. The gain over it is conservative.
              </p>
              <p className="small">Machine: {cpu || 'not recorded'}, {M.machine.logical_cores} logical cores, {M.machine.ram_gib ? `${M.machine.ram_gib} GiB, ` : ''}torch {M.machine.torch}.</p>
            </Reveal>
            <Reveal delay={0.08}>
              <h3 style={{ marginBottom: '.6rem' }}>Workloads</h3>
              <div className="tscroll">
                <table className="data">
                  <thead><tr><th>Workload</th><th>Prompt tokens</th><th>Output tokens</th><th className="r">Offered</th></tr></thead>
                  <tbody>
                    {Object.entries(M.workloads).map(([k, v]) => (
                      <tr key={k}>
                        <td style={{ fontWeight: 500 }}>{k}</td><td>{spec(v.prompt)}</td><td>{spec(v.output)}</td>
                        <td className="r num">{M.ablation_rates[k]} req/s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small" style={{ marginTop: '.9rem', maxWidth: '52ch' }}>
                Prompts are random token ids and every request ignores the end-of-text token, so output length is exactly the sampled value.
                Output-length variance is the largest lever on the result, which is why all three are published, least flattering first.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <section id="limitations">
        <div className="wrap">
          <Reveal className="sec-head">
            <h2>Limitations</h2>
            <p className="body">Stated plainly, and not tucked away. Every <code>LIMITATION</code> comment in the engine code is listed underneath.</p>
          </Reveal>
          <Reveal>
            <ul className="limits">
              {LIMITS.map(([h, t]) => <li key={h}><b>{h}</b> {t}</li>)}
            </ul>
          </Reveal>
          <Reveal delay={0.05} style={{ marginTop: '2.2rem' }}>
            <h3 style={{ marginBottom: '.5rem' }}>From the code</h3>
            <ul className="limits">
              {data.limitations.map((l, i) => <li key={i}><code>{l.file}</code> {l.text}</li>)}
            </ul>
          </Reveal>
        </div>
      </section>

      <section id="reproduce">
        <div className="wrap split wide-left">
          <Reveal>
            <h2 style={{ marginBottom: '1.2rem' }}>Reproduce every number</h2>
            <p className="body">
              The raw per-request data for all {M.runs} runs is committed next to the code. This page is generated from it: nothing here is
              typed by hand. The repository also holds the build log with what broke and why, and an operations guide covering SLOs, alerts and runbooks.
            </p>
          </Reveal>
          <Reveal delay={0.08} style={{ alignSelf: 'end' }}>
            <div className="codeblock">
              <div><span className="c"># tests, including the golden ones</span></div>
              <div>make test</div>
              <div><span className="c"># about two hours, writes results/bench/</span></div>
              <div>make bench</div>
              <div><span className="c"># regenerates this page from the raw data</span></div>
              <div>make results</div>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  )
}
