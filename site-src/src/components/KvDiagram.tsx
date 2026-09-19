import { useMemo, useState } from 'react'
import Reveal from './Reveal'
import Section from './Section'
import { data } from '../data'
import { f2, mulberry32 } from '../lib/format'

const POOL = 32
const COLS = 8
const BLOCK_SIZES = [4, 8, 16, 32] as const
// 2 (K and V) x 12 layers x 768 dims x 4 bytes (fp32), the arithmetic from the design doc.
const BYTES_PER_TOKEN = 2 * 12 * 768 * 4
const MAX_CONTEXT = 1024
const MIB = 1024 * 1024

/** A fixed shuffle: the physical block a sequence's i-th logical block lands in. Deliberately not adjacent. */
const PHYS: number[] = (() => {
  const a = Array.from({ length: POOL }, (_, i) => i)
  const r = mulberry32(7)
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1))
    const x = a[i] as number
    a[i] = a[j] as number
    a[j] = x
  }
  return a
})()

export default function KvDiagram() {
  const [tokens, setTokens] = useState(17)
  const [bs, setBs] = useState<(typeof BLOCK_SIZES)[number]>(16)

  const blocks = Math.ceil(tokens / bs)
  const tail = tokens - (blocks - 1) * bs
  const wasted = blocks * bs - tokens
  const exactlyFull = tokens % bs === 0
  const usedMiB = (tokens * BYTES_PER_TOKEN) / MIB
  const reservedMiB = (MAX_CONTEXT * BYTES_PER_TOKEN) / MIB
  const table = useMemo(() => Array.from({ length: blocks }, (_, i) => PHYS[i] as number), [blocks])
  const owner = useMemo(() => {
    const m = new Map<number, number>()
    table.forEach((p, i) => m.set(p, i))
    return m
  }, [table])
  const eff = data.ablation.B.rows.find((r) => r.key === 'm4_full')?.kv_eff?.median
  const effC = data.ablation.B.rows.find((r) => r.key === 'm3_continuous')?.kv_eff?.median

  return (
    <Section
      id="memory"
      title="How KV memory is paged"
      intro={
        <>
          Every token of every running request needs its keys and values kept for the rest of the request: {BYTES_PER_TOKEN / 1024} KiB per
          token for GPT-2 small. Reserve the maximum context up front and most of it sits empty. Paging hands out small fixed blocks as a
          sequence grows, and a block table records where each one lives. Drag the slider and watch the boundary.
        </>
      }
    >
      <Reveal>
        <div className="arch kv">
          <div className="kv-controls">
            <label className="slider">
              <span>Sequence length <b className="num">{tokens}</b> tokens</span>
              <input type="range" min={1} max={96} value={tokens} onChange={(e) => setTokens(Number(e.target.value))} aria-label="Sequence length in tokens" />
            </label>
            <div className="seg" role="group" aria-label="Block size">
              {BLOCK_SIZES.map((b) => <button key={b} aria-pressed={bs === b} onClick={() => setBs(b)}>{b}-token blocks</button>)}
            </div>
          </div>

          <div className="kv-grid">
            <div>
              <h4>The sequence, cut into logical blocks</h4>
              <div className="tok-row" role="img" aria-label={`${tokens} tokens in ${blocks} logical blocks`}>
                {Array.from({ length: blocks }, (_, b) => {
                  const inBlock = b === blocks - 1 ? tail : bs
                  return (
                    <div key={b} className="lblock" style={{ flexBasis: `${(bs / Math.max(bs * blocks, 1)) * 100}%` }}>
                      <div className="cells">
                        {Array.from({ length: bs }, (_, c) => <i key={c} className={c < inBlock ? 'f' : 'e'} />)}
                      </div>
                      <span className="num">L{b}</span>
                    </div>
                  )
                })}
              </div>

              <h4>Block table: logical to physical</h4>
              <table className="data compact">
                <thead><tr><th scope="col">Logical</th><th scope="col">Physical block</th><th scope="col" className="r">Tokens held</th></tr></thead>
                <tbody>
                  {table.map((p, i) => (
                    <tr key={i}>
                      <th scope="row" className="num">L{i}</th>
                      <td className="num">P{p}</td>
                      <td className="r num">{i === blocks - 1 ? tail : bs} / {bs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <h4>The physical pool ({POOL} blocks)</h4>
              <svg className="pool" viewBox={`0 0 ${COLS * 44} ${(POOL / COLS) * 44}`} role="img" aria-label={`Physical pool with ${blocks} blocks in use, not adjacent`}>
                {Array.from({ length: POOL }, (_, p) => {
                  const x = (p % COLS) * 44
                  const y = Math.floor(p / COLS) * 44
                  const lo = owner.get(p)
                  const used = lo != null
                  const last = lo === blocks - 1
                  return (
                    <g key={p}>
                      <rect x={x + 2} y={y + 2} width="38" height="38" rx="5" className={used ? 'pb used' : 'pb'} />
                      {used && last && <rect x={x + 2} y={y + 40 - (38 * tail) / bs} width="38" height={(38 * tail) / bs} rx="3" className="pb-fill" />}
                      {used && !last && <rect x={x + 2} y={y + 2} width="38" height="38" rx="5" className="pb-fill" />}
                      <text x={x + 21} y={y + 26} textAnchor="middle" className={used ? 'pooltext on' : 'pooltext'}>{used ? `L${lo}` : `P${p}`}</text>
                    </g>
                  )
                })}
              </svg>
              <p className="small">Filled blocks are this sequence&rsquo;s. Their physical order is scrambled on purpose: attention has to work for blocks that are not adjacent.</p>
            </div>
          </div>

          <dl className="kv-stats">
            <div><dt>Blocks allocated</dt><dd className="num">{blocks}</dd></div>
            <div><dt>Empty slots in the last block</dt><dd className="num">{wasted}</dd></div>
            <div><dt>Paged memory used</dt><dd className="num">{usedMiB.toFixed(2)} MiB</dd></div>
            <div><dt>Contiguous would reserve</dt><dd className="num">{reservedMiB.toFixed(0)} MiB</dd></div>
          </dl>

          <p className={`kv-callout ${exactlyFull ? 'hot' : ''}`} aria-live="polite">
            {exactlyFull
              ? <><b>Exactly full.</b> {tokens} tokens fill {blocks} block{blocks > 1 ? 's' : ''} completely, so {blocks} block{blocks > 1 ? 's are' : ' is'} enough. The very next token opens block L{blocks}. Allocating one block too few here is the classic bug, which is why the test fixtures include prompts of exactly one block, one over and one under.</>
              : <>A sequence needs <span className="num">ceil({tokens} / {bs}) = {blocks}</span> block{blocks > 1 ? 's' : ''}. Waste is bounded by one partly filled block per request, instead of a reservation for the maximum context.</>}
          </p>
          {eff != null && effC != null && (
            <p className="small">Measured on the real server (workload B): live tokens divided by allocated capacity was <b className="num ink">{f2(effC)}</b> with contiguous slots and <b className="num ink">{f2(eff)}</b> with paged blocks.</p>
          )}
        </div>
      </Reveal>
    </Section>
  )
}
