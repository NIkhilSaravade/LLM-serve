import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Play } from 'lucide-react'
import { useTicker } from '../lib/hooks'
import Reveal from './Reveal'
import { Sub } from './Section'

type StateId = 'door' | 'waiting' | 'running' | 'finished' | 'rejected'

const STATES: Record<StateId, { x: number; y: number; w: number; label: string; sub: string }> = {
  door: { x: 20, y: 96, w: 128, label: 'Front door', sub: 'queue cap' },
  waiting: { x: 200, y: 96, w: 150, label: 'WAITING', sub: 'holds no KV memory' },
  running: { x: 420, y: 96, w: 150, label: 'RUNNING', sub: 'in the decode batch' },
  finished: { x: 640, y: 96, w: 150, label: 'FINISHED', sub: 'KV freed' },
  rejected: { x: 20, y: 200, w: 128, label: 'REJECTED', sub: 'HTTP 429' },
}

interface Scenario {
  id: string
  label: string
  path: StateId[]
  caption: string
}

const SCENARIOS: Scenario[] = [
  { id: 'normal', label: 'Normal', path: ['door', 'waiting', 'running', 'finished'], caption: 'Accepted, admitted when memory allows, decoded, then finished on a stop token or its length limit. Its blocks return to the free list.' },
  { id: 'evicted', label: 'Evicted', path: ['door', 'waiting', 'running', 'waiting', 'running', 'finished'], caption: 'Memory ran out. The request was evicted, its KV thrown away but its generated tokens kept, and it re-entered at the front of the queue. Re-prefilling prompt plus generated tokens gives the next token directly.' },
  { id: 'cancelled', label: 'Client left', path: ['door', 'waiting', 'running', 'finished'], caption: 'The connection closed mid-stream. The scheduler drops the request and frees its blocks at the start of the next iteration: abandoned work stops costing anything.' },
  { id: 'rejected', label: 'Queue full', path: ['door', 'rejected'], caption: 'The queue was at its cap, so the request is refused with HTTP 429 and Retry-After rather than queued without bound.' },
]

const ITERATION = [
  { name: 'Retire', code: 'retire()', text: 'Drop cancelled waiting requests. Finish cancelled running ones. Free the KV memory of everything that finished, so it can be used this very iteration.' },
  { name: 'Admit', code: 'admit()', text: 'First come first served, evicted requests first. Continuous mode prefills each newcomer on its own and adds it to the batch. Static mode only admits when nothing is running.' },
  { name: 'Make room', code: 'ensure_capacity()', text: 'Each row needs a block for the token it is about to feed. If none is free, evict a victim and retry. Older requests are served first.' },
  { name: 'Decode', code: 'step_tokens()', text: 'One batched forward pass. Every row feeds its newest token at position seq_len - 1 and attends only to its own keys.' },
  { name: 'Emit', code: '_emit()', text: 'Append each token, stream it to its client, and mark the request finished on a stop token or its length limit.' },
] as const

function center(id: StateId): { x: number; y: number } {
  const s = STATES[id]
  return { x: s.x + s.w - 16, y: s.y + 16 }
}

export default function Lifecycle() {
  const reduce = useReducedMotion()
  const [sid, setSid] = useState('normal')
  const [pos, setPos] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [it, setIt] = useState(0)
  const [itPlay, setItPlay] = useState(false)
  const sc = SCENARIOS.find((s) => s.id === sid) ?? SCENARIOS[0]!
  const here = sc.path[Math.min(pos, sc.path.length - 1)] ?? 'door'
  const at = center(here)

  useTicker(() => setPos((p) => { if (p + 1 >= sc.path.length) { setPlaying(false); return p } return p + 1 }), 1100, playing)
  useTicker(() => setIt((i) => (i + 1) % ITERATION.length), 2400, itPlay)

  const run = (id: string) => { setSid(id); setPos(0); setPlaying(true) }

  return (
    <>
      <Sub title="The life of a request">
        A request is always in exactly one of these states. The state machine is explicit in the code because it makes the scheduler far
        easier to reason about, log and test.
      </Sub>
      <Reveal>
        <div className="arch">
          <div className="arch-bar">
            <div className="seg" role="group" aria-label="Scenario">
              {SCENARIOS.map((s) => <button key={s.id} aria-pressed={sid === s.id} onClick={() => run(s.id)}>{s.label}</button>)}
            </div>
            <button className="btn primary" onClick={() => run(sid)}><Play size={14} />Replay</button>
          </div>
          <div className="hscroll" tabIndex={0} role="group" aria-label="State machine, scrollable">
            <svg className="life-svg" viewBox="0 0 810 270" role="group" aria-label="Request state machine">
              <defs>
                <marker id="ah2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
                </marker>
              </defs>
              <g className="edge e-request">
                <path d="M148,128 H200" fill="none" markerEnd="url(#ah2)" /><text x="160" y="118">admit?</text>
                <path d="M350,128 H420" fill="none" markerEnd="url(#ah2)" /><text x="362" y="118">prefill</text>
                <path d="M570,128 H640" fill="none" markerEnd="url(#ah2)" /><text x="580" y="118">done</text>
              </g>
              <g className="edge e-control">
                <path d="M470,96 C470,30 300,30 300,96" fill="none" markerEnd="url(#ah2)" />
                <text x="316" y="34">evicted: free KV, keep tokens</text>
                <path d="M84,160 V200" fill="none" markerEnd="url(#ah2)" /><text x="92" y="186">queue full</text>
                <path d="M495,160 C495,236 715,236 715,160" fill="none" markerEnd="url(#ah2)" />
                <text x="548" y="248">client disconnects: cancelled</text>
              </g>
              {(Object.keys(STATES) as StateId[]).map((id) => {
                const s = STATES[id]
                return (
                  <g key={id} className={`node g-core ${here === id ? 'on' : ''}`}>
                    <rect x={s.x} y={s.y} width={s.w} height={64} rx="6" />
                    <text className="nt" x={s.x + 14} y={s.y + 27}>{s.label}</text>
                    <text className="ns" x={s.x + 14} y={s.y + 48}>{s.sub}</text>
                  </g>
                )
              })}
              <motion.circle
                r="8" className="packet" initial={false} animate={{ cx: at.x, cy: at.y }}
                transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 140, damping: 20 }}
              />
            </svg>
          </div>
          <p className="trace-cap" aria-live="polite">{sc.caption}</p>
        </div>
      </Reveal>

      <Sub title="One scheduler iteration">
        The scheduler is a loop of five steps. Their order is deliberate: memory is freed before anyone is admitted, and capacity is secured
        before the forward pass, so a decode step can never run out of blocks halfway through.
      </Sub>
      <Reveal>
        <div className="arch">
          <div className="arch-bar">
            <div className="seg" role="group" aria-label="Iteration step">
              {ITERATION.map((s, i) => <button key={s.name} aria-pressed={it === i} onClick={() => { setItPlay(false); setIt(i) }}>{s.name}</button>)}
            </div>
            <button className="btn" onClick={() => setItPlay((p) => !p)}>{itPlay ? 'Pause' : 'Auto-play'}</button>
          </div>
          <ol className="iter" aria-label="Scheduler steps">
            {ITERATION.map((s, i) => (
              <li key={s.name} className={i === it ? 'on' : i < it ? 'done' : ''}>
                <code>{s.code}</code>
              </li>
            ))}
          </ol>
          <p className="trace-cap" aria-live="polite"><b>{ITERATION[it]?.name}.</b> {ITERATION[it]?.text}</p>
        </div>
      </Reveal>
    </>
  )
}
