import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink, FileText, X } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import type { Citation } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { SampleBadge } from './SampleBadge'

interface Props {
  citation: Citation | null
  context: string
  onClose: () => void
}

function words(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/\[\d+\]/g, ' ')
      .split(/[^\p{L}\p{M}\p{N}]+/u)
      .filter((w) => w.length > 2),
  )
}

/** Split a chunk into lines/sentences and mark the one closest to the cited claim. */
function highlight(text: string, context: string): { part: string; hit: boolean }[] {
  const parts = text.split(/(?<=[.!?।])\s+|\n/).filter((p) => p.trim())
  const claim = words(context)
  let best = -1
  let bestScore = 0
  parts.forEach((part, index) => {
    const overlap = [...words(part)].filter((w) => claim.has(w)).length
    if (overlap > bestScore) {
      best = index
      bestScore = overlap
    }
  })
  return parts.map((part, index) => ({ part, hit: index === best }))
}

export function CitationDrawer({ citation, context, onClose }: Props) {
  const { t } = usePreferences()
  const closeRef = useRef<HTMLButtonElement>(null)
  const pieces = useMemo(
    () => (citation ? highlight(citation.text, context) : []),
    [citation, context],
  )

  useEffect(() => {
    if (!citation) return undefined
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [citation, onClose])

  return (
    <AnimatePresence>
      {citation && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-teal/30 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="citation-title"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line bg-surface shadow-2xl"
          >
            <div className="flex items-start gap-3 border-b border-line p-5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-sm font-bold text-on-accent">
                {citation.n}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
                  {t('citation.source')}
                  {citation.page ? ` · ${t('citation.page', { page: citation.page })}` : ''}
                </p>
                <h2 id="citation-title" className="text-lg font-bold leading-snug">
                  {citation.scheme_name}
                </h2>
                <p className="mt-0.5 flex items-center gap-1.5 text-sm text-fg-muted">
                  <FileText className="size-4" aria-hidden />
                  {citation.section_label}
                </p>
                {citation.is_sample && <SampleBadge className="mt-2" />}
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                className="btn-ghost p-2"
                aria-label={t('citation.close')}
              >
                <X className="size-5" aria-hidden />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5" lang={citation.language}>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">
                {t('citation.passage')}
              </p>
              <div className="space-y-2 leading-relaxed">
                {pieces.map(({ part, hit }, index) =>
                  hit ? (
                    <motion.mark
                      key={index}
                      initial={{ backgroundSize: '0% 100%' }}
                      animate={{ backgroundSize: '100% 100%' }}
                      transition={{ duration: 0.6, delay: 0.25 }}
                      className="block rounded-md bg-gradient-to-r from-accent to-accent bg-no-repeat px-1.5 py-0.5 text-on-accent"
                    >
                      {part}
                    </motion.mark>
                  ) : (
                    <p key={index}>{part}</p>
                  ),
                )}
              </div>
            </div>
            <div className="border-t border-line p-5">
              <a
                href={citation.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="btn-brand w-full"
              >
                <ExternalLink className="size-4" aria-hidden />
                {t('citation.visit')}
              </a>
              <p className="mt-2 truncate text-center text-xs text-fg-muted">
                {citation.source_url}
              </p>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
