import { AnimatePresence, motion } from 'framer-motion'
import { Cpu, Database, Zap } from 'lucide-react'
import type { ProviderInfo } from '../lib/types'
import { usePreferences } from '../state/preferences'

/** Shows which provider answered; morphs when the gateway fails over. */
export function ProviderPill({ provider, id }: { provider?: ProviderInfo; id: string }) {
  const { t } = usePreferences()
  if (!provider) return null
  const Icon = provider.cached ? Database : provider.offline ? Cpu : Zap
  return (
    <motion.span
      layout
      layoutId={`provider-${id}`}
      className="inline-flex items-center gap-1.5 overflow-hidden rounded-full border border-line bg-surface-2 px-2.5 py-1 text-xs font-semibold text-fg"
      transition={{ type: 'spring', stiffness: 500, damping: 35 }}
      title={provider.model || provider.label}
    >
      <Icon className="size-3.5" aria-hidden />
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={provider.name}
          initial={{ y: 10, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -10, opacity: 0 }}
          transition={{ duration: 0.25 }}
        >
          {provider.label}
          {provider.cached ? ` · ${t('chat.cached')}` : ''}
        </motion.span>
      </AnimatePresence>
    </motion.span>
  )
}
