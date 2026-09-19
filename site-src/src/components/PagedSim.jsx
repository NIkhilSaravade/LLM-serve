import { useEffect, useRef, useState } from 'react'
import { useInView, useReducedMotion } from 'motion/react'
import { mulberry32 } from '../lib.js'

const CELLS = 48       // memory, in "token blocks"
const COLS = 12
const RESERVE = 16     // what a contiguous slot reserves per request (the maximum context)
const SHADE = [0.5, 0.72, 0.95]   // requests are told apart by opacity; hue belongs to the system

const rnd = mulberry32(5)
const FINAL = Array.from({ length: 300 }, () => 4 + Math.floor(Math.pow(rnd(), 1.4) * 11)) // blocks each request really needs
const ORDER = (() => { const a = Array.from({ length: CELLS }, (_, i) => i); const r = mulberry32(9); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]] } return a })()

function fresh() { return { cells: Array(CELLS).fill(null), reqs: [], next: 0, finished: 0, steps: 0 } }

function step(s, mode) {
  const cells = s.cells.map((c) => (c ? { ...c } : null))
  let reqs = s.reqs.map((r) => ({ ...r, cells: r.cells.slice() }))
  let next = s.next, finished = s.finished

  // admit
  for (;;) {
    const need = mode === 'contiguous' ? RESERVE : 2
    const freeIdx = mode === 'contiguous'
      ? [0, 16, 32].find((st) => cells.slice(st, st + RESERVE).every((c) => c === null))
      : ORDER.filter((i) => cells[i] === null)
    const ok = mode === 'contiguous' ? freeIdx !== undefined : freeIdx.length >= need + 2
    if (!ok || reqs.length >= 12) break
    const id = next++
    const r = { id, final: FINAL[id % FINAL.length], tokens: 0, cells: [], op: SHADE[id % SHADE.length] }
    if (mode === 'contiguous') {
      for (let k = 0; k < RESERVE; k++) { cells[freeIdx + k] = { id, used: false, op: r.op }; r.cells.push(freeIdx + k) }
    }
    reqs.push(r)
  }
  // grow one token per request per step
  reqs = reqs.map((r) => {
    r.tokens += 1
    if (mode === 'contiguous') {
      cells[r.cells[r.tokens - 1]] = { ...cells[r.cells[r.tokens - 1]], used: true }
    } else {
      const slot = ORDER.find((i) => cells[i] === null)
      if (slot !== undefined) { cells[slot] = { id: r.id, used: true, op: r.op }; r.cells.push(slot) } else r.tokens -= 1
    }
    return r
  })
  // finish
  const keep = []
  for (const r of reqs) {
    if (r.tokens >= r.final) { r.cells.forEach((c) => { cells[c] = null }); finished++ } else keep.push(r)
  }
  return { cells, reqs: keep, next, finished, steps: s.steps + 1 }
}

function Grid({ mode, state }) {
  const used = state.cells.filter((c) => c?.used).length
  const alloc = state.cells.filter(Boolean).length
  const eff = alloc ? used / alloc : 0
  const rows = CELLS / COLS
  const hue = mode === 'contiguous' ? 'var(--s-cont)' : 'var(--s-paged)'
  const S = 22, G = 4
  return (
    <div>
      <div className="lane-h">
        <b>{mode === 'contiguous' ? 'Contiguous slots' : 'Paged blocks'}</b>
        <span className="small">{mode === 'contiguous' ? 'each request reserves the maximum up front' : 'blocks are taken only as a sequence grows'}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${COLS * (S + G)} ${rows * (S + G)}`} role="img"
        aria-label={`${mode} memory: ${state.reqs.length} requests running, ${used} of ${alloc} allocated blocks hold tokens.`} style={{ maxWidth: 520, display: 'block' }}>
        <defs>
          <pattern id="hatch-mem" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--muted)" strokeWidth="1.4" />
          </pattern>
        </defs>
        {state.cells.map((c, i) => {
          const x = (i % COLS) * (S + G), y = Math.floor(i / COLS) * (S + G)
          if (!c) return <rect key={i} x={x} y={y} width={S} height={S} rx="3" fill="none" stroke="var(--line-strong)" />
          if (c.used) return <rect key={i} x={x} y={y} width={S} height={S} rx="3" fill={hue} opacity={c.op} />
          return (
            <g key={i}>
              <rect x={x} y={y} width={S} height={S} rx="3" fill="url(#hatch-mem)" />
              <rect x={x + .5} y={y + .5} width={S - 1} height={S - 1} rx="3" fill="none" stroke={hue} opacity={c.op} strokeWidth="1.4" />
            </g>
          )
        })}
      </svg>
      <div className="stat-line">
        <span>running <b className="num">{state.reqs.length}</b></span>
        <span>blocks holding tokens <b className="num">{used}</b></span>
        <span>reserved but empty <b className="num">{alloc - used}</b></span>
        <span>efficiency <b className="num">{eff.toFixed(2)}</b></span>
      </div>
    </div>
  )
}

export default function PagedSim({ measured }) {
  const ref = useRef(null)
  const inView = useInView(ref, { margin: '-10% 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [sims, setSims] = useState(() => ({ c: fresh(), p: fresh() }))
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const adv = () => setSims((v) => ({ c: step(v.c, 'contiguous'), p: step(v.p, 'paged') }))

  useEffect(() => {
    if (!reduce) return
    let v = { c: fresh(), p: fresh() }
    for (let i = 0; i < 60; i++) v = { c: step(v.c, 'contiguous'), p: step(v.p, 'paged') }
    setSims(v); setPlaying(false)
  }, [reduce])
  useEffect(() => {
    if (!playing || !inView || reduce) return
    const id = setInterval(adv, 1000 / (4 * speed))
    return () => clearInterval(id)
  }, [playing, inView, speed, reduce])

  return (
    <div className="sim" ref={ref}>
      <div className="chart-top" style={{ paddingTop: 0 }}>
        <div>
          <div className="chart-title">Reserving memory versus paging it</div>
          <div className="chart-sub">The same 48 blocks of memory and the same requests.</div>
        </div>
        <span className="tag illustration" title="A simplified simulation, not benchmark data">Illustration</span>
      </div>
      <p className="sim-cap">
        A request does not know how long its answer will be, so the safe move is to reserve the maximum. Most of that reservation
        stays empty (hatched). Paging hands out one small block at a time as the sequence grows, and the blocks do not have to sit
        next to each other, so far more requests fit in the same memory.
      </p>
      <div className="sim-ctl">
        <button className="btn" onClick={() => setPlaying((v) => !v)}>{playing ? 'Pause' : 'Play'}</button>
        <button className="btn" onClick={() => { setPlaying(false); adv() }}>Step</button>
        <button className="btn" onClick={() => setSims({ c: fresh(), p: fresh() })}>Restart</button>
        <div className="seg" role="group" aria-label="Speed">
          {[1, 2, 4].map((v) => <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{v}x</button>)}
        </div>
      </div>
      <div className="sim-pair">
        <Grid mode="contiguous" state={sims.c} />
        <Grid mode="paged" state={sims.p} />
      </div>
      <div className="measured-line">
        <span className="tag measured">Measured</span>
        <span>
          On the real server, live tokens divided by allocated capacity was <b className="num ink">{measured.contig.toFixed(2)}</b> for contiguous slots
          and <b className="num ink">{measured.paged.toFixed(2)}</b> for paged blocks.
        </span>
      </div>
    </div>
  )
}
