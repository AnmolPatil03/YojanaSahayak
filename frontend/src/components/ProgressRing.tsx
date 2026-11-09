import { motion, useReducedMotion } from 'framer-motion'
import { CountUp } from './CountUp'

interface Props {
  value: number
  size?: number
  label: string
  highlight?: boolean
}

/** Animated ring showing the share of criteria met, with a counting percentage. */
export function ProgressRing({ value, size = 64, label, highlight }: Props) {
  const reduce = useReducedMotion()
  const stroke = 6
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(1, value))
  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={label}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-surface-2"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          className={highlight ? 'stroke-accent' : 'stroke-brand'}
          initial={{ strokeDashoffset: reduce ? circumference * (1 - clamped) : circumference }}
          animate={{ strokeDashoffset: circumference * (1 - clamped) }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center text-sm font-bold"
        aria-hidden
      >
        <CountUp value={Math.round(clamped * 100)} suffix="%" />
      </span>
    </div>
  )
}
