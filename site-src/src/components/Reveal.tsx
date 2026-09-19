import type { CSSProperties, ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'

export const EASE_OUT = [0.16, 1, 0.3, 1] as const

interface RevealProps {
  children: ReactNode
  delay?: number
  y?: number
  className?: string
  style?: CSSProperties
  id?: string
}

/** Quiet scroll reveal: opacity plus a small rise, once. Users who prefer less motion get the final state. */
export default function Reveal({ children, delay = 0, y = 16, className, style, id }: RevealProps) {
  const reduce = useReducedMotion()
  if (reduce) {
    return (
      <div className={className} style={style} id={id}>
        {children}
      </div>
    )
  }
  return (
    <motion.div
      id={id}
      className={className}
      style={style}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -8% 0px' }}
      transition={{ duration: 0.7, delay, ease: EASE_OUT }}
    >
      {children}
    </motion.div>
  )
}
