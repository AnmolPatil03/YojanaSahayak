import { motion } from 'framer-motion'
import { Check, ExternalLink, Printer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { readStored, writeStored } from '../lib/storage'
import type { ChecklistItem } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { EmptyState } from './States'

interface Props {
  schemeId: string
  schemeName: string
  items: ChecklistItem[]
}

/** Documents list with persistent ticks, an animated strike-through and a print view. */
export function Checklist({ schemeId, schemeName, items }: Props) {
  const { t } = usePreferences()
  const key = `checklist.${schemeId}`
  const [done, setDone] = useState<string[]>(() => readStored(key, []))

  useEffect(() => writeStored(key, done), [key, done])

  if (!items.length) {
    return <EmptyState illustration="documents" title={t('checklist.empty')} />
  }

  const toggle = (id: string) =>
    setDone((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    )
  const count = items.filter((item) => done.includes(item.id)).length
  const progress = count / items.length

  return (
    <section aria-labelledby="checklist-title">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 id="checklist-title" className="text-lg font-bold">
          {t('checklist.title')}
        </h2>
        <span className="print-only text-sm">{schemeName}</span>
        <button type="button" onClick={() => window.print()} className="btn-ghost no-print ms-auto">
          <Printer className="size-4" aria-hidden />
          {t('checklist.print')}
        </button>
      </div>
      <div
        className="no-print mb-1 flex items-center justify-between text-sm text-fg-muted"
        aria-live="polite"
      >
        <span>{t('checklist.progress', { done: count, total: items.length })}</span>
        <span className="tabular-nums">{Math.round(progress * 100)}%</span>
      </div>
      <div className="no-print mb-4 h-2 overflow-hidden rounded-full bg-surface-2">
        <motion.div
          className="h-full rounded-full bg-accent"
          initial={false}
          animate={{ width: `${progress * 100}%` }}
          transition={{ type: 'spring', stiffness: 200, damping: 26 }}
        />
      </div>
      <ul className="space-y-2">
        {items.map((item) => {
          const checked = done.includes(item.id)
          return (
            <li key={item.id} className="card flex items-center gap-3 p-3">
              <label className="flex flex-1 cursor-pointer items-center gap-3">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(item.id)}
                  className="peer sr-only"
                />
                <span
                  className={[
                    'flex size-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors peer-focus-visible:ring-4 peer-focus-visible:ring-accent',
                    checked ? 'border-accent bg-accent text-on-accent' : 'border-line',
                  ].join(' ')}
                  aria-hidden
                >
                  {checked && (
                    <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }}>
                      <Check className="size-4" strokeWidth={3} />
                    </motion.span>
                  )}
                </span>
                <span
                  className={['strike', checked ? 'text-fg-muted' : ''].join(' ')}
                  data-done={checked}
                  lang={item.language}
                >
                  {item.text}
                </span>
              </label>
              <a
                href={item.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="no-print rounded-md p-1 text-fg-muted hover:text-fg"
                aria-label={t('citation.visit')}
                title={item.page ? t('citation.page', { page: item.page }) : t('citation.source')}
              >
                <ExternalLink className="size-4" aria-hidden />
              </a>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
