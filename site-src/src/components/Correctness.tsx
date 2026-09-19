import { ArrowRight, Check, X } from 'lucide-react'
import Reveal from './Reveal'
import Section, { Sub } from './Section'
import { data } from '../data'
import bugsRaw from '../content/bugs.json'

interface Bug { bug: string; detail: string; caught_by: string; first_run: 'caught' | 'missed'; source: string }
const bugs = bugsRaw as Bug[]

const COVERS: { file: string; covers: string }[] = [
  { file: 'test_golden.py', covers: 'The naive and the own-cache paths equal the reference; static and continuous engines equal it for every fixture; batches of mixed length; neighbours joining and leaving mid-generation; streamed text equals decoded tokens, including emoji and CJK.' },
  { file: 'test_paged.py', covers: 'Every fixture at block sizes 4 and 16; a shuffled free list so blocks are not adjacent; the block-boundary off-by-one; and a bit-exact comparison of every K and V, all 12 layers, against a contiguous prefill.' },
  { file: 'test_preemption.py', covers: 'Evictions are forced (and asserted) yet tokens stay exact; each token reaches the client exactly once across an eviction; no livelock under 2x over-commit; queue cap, oversize and cancellation behaviour.' },
  { file: 'test_ops.py', covers: 'Health, readiness and version; Prometheus counters and histograms after a request; every metric a dashboard or alert uses exists in the live output; generated files are not stale.' },
]

export default function Correctness() {
  const n = data.facts.tests
  return (
    <Section
      id="correctness"
      title="How it is known to be right"
      intro={
        <>
          Every bug in a system like this produces fluent, grammatical, plausible text. It throws no exception and returns no wrong number,
          so it cannot be judged by looking. Correctness has to be mechanical.
        </>
      }
    >
      <Reveal>
        <ol className="flow" aria-label="The golden test">
          <li><b>Hugging Face reference</b><span>greedy decoding, run once. The only place <code>generate()</code> is allowed.</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li><b>{data.facts.golden_fixtures} committed fixtures</b><span>token ids for block boundaries, long prompts, long outputs and mixed batches</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li><b>Every configuration</b><span>naive, cached, static, continuous, paged, evicted, alone or in a batch</span></li>
          <li className="arrow" aria-hidden="true"><ArrowRight size={18} /></li>
          <li className="gate"><b>Exact token-id equality</b><span>no tolerance, and never decoded text</span></li>
        </ol>
      </Reveal>

      <div className="split gap-top">
        <Reveal className="prose">
          <p className="body">
            Greedy decoding always picks the highest-probability token, so it is fully deterministic: two correct implementations must
            produce the same integers in the same order. Sampling cannot be used as a signal, because the order of random draws changes when
            batching changes.
          </p>
          <p className="body">
            The invariant that matters most: <b className="ink">a request&rsquo;s output must not depend on what else was in the batch.</b> It is
            tested alone, in a batch of eight with wildly different neighbours, and with neighbours that join and leave halfway through.
            {n != null && <> {n} tests enforce this and the rest of the contract.</>}
          </p>
        </Reveal>
        <Reveal delay={0.08}>
          <table className="data">
            <thead><tr><th scope="col">Suite</th><th scope="col">What it pins down</th></tr></thead>
            <tbody>
              {COVERS.map((c) => (
                <tr key={c.file}><th scope="row"><code>{c.file}</code></th><td>{c.covers}</td></tr>
              ))}
            </tbody>
          </table>
        </Reveal>
      </div>

      <Sub title="Do the tests catch the bugs they exist for?">
        The golden tests never failed against the engine during the build. A test that has never failed proves little, so bugs were injected on
        purpose and the relevant tests run. One got through.
      </Sub>
      <Reveal>
        <div className="tscroll">
          <table className="data bug">
            <thead><tr><th scope="col">Injected bug</th><th scope="col">Caught by</th><th scope="col">First run</th></tr></thead>
            <tbody>
              {bugs.map((b) => (
                <tr key={b.bug} className={b.first_run === 'missed' ? 'missed' : ''}>
                  <th scope="row">{b.bug}<span className="small block">{b.detail}</span></th>
                  <td>{b.caught_by}</td>
                  <td>
                    <span className={`pill-status ${b.first_run}`}>
                      {b.first_run === 'caught' ? <Check size={14} /> : <X size={14} />}
                      {b.first_run === 'caught' ? 'Caught' : 'Missed'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small hint">
          The missed bug was a real gap: the tests compared final outputs and never the token stream a client sees. A test on the stream was
          added, and the same bug is now caught. This was a manual spot check of four bugs, not a mutation-testing suite, so it is evidence
          and not coverage.
        </p>
      </Reveal>
    </Section>
  )
}
