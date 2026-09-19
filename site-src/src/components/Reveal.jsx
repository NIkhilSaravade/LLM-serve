import { motion, useReducedMotion } from 'motion/react'

const EASE = [0.16, 1, 0.3, 1]

/** Quiet scroll reveal: opacity plus a small rise, once. Users who prefer less motion get the final state. */
export default function Reveal({ children, delay = 0, y = 14, className, as = 'div', ...rest }) {
  const reduce = useReducedMotion()
  const Tag = motion[as] || motion.div
  if (reduce) return <Tag className={className} {...rest}>{children}</Tag>
  return (
    <Tag
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -8% 0px' }}
      transition={{ duration: 0.7, delay, ease: EASE }}
      {...rest}
    >
      {children}
    </Tag>
  )
}
