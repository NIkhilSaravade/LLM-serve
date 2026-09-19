import { useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ChevronDown } from 'lucide-react'
import Reveal, { EASE_OUT } from './Reveal'
import Section from './Section'
import problemsRaw from '../content/problems.json'
import type { Problem, ProblemTag } from '../types'

export const problems = problemsRaw as Problem[]

const TAGS: Record<ProblemTag | 'all', string> = {
  all: 'All',
  measurement: 'Measurement',
  correctness: 'Correctness',
  harness: 'Harness',
  operations: 'Operations',
  process: 'Process',
}

function Fields({ p }: { p: Problem }) {
  const rows: [string, string][] = [
    ['What I saw', p.symptom],
    ['The wrong assumption', p.wrong_model],
    ['What was actually happening', p.cause],
    ['The fix', p.fix],
    ['What it taught', p.lesson],
  ]
  return (
    <dl className="prob-fields">
      {rows.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
      <div className="evidence"><dt>The numbers</dt><dd className="num">{p.evidence}</dd></div>
    </dl>
  )
}

export default function Problems() {
  const reduce = useReducedMotion()
  const [tag, setTag] = useState<ProblemTag | 'all'>('all')
  const [open, setOpen] = useState<string | null>(problems[0]?.id ?? null)
  const shown = problems.filter((p) => tag === 'all' || p.tag === tag)
  const counts = (t: ProblemTag | 'all') => (t === 'all' ? problems.length : problems.filter((p) => p.tag === t).length)

  return (
    <Section
      id="problems"
      title="What broke, and what it taught"
      intro={<>{problems.length} real problems from building and measuring this, each with the wrong assumption behind it. Most were in the measuring, not the engine: the hardest part of this project was not fooling itself.</>}
    >
      <Reveal>
        <div className="seg wrap-seg" role="group" aria-label="Filter problems by kind">
          {(Object.keys(TAGS) as (ProblemTag | 'all')[]).map((t) => (
            <button key={t} aria-pressed={tag === t} onClick={() => setTag(t)}>{TAGS[t]} <span className="num">{counts(t)}</span></button>
          ))}
        </div>
      </Reveal>
      <ul className="prob-list">
        {shown.map((p) => {
          const isOpen = open === p.id
          return (
            <li key={p.id} className={isOpen ? 'open' : ''}>
              <h3>
                <button aria-expanded={isOpen} aria-controls={`prob-${p.id}`} onClick={() => setOpen(isOpen ? null : p.id)}>
                  <span className={`tag kind-${p.tag}`}>{TAGS[p.tag]}</span>
                  <span className="pt">{p.title}</span>
                  <span className="when small">{p.when}</span>
                  <ChevronDown size={18} className="chev" aria-hidden="true" />
                </button>
              </h3>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    id={`prob-${p.id}`} className="prob-body"
                    initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
                    transition={{ duration: reduce ? 0 : 0.35, ease: EASE_OUT }}
                  >
                    <Fields p={p} />
                  </motion.div>
                )}
              </AnimatePresence>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}
