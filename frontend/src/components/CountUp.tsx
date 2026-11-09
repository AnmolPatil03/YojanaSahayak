import { animate, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'

interface Props {
  value: number
  decimals?: number
  suffix?: string
  duration?: number
}

export function CountUp({ value, decimals = 0, suffix = '', duration = 0.9 }: Props) {
  const reduce = useReducedMotion()
  const [animated, setAnimated] = useState(0)

  useEffect(() => {
    if (reduce) return undefined
    const controls = animate(0, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: setAnimated,
    })
    return () => controls.stop()
  }, [value, duration, reduce])

  return (
    <span className="tabular-nums">
      {(reduce ? value : animated).toFixed(decimals)}
      {suffix}
    </span>
  )
}
