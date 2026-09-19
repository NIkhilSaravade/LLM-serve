import { useEffect, useRef, useState } from 'react'
import { useInView, useReducedMotion } from 'motion/react'
import { mulberry32 } from '../lib.js'

const SLOTS = 6
const COLS = 46
const ROW = 20
const GAP = 4

/** Same request stream for both engines: output lengths are deterministic. */
function lengths(n) {
  const r = mulberry32(11)
  return Array.from({ length: n }, () => 3 + Math.floor(Math.pow(r(), 1.7) * 19))
}
const STREAM = lengths(400)

function fresh() {
  return { slots: Array(SLOTS).fill(null), hist: Array.from({ length: SLOTS }, () => []), next: 0, done: 0, busy: 0, steps: 0 }
}

/** One decode step. static: admit only when every slot is empty. continuous: refill every free slot now. */
function tick(s, mode) {
  const slots = s.slots.slice()
  const allEmpty = slots.every((x) => x === null)
  if (mode === 'continuous' || allEmpty) {
    for (let i = 0; i < SLOTS; i++) {
      if (slots[i] === null) { slots[i] = { id: s.next, left: STREAM[s.next % STREAM.length] }; s.next++ }
    }
  }
  const anyActive = slots.some((x) => x)
  let busy = 0, done = 0
  const hist = s.hist.map((h, i) => {
    const cell = slots[i] ? { id: slots[i].id, idle: false } : { id: -1, idle: anyActive }
    if (slots[i]) busy++
    const nh = h.length >= COLS ? h.slice(h.length - COLS + 1) : h.slice()
    nh.push(cell)
    return nh
  })
  for (let i = 0; i < SLOTS; i++) {
    if (slots[i]) { slots[i] = { ...slots[i], left: slots[i].left - 1 }; if (slots[i].left <= 0) { slots[i] = null; done++ } }
  }
  return { slots, hist, next: s.next, done: s.done + done, busy: s.busy + busy, steps: s.steps + 1 }
}

function Lane({ mode, state, color }) {
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
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} role="img" style={{ display: 'block' }}
        aria-label={`${mode} batching simulation with ${SLOTS} slots. ${state.done} requests finished, utilisation ${Math.round(util * 100)} percent.`}>
        <defs>
          <pattern id={pid} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-strong)" strokeWidth="1.5" />
          </pattern>
        </defs>
        {state.hist.map((row, i) => row.map((c, j) => {
          const x = GAP / 2 + j * cw   // fills from the left, then scrolls
          const y = i * (ROW + GAP) + GAP / 2
          const prev = row[j - 1]
          const edge = prev && prev.id !== c.id
          if (c.id < 0) {
            return c.idle
              ? <rect key={j} x={x} y={y} width={cw + 0.5} height={ROW} fill={`url(#${pid})`} />
              : <rect key={j} x={x} y={y} width={cw + 0.5} height={ROW} fill="var(--line)" opacity=".5" />
          }
          return <rect key={j} x={x + (edge ? 1.5 : 0)} y={y} width={cw + 0.5 - (edge ? 1.5 : 0)} height={ROW}
            fill={color} opacity={c.id % 2 ? 0.95 : 0.62} />
        }))}
      </svg>
      <div className="stat-line" aria-live="off">
        <span>busy now <b className="num">{state.slots.filter(Boolean).length}/{SLOTS}</b></span>
        <span>idle (hatched) <b className="num">{idleNow}</b></span>
        <span>finished <b className="num">{state.done}</b></span>
        <span>utilisation so far <b className="num">{util.toFixed(2)}</b></span>
      </div>
    </div>
  )
}

export default function BatchingSim({ measured }) {
  const ref = useRef(null)
  const inView = useInView(ref, { margin: '-10% 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [sims, setSims] = useState(() => ({ s: fresh(), c: fresh() }))
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)

  const advance = () => setSims((p) => ({ s: tick(p.s, 'static'), c: tick(p.c, 'continuous') }))
  const restart = () => setSims({ s: fresh(), c: fresh() })

  // Reduced motion: show a settled snapshot instead of running.
  useEffect(() => {
    if (!reduce) return
    let p = { s: fresh(), c: fresh() }
    for (let i = 0; i < 90; i++) p = { s: tick(p.s, 'static'), c: tick(p.c, 'continuous') }
    setSims(p)
    setPlaying(false)
  }, [reduce])

  useEffect(() => {
    if (!playing || !inView || reduce) return
    const id = setInterval(advance, 1000 / (5 * speed))
    return () => clearInterval(id)
  }, [playing, inView, speed, reduce])


  return (
    <div className="sim" ref={ref}>
      <div className="chart-top" style={{ paddingTop: 0 }}>
        <div>
          <div className="chart-title">Batching, one decode step at a time</div>
          <div className="chart-sub">Six slots, the same stream of requests, time flows left to right.</div>
        </div>
        <span className="tag illustration" title="A simplified simulation, not benchmark data">Illustration</span>
      </div>
      <p className="sim-cap">
        Each row is a slot and each block is one decode step. Requests need different numbers of steps. When a short one finishes,
        static batching leaves its slot empty until the slowest request in the batch is done. Continuous batching hands the slot to
        the next request straight away.
      </p>
      <div className="sim-ctl">
        <button className="btn" onClick={() => setPlaying((v) => !v)}>{playing ? 'Pause' : 'Play'}</button>
        <button className="btn" onClick={() => { setPlaying(false); advance() }}>Step</button>
        <button className="btn" onClick={restart}>Restart</button>
        <div className="seg" role="group" aria-label="Speed">
          {[1, 2, 4].map((v) => (
            <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{v}x</button>
          ))}
        </div>
      </div>
      <div className="sim-pair" style={{ gridTemplateColumns: '1fr' }}>
        <Lane mode="static" state={sims.s} color="var(--s-static)" />
        <Lane mode="continuous" state={sims.c} color="var(--s-cont)" />
      </div>
      <div className="measured-line">
        <span className="tag measured">Measured</span>
        <span>
          Under a saturating burst on the real server, slot utilisation was <b className="num ink">{measured.sat_static_util.toFixed(2)}</b> for
          static and <b className="num ink">{measured.sat_cont_util.toFixed(2)}</b> for continuous batching,
          at <b className="num ink">{measured.sat_static_tok_s}</b> vs <b className="num ink">{measured.sat_cont_tok_s}</b> tokens per second.
        </span>
      </div>
    </div>
  )
}
