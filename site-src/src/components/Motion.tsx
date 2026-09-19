import { useEffect, useRef, useState } from 'react'
import { useInView, useReducedMotion } from 'motion/react'
import Reveal from './Reveal'
import Section from './Section'
import { data } from '../data'
import { f2, mulberry32 } from '../lib/format'
import { useTicker } from '../lib/hooks'

/* ------------------------------------------------------------------ batching */
const SLOTS = 6
const COLS = 46
const ROW = 20
const GAP = 4

const STREAM: number[] = (() => {
  const r = mulberry32(11)
  return Array.from({ length: 400 }, () => 3 + Math.floor(Math.pow(r(), 1.7) * 19))
})()

interface Cell { id: number; idle: boolean }
interface BatchSim {
  slots: ({ id: number; left: number } | null)[]
  hist: Cell[][]
  next: number
  done: number
  busy: number
  steps: number
}
const freshBatch = (): BatchSim => ({ slots: Array(SLOTS).fill(null), hist: Array.from({ length: SLOTS }, () => []), next: 0, done: 0, busy: 0, steps: 0 })

/** One decode step. Static: admit only when every slot is empty. Continuous: refill every free slot now. */
function tick(s: BatchSim, mode: 'static' | 'continuous'): BatchSim {
  const slots = s.slots.slice()
  let next = s.next
  const allEmpty = slots.every((x) => x === null)
  if (mode === 'continuous' || allEmpty) {
    for (let i = 0; i < SLOTS; i++) {
      if (slots[i] === null) { slots[i] = { id: next, left: STREAM[next % STREAM.length] as number }; next++ }
    }
  }
  const anyActive = slots.some((x) => x !== null)
  let busy = 0
  let done = 0
  const hist = s.hist.map((h, i) => {
    const sl = slots[i]
    const cell: Cell = sl ? { id: sl.id, idle: false } : { id: -1, idle: anyActive }
    if (sl) busy++
    const nh = h.length >= COLS ? h.slice(h.length - COLS + 1) : h.slice()
    nh.push(cell)
    return nh
  })
  for (let i = 0; i < SLOTS; i++) {
    const sl = slots[i]
    if (sl) {
      const left = sl.left - 1
      if (left <= 0) { slots[i] = null; done++ } else slots[i] = { ...sl, left }
    }
  }
  return { slots, hist, next, done: s.done + done, busy: s.busy + busy, steps: s.steps + 1 }
}

function Lane({ mode, state, color }: { mode: 'static' | 'continuous'; state: BatchSim; color: string }) {
  const w = 600
  const cw = (w - GAP) / COLS
  const h = SLOTS * (ROW + GAP)
  const util = state.steps ? state.busy / (state.steps * SLOTS) : 0
  const idleNow = state.hist.filter((x) => x[x.length - 1]?.idle).length
  const pid = `hatch-${mode}`
  return (
    <div>
      <div className="lane-h">
        <b>{mode === 'static' ? 'Static batching' : 'Continuous batching'}</b>
        <span className="small">{mode === 'static' ? 'new work waits for the whole batch' : 'a freed slot is refilled next step'}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} role="img" className="block"
        aria-label={`${mode} batching simulation with ${SLOTS} slots. ${state.done} requests finished, utilisation ${Math.round(util * 100)} percent.`}>
        <defs>
          <pattern id={pid} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-strong)" strokeWidth="1.5" />
          </pattern>
        </defs>
        {state.hist.map((row, i) => row.map((c, j) => {
          const x = GAP / 2 + j * cw
          const y = i * (ROW + GAP) + GAP / 2
          const prev = row[j - 1]
          const edge = prev !== undefined && prev.id !== c.id
          if (c.id < 0) {
            return c.idle
              ? <rect key={`${i}-${j}`} x={x} y={y} width={cw + 0.5} height={ROW} fill={`url(#${pid})`} />
              : <rect key={`${i}-${j}`} x={x} y={y} width={cw + 0.5} height={ROW} fill="var(--line)" opacity=".5" />
          }
          return <rect key={`${i}-${j}`} x={x + (edge ? 1.5 : 0)} y={y} width={cw + 0.5 - (edge ? 1.5 : 0)} height={ROW} fill={color} opacity={c.id % 2 ? 0.95 : 0.6} />
        }))}
      </svg>
      <div className="stat-line">
        <span>busy now <b className="num">{state.slots.filter(Boolean).length}/{SLOTS}</b></span>
        <span>idle (hatched) <b className="num">{idleNow}</b></span>
        <span>finished <b className="num">{state.done}</b></span>
        <span>utilisation so far <b className="num">{util.toFixed(2)}</b></span>
      </div>
    </div>
  )
}

function Controls({ playing, setPlaying, step, restart, speed, setSpeed }: {
  playing: boolean; setPlaying: (f: (p: boolean) => boolean) => void; step: () => void; restart: () => void
  speed: number; setSpeed: (n: number) => void
}) {
  return (
    <div className="sim-ctl">
      <button className="btn" onClick={() => setPlaying((v) => !v)}>{playing ? 'Pause' : 'Play'}</button>
      <button className="btn" onClick={step}>Step</button>
      <button className="btn" onClick={restart}>Restart</button>
      <div className="seg" role="group" aria-label="Speed">
        {[1, 2, 4].map((v) => <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{v}x</button>)}
      </div>
    </div>
  )
}

function BatchingSim() {
  const ref = useRef<HTMLDivElement | null>(null)
  const inView = useInView(ref, { margin: '-10% 0px -10% 0px' })
  const reduce = useReducedMotion() ?? false
  const [sims, setSims] = useState({ s: freshBatch(), c: freshBatch() })
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const m = data.milestones

  const advance = () => setSims((p) => ({ s: tick(p.s, 'static'), c: tick(p.c, 'continuous') }))
  useEffect(() => {
    if (!reduce) return
    let p = { s: freshBatch(), c: freshBatch() }
    for (let i = 0; i < 90; i++) p = { s: tick(p.s, 'static'), c: tick(p.c, 'continuous') }
    setSims(p)
    setPlaying(false)
  }, [reduce])
  useTicker(advance, 1000 / (5 * speed), playing && inView && !reduce)

  return (
    <div className="sim" ref={ref}>
      <div className="chart-top top-0">
        <div>
          <div className="chart-title">Batching, one decode step at a time</div>
          <div className="chart-sub">Six slots, the same stream of requests, time flows left to right.</div>
        </div>
        <span className="tag illustration" title="A simplified simulation, not benchmark data">Illustration</span>
      </div>
      <p className="sim-cap">
        Each row is a slot and each block is one decode step. Requests need different numbers of steps. When a short one finishes, static
        batching leaves its slot empty until the slowest request in the batch is done. Continuous batching hands the slot to the next
        request straight away.
      </p>
      <Controls playing={playing} setPlaying={setPlaying} step={() => { setPlaying(false); advance() }} restart={() => setSims({ s: freshBatch(), c: freshBatch() })} speed={speed} setSpeed={setSpeed} />
      <div className="sim-pair single">
        <Lane mode="static" state={sims.s} color="var(--s-static)" />
        <Lane mode="continuous" state={sims.c} color="var(--s-cont)" />
      </div>
      <div className="measured-line">
        <span className="tag measured">Measured</span>
        <span>
          Under a saturating burst on the real server, slot utilisation was <b className="num ink">{m.sat_static_util.toFixed(2)}</b> for static and{' '}
          <b className="num ink">{m.sat_cont_util.toFixed(2)}</b> for continuous batching, at <b className="num ink">{m.sat_static_tok_s}</b> against{' '}
          <b className="num ink">{m.sat_cont_tok_s}</b> tokens per second.
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ paging */
const CELLS = 48
const MCOLS = 12
const RESERVE = 16
const SHADE = [0.5, 0.72, 0.95] as const

const FINAL: number[] = (() => { const r = mulberry32(5); return Array.from({ length: 300 }, () => 4 + Math.floor(Math.pow(r(), 1.4) * 11)) })()
const ORDER: number[] = (() => {
  const a = Array.from({ length: CELLS }, (_, i) => i)
  const r = mulberry32(9)
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); const x = a[i] as number; a[i] = a[j] as number; a[j] = x }
  return a
})()

interface MCell { id: number; used: boolean; op: number }
interface MReq { id: number; final: number; tokens: number; cells: number[]; op: number }
interface MemSim { cells: (MCell | null)[]; reqs: MReq[]; next: number; finished: number; steps: number }
const freshMem = (): MemSim => ({ cells: Array(CELLS).fill(null), reqs: [], next: 0, finished: 0, steps: 0 })

function memStep(s: MemSim, mode: 'contiguous' | 'paged'): MemSim {
  const cells = s.cells.map((c) => (c ? { ...c } : null))
  let reqs = s.reqs.map((r) => ({ ...r, cells: r.cells.slice() }))
  let next = s.next
  let finished = s.finished
  for (;;) {
    let ok: boolean
    let start = 0
    if (mode === 'contiguous') {
      const found = [0, 16, 32].find((st) => cells.slice(st, st + RESERVE).every((c) => c === null))
      ok = found !== undefined
      start = found ?? 0
    } else {
      ok = ORDER.filter((i) => cells[i] === null).length >= 4
    }
    if (!ok || reqs.length >= 12) break
    const id = next++
    const r: MReq = { id, final: FINAL[id % FINAL.length] as number, tokens: 0, cells: [], op: SHADE[id % SHADE.length] as number }
    if (mode === 'contiguous') for (let k = 0; k < RESERVE; k++) { cells[start + k] = { id, used: false, op: r.op }; r.cells.push(start + k) }
    reqs.push(r)
  }
  reqs = reqs.map((r) => {
    r.tokens += 1
    if (mode === 'contiguous') {
      const at = r.cells[r.tokens - 1]
      if (at !== undefined) cells[at] = { id: r.id, used: true, op: r.op }
    } else {
      const slot = ORDER.find((i) => cells[i] === null)
      if (slot !== undefined) { cells[slot] = { id: r.id, used: true, op: r.op }; r.cells.push(slot) } else r.tokens -= 1
    }
    return r
  })
  const keep: MReq[] = []
  for (const r of reqs) {
    if (r.tokens >= r.final) { r.cells.forEach((c) => { cells[c] = null }); finished++ } else keep.push(r)
  }
  return { cells, reqs: keep, next, finished, steps: s.steps + 1 }
}

function Grid({ mode, state }: { mode: 'contiguous' | 'paged'; state: MemSim }) {
  const used = state.cells.filter((c) => c?.used).length
  const alloc = state.cells.filter(Boolean).length
  const eff = alloc ? used / alloc : 0
  const rows = CELLS / MCOLS
  const hue = mode === 'contiguous' ? 'var(--s-cont)' : 'var(--s-paged)'
  const S = 22
  const G = 4
  const pid = `hatch-mem-${mode}`
  return (
    <div>
      <div className="lane-h">
        <b>{mode === 'contiguous' ? 'Contiguous slots' : 'Paged blocks'}</b>
        <span className="small">{mode === 'contiguous' ? 'each request reserves the maximum up front' : 'blocks are taken only as a sequence grows'}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${MCOLS * (S + G)} ${rows * (S + G)}`} role="img" className="block maxw"
        aria-label={`${mode} memory: ${state.reqs.length} requests running, ${used} of ${alloc} allocated blocks hold tokens.`}>
        <defs>
          <pattern id={pid} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--muted)" strokeWidth="1.4" />
          </pattern>
        </defs>
        {state.cells.map((c, i) => {
          const x = (i % MCOLS) * (S + G)
          const y = Math.floor(i / MCOLS) * (S + G)
          if (!c) return <rect key={i} x={x} y={y} width={S} height={S} rx="3" fill="none" stroke="var(--line-strong)" />
          if (c.used) return <rect key={i} x={x} y={y} width={S} height={S} rx="3" fill={hue} opacity={c.op} />
          return (
            <g key={i}>
              <rect x={x} y={y} width={S} height={S} rx="3" fill={`url(#${pid})`} />
              <rect x={x + 0.5} y={y + 0.5} width={S - 1} height={S - 1} rx="3" fill="none" stroke={hue} opacity={c.op} strokeWidth="1.4" />
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

function PagedSim() {
  const ref = useRef<HTMLDivElement | null>(null)
  const inView = useInView(ref, { margin: '-10% 0px -10% 0px' })
  const reduce = useReducedMotion() ?? false
  const [sims, setSims] = useState({ c: freshMem(), p: freshMem() })
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const rows = data.ablation.B.rows
  const contig = rows.find((r) => r.key === 'm3_continuous')?.kv_eff?.median
  const paged = rows.find((r) => r.key === 'm4_full')?.kv_eff?.median

  const adv = () => setSims((v) => ({ c: memStep(v.c, 'contiguous'), p: memStep(v.p, 'paged') }))
  useEffect(() => {
    if (!reduce) return
    let v = { c: freshMem(), p: freshMem() }
    for (let i = 0; i < 60; i++) v = { c: memStep(v.c, 'contiguous'), p: memStep(v.p, 'paged') }
    setSims(v)
    setPlaying(false)
  }, [reduce])
  useTicker(adv, 1000 / (4 * speed), playing && inView && !reduce)

  return (
    <div className="sim" ref={ref}>
      <div className="chart-top top-0">
        <div>
          <div className="chart-title">Reserving memory versus paging it</div>
          <div className="chart-sub">The same 48 blocks of memory and the same requests.</div>
        </div>
        <span className="tag illustration" title="A simplified simulation, not benchmark data">Illustration</span>
      </div>
      <p className="sim-cap">
        A request does not know how long its answer will be, so the safe move is to reserve the maximum. Most of that reservation stays
        empty (hatched). Paging hands out one small block at a time as the sequence grows, and the blocks need not sit next to each
        other, so far more requests fit in the same memory.
      </p>
      <Controls playing={playing} setPlaying={setPlaying} step={() => { setPlaying(false); adv() }} restart={() => setSims({ c: freshMem(), p: freshMem() })} speed={speed} setSpeed={setSpeed} />
      <div className="sim-pair">
        <Grid mode="contiguous" state={sims.c} />
        <Grid mode="paged" state={sims.p} />
      </div>
      {contig != null && paged != null && (
        <div className="measured-line">
          <span className="tag measured">Measured</span>
          <span>On the real server, live tokens divided by allocated capacity was <b className="num ink">{f2(contig)}</b> for contiguous slots and <b className="num ink">{f2(paged)}</b> for paged blocks.</span>
        </div>
      )}
    </div>
  )
}

export default function MotionSection() {
  return (
    <Section
      id="motion"
      title="Both ideas, in motion"
      intro="The results come from two mechanisms. These are simplified simulations so you can watch them work. They are illustrations, not data, and are labelled that way. The measured value each one stands in for is underneath."
    >
      <div className="split">
        <Reveal><BatchingSim /></Reveal>
        <Reveal delay={0.08}><PagedSim /></Reveal>
      </div>
    </Section>
  )
}
