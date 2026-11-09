import { motion, useReducedMotion } from 'framer-motion'
import { formatMs } from '../lib/format'
import { STAGES } from '../lib/i18n'
import type { StageName, StageState } from '../lib/types'
import { usePreferences } from '../state/preferences'

function Check() {
  const reduce = useReducedMotion()
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" aria-hidden>
      <motion.path
        d="M5 12.5l4.5 4.5L19 7.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: reduce ? 1 : 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      />
    </svg>
  )
}

/** Horizontal stepper driven by the server's `stage` events. */
export function PipelineTracker({ stages }: { stages: Record<StageName, StageState> }) {
  const { t } = usePreferences()
  const visible = STAGES.filter((stage) => stages[stage].status !== 'skipped')
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs" aria-label="Progress">
      {visible.map((stage, index) => {
        const state = stages[stage]
        const active = state.status === 'active'
        const done = state.status === 'done'
        return (
          <li key={stage} className="flex items-center gap-1">
            <span
              className={[
                'relative flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-semibold transition-colors duration-300',
                done
                  ? 'border-transparent bg-brand text-on-brand'
                  : active
                    ? 'border-transparent bg-accent text-on-accent'
                    : 'border-line text-fg-muted',
              ].join(' ')}
              aria-current={active ? 'step' : undefined}
            >
              {active && (
                <motion.span
                  className="absolute inset-0 rounded-full bg-accent"
                  initial={{ opacity: 0.5, scale: 1 }}
                  animate={{ opacity: 0, scale: 1.35 }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'easeOut' }}
                  aria-hidden
                />
              )}
              {done ? (
                <Check />
              ) : (
                <span
                  className={[
                    'size-1.5 rounded-full',
                    active ? 'bg-on-accent' : 'bg-fg-muted/50',
                  ].join(' ')}
                  aria-hidden
                />
              )}
              <span className="relative">{t(`stage.${stage}`)}</span>
              {done && state.ms !== undefined && (
                <span className="relative font-normal opacity-80">{formatMs(state.ms)}</span>
              )}
            </span>
            {index < visible.length - 1 && (
              <span
                className={['h-px w-3 transition-colors', done ? 'bg-brand' : 'bg-line'].join(' ')}
                aria-hidden
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}
