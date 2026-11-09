import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'framer-motion'
import { MapPin, ShieldCheck } from 'lucide-react'
import type { PointerEvent } from 'react'
import { Link } from 'react-router-dom'
import type { SchemeSummary } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { SampleBadge } from './SampleBadge'

/** Scheme card with a gentle 3D tilt that follows a mouse pointer (never touch). */
export function SchemeCard({ scheme }: { scheme: SchemeSummary }) {
  const { language, t } = usePreferences()
  const reduce = useReducedMotion()
  const px = useMotionValue(0)
  const py = useMotionValue(0)
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [5, -5]), { stiffness: 220, damping: 20 })
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-6, 6]), { stiffness: 220, damping: 20 })

  const onMove = (event: PointerEvent<HTMLDivElement>) => {
    if (reduce || event.pointerType !== 'mouse') return
    const rect = event.currentTarget.getBoundingClientRect()
    px.set((event.clientX - rect.left) / rect.width - 0.5)
    py.set((event.clientY - rect.top) / rect.height - 0.5)
  }
  const onLeave = () => {
    px.set(0)
    py.set(0)
  }

  const name = scheme.names?.[language] ?? scheme.name
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      style={{ rotateX, rotateY, transformPerspective: 900 }}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className="h-full"
    >
      <Link
        to={`/schemes/${scheme.scheme_id}`}
        className="card flex h-full flex-col gap-3 p-5 transition-shadow hover:shadow-xl"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold">
            {scheme.category_label[language]}
          </span>
          {scheme.is_sample && <SampleBadge />}
        </div>
        <h3 className="text-lg font-bold leading-snug" lang={scheme.languages[0]}>
          {name}
        </h3>
        {scheme.ministry && <p className="text-sm text-fg-muted">{scheme.ministry}</p>}
        <p className="line-clamp-3 text-sm leading-relaxed" lang={scheme.languages[0]}>
          {scheme.summary}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-3 pt-2 text-xs font-semibold text-fg-muted">
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3.5" aria-hidden />
            {scheme.state === 'ALL' ? t('scheme.national') : scheme.state}
          </span>
          {scheme.rules_reviewed && (
            <span className="inline-flex items-center gap-1">
              <ShieldCheck className="size-3.5" aria-hidden />
              {t('scheme.eligibility')}
            </span>
          )}
        </div>
      </Link>
    </motion.div>
  )
}
