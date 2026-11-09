import { motion } from 'framer-motion'
import { RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import { usePreferences } from '../state/preferences'

type Illustration = 'search' | 'documents' | 'compare' | 'chat' | 'error'

function Art({ kind }: { kind: Illustration }) {
  return (
    <svg viewBox="0 0 160 120" className="mx-auto h-28 w-auto" aria-hidden>
      <ellipse cx="80" cy="104" rx="52" ry="8" className="fill-surface-2" />
      {kind === 'search' && (
        <>
          <rect
            x="34"
            y="24"
            width="64"
            height="74"
            rx="10"
            className="fill-surface stroke-line"
            strokeWidth="2"
          />
          <rect x="44" y="38" width="40" height="6" rx="3" className="fill-brand-soft" />
          <rect x="44" y="52" width="30" height="6" rx="3" className="fill-brand-soft" />
          <circle cx="104" cy="66" r="18" className="fill-none stroke-brand" strokeWidth="6" />
          <path d="M117 79l14 14" className="stroke-brand" strokeWidth="7" strokeLinecap="round" />
          <circle cx="104" cy="66" r="6" className="fill-marigold" />
        </>
      )}
      {kind === 'documents' && (
        <>
          <rect
            x="46"
            y="18"
            width="62"
            height="80"
            rx="10"
            className="fill-surface stroke-line"
            strokeWidth="2"
          />
          {[34, 50, 66].map((y) => (
            <g key={y}>
              <rect x="56" y={y} width="10" height="10" rx="3" className="fill-marigold" />
              <rect x="72" y={y + 2} width="26" height="6" rx="3" className="fill-brand-soft" />
            </g>
          ))}
        </>
      )}
      {kind === 'compare' && (
        <>
          <rect
            x="26"
            y="26"
            width="46"
            height="70"
            rx="10"
            className="fill-surface stroke-line"
            strokeWidth="2"
          />
          <rect
            x="88"
            y="26"
            width="46"
            height="70"
            rx="10"
            className="fill-surface stroke-line"
            strokeWidth="2"
          />
          <path
            d="M72 50h16M84 44l6 6-6 6"
            className="fill-none stroke-brand"
            strokeWidth="4"
            strokeLinecap="round"
          />
          <circle cx="111" cy="78" r="7" className="fill-marigold" />
        </>
      )}
      {kind === 'chat' && (
        <>
          <rect x="22" y="22" width="78" height="44" rx="14" className="fill-brand" />
          <rect
            x="58"
            y="56"
            width="80"
            height="40"
            rx="14"
            className="fill-surface stroke-line"
            strokeWidth="2"
          />
          <circle cx="82" cy="76" r="4" className="fill-marigold" />
          <circle cx="98" cy="76" r="4" className="fill-marigold" />
          <circle cx="114" cy="76" r="4" className="fill-marigold" />
        </>
      )}
      {kind === 'error' && (
        <>
          <circle cx="80" cy="58" r="36" className="fill-surface stroke-line" strokeWidth="2" />
          <path d="M80 38v26" className="stroke-brand" strokeWidth="7" strokeLinecap="round" />
          <circle cx="80" cy="76" r="5" className="fill-marigold" />
        </>
      )}
    </svg>
  )
}

interface StateProps {
  title: string
  body?: string
  illustration?: Illustration
  action?: ReactNode
}

export function EmptyState({ title, body, illustration = 'search', action }: StateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto max-w-md py-12 text-center"
    >
      <Art kind={illustration} />
      <h2 className="mt-4 text-lg font-bold">{title}</h2>
      {body && <p className="mt-1 text-fg-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </motion.div>
  )
}

export function ErrorState({
  onRetry,
  title,
  body,
}: {
  onRetry?: () => void
  title?: string
  body?: string
}) {
  const { t } = usePreferences()
  return (
    <EmptyState
      illustration="error"
      title={title ?? t('error.title')}
      body={body ?? t('error.body')}
      action={
        onRetry && (
          <button type="button" onClick={onRetry} className="btn-brand">
            <RotateCcw className="size-4" aria-hidden />
            {t('common.retry')}
          </button>
        )
      }
    />
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} aria-hidden />
}
