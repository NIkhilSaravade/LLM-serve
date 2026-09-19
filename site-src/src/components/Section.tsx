import type { ReactNode } from 'react'
import Reveal from './Reveal'

interface Props {
  id: string
  title: string
  intro?: ReactNode
  children?: ReactNode
  className?: string
}

/** A titled section. The heading carries its own weight; there is no label above it. */
export default function Section({ id, title, intro, children, className }: Props) {
  return (
    <section id={id} className={className} aria-labelledby={`${id}-h`}>
      <Reveal className="sec-head">
        <h2 id={`${id}-h`}>{title}</h2>
        {intro && <div className="body">{intro}</div>}
      </Reveal>
      {children}
    </section>
  )
}

export function Sub({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Reveal className="sub-head">
      <h3>{title}</h3>
      {children && <div className="body">{children}</div>}
    </Reveal>
  )
}
