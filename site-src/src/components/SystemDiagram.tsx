import { useMemo, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { ARCH_VIEW, EDGES, GROUP_LABEL, NODES, TRACE, type ArchEdge, type ArchNode, type NodeGroup } from '../content/architecture'
import { data } from '../data'
import { repoFile } from '../config'
import { useTicker } from '../lib/hooks'
import Reveal from './Reveal'
import Section from './Section'
import Lifecycle from './Lifecycle'

const GROUPS: NodeGroup[] = ['client', 'service', 'core', 'ops', 'ship']

function fill(text: string): string {
  const b = data.m4_burst
  return text
    .replace('{runs}', String(data.meta.runs))
    .replace('{slow_min}', String(b.paged_slowdown_pct_min))
    .replace('{slow_max}', String(b.paged_slowdown_pct_max))
    .replace('{speedup}', b.paged_speedup_at_128.toFixed(1))
}

const byId = new Map<string, ArchNode>(NODES.map((n) => [n.id, n]))
// the packet rides on the node's top-right corner so it never covers the label
const centre = (n: ArchNode): { x: number; y: number } => ({ x: n.x + n.w - 16, y: n.y + 16 })

function Detail({ node }: { node: ArchNode }) {
  return (
    <div className="arch-detail" aria-live="polite">
      <div className="ad-head">
        <h3>{node.title}</h3>
        <span className="tag">{GROUP_LABEL[node.group]}</span>
      </div>
      <p className="body">{node.role}</p>
      <h4>Decisions inside it</h4>
      <ul className="bullets">{node.decisions.map((d) => <li key={d}>{d}</li>)}</ul>
      {node.limitation && (
        <p className="limit"><b>Known limitation.</b> {node.limitation}</p>
      )}
      {node.proof && (
        <p className="proof"><b>Evidence.</b> {fill(node.proof)}</p>
      )}
      <div className="files">
        {node.files.map((f) => {
          const href = repoFile(f)
          return href
            ? <a key={f} href={href} target="_blank" rel="noopener noreferrer"><code>{f}</code></a>
            : <code key={f}>{f}</code>
        })}
      </div>
    </div>
  )
}

export default function SystemDiagram() {
  const reduce = useReducedMotion()
  const [selected, setSelected] = useState('sched')
  const [hover, setHover] = useState<string | null>(null)
  const [step, setStep] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)

  const traceNode = step != null ? TRACE[step]?.node : undefined
  const focusId = hover ?? traceNode ?? selected
  const node = byId.get(traceNode ?? selected) ?? NODES[0]!

  useTicker(() => setStep((s) => {
    const n = (s ?? -1) + 1
    if (n >= TRACE.length) { setPlaying(false); return s }
    return n
  }), 2600, playing)

  const traceEdges = useMemo(() => {
    const set = new Set<string>()
    if (step != null && step > 0) {
      const a = TRACE[step - 1]?.node
      const b = TRACE[step]?.node
      EDGES.forEach((e) => { if ((e.from === a && e.to === b) || (e.from === b && e.to === a)) set.add(e.id) })
    }
    return set
  }, [step])

  const isHot = (e: ArchEdge): boolean => traceEdges.has(e.id) || e.from === focusId || e.to === focusId
  const dot = traceNode ? centre(byId.get(traceNode) ?? NODES[0]!) : null

  const start = () => { setStep(0); setPlaying(true) }
  const reset = () => { setPlaying(false); setStep(null) }

  return (
    <Section
      id="architecture"
      title="How it is built"
      intro="Nine components in one process and the machinery around it. Click any of them, or trace a single request from the load generator to the metrics and back."
    >
      <Reveal>
        <div className="arch">
          <div className="arch-bar">
            <div className="arch-legend" aria-label="Legend">
              {GROUPS.map((g) => <span key={g} className={`lg lg-${g}`}><i />{GROUP_LABEL[g]}</span>)}
            </div>
            <div className="row gap-2">
              {step == null ? (
                <button className="btn primary" onClick={start}><Play size={14} />Trace a request</button>
              ) : (
                <>
                  <button className="btn" onClick={() => setPlaying((p) => !p)}>{playing ? <Pause size={14} /> : <Play size={14} />}{playing ? 'Pause' : 'Resume'}</button>
                  <button className="btn" onClick={() => { setPlaying(false); setStep((s) => Math.min(TRACE.length - 1, (s ?? -1) + 1)) }}>Next</button>
                  <button className="btn" onClick={reset}><RotateCcw size={14} />Reset</button>
                </>
              )}
            </div>
          </div>

          <div className="hscroll" tabIndex={0} role="group" aria-label="System diagram, scrollable">
            <svg className="arch-svg" viewBox={`${ARCH_VIEW.x} ${ARCH_VIEW.y} ${ARCH_VIEW.w} ${ARCH_VIEW.h}`} role="group" aria-label="System map of the inference server">
              <defs>
                <marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
                </marker>
              </defs>
              {EDGES.map((e) => (
                <g key={e.id} className={`edge e-${e.kind} ${isHot(e) ? 'hot' : ''}`}>
                  <path d={e.d} fill="none" markerEnd="url(#ah)" />
                  {e.label && <text x={e.lx} y={e.ly} textAnchor={e.anchor ?? 'start'}>{e.label}</text>}
                </g>
              ))}
              {NODES.map((n) => {
                const on = n.id === focusId
                return (
                  <g
                    key={n.id} className={`node g-${n.group} ${on ? 'on' : ''}`} tabIndex={0} role="button"
                    aria-pressed={n.id === selected} aria-label={`${n.title}: ${n.sub}`}
                    onClick={() => { setSelected(n.id); reset() }}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(n.id); reset() } }}
                    onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
                  >
                    <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="6" />
                    <text className="nt" x={n.x + 16} y={n.y + 36}>{n.title}</text>
                    <text className="ns" x={n.x + 16} y={n.y + 60}>{n.sub}</text>
                  </g>
                )
              })}
              {dot && (
                <motion.circle
                  r="8" className="packet" initial={false}
                  animate={{ cx: dot.x, cy: dot.y }}
                  transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 90, damping: 18 }}
                />
              )}
            </svg>
          </div>

          <p className="trace-cap" aria-live="polite">
            {step != null
              ? <><b className="num">{step + 1} / {TRACE.length}.</b> {TRACE[step]?.caption}</>
              : 'Solid lines carry the request path, dashed lines carry control and return traffic. Selecting a component explains what it decides.'}
          </p>
        </div>
      </Reveal>

      <Reveal delay={0.05}><Detail node={node} /></Reveal>
      <Lifecycle />
    </Section>
  )
}
