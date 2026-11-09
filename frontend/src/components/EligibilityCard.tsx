import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown, CircleHelp, ExternalLink, ShieldAlert, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { formatRupees } from '../lib/format'
import { FIELD_LABELS, VALUE_LABELS } from '../lib/i18n'
import type { Criterion, Language, ProfileField, SchemeEligibility } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { ProgressRing } from './ProgressRing'
import { SampleBadge } from './SampleBadge'

function StatusIcon({ status }: { status: Criterion['status'] }) {
  if (status === 'met') {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-on-accent">
        <Check className="size-3.5" strokeWidth={3} aria-hidden />
      </span>
    )
  }
  if (status === 'unmet') {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand">
        <X className="size-3.5" strokeWidth={3} aria-hidden />
      </span>
    )
  }
  return (
    <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-dashed border-fg-muted text-fg-muted">
      <CircleHelp className="size-3.5" aria-hidden />
    </span>
  )
}

function localizedExpected(criterion: Criterion, language: Language): string {
  if (language === 'en' || criterion.field === 'other') return criterion.expected
  const values = criterion.expected_values
  const field = criterion.field as ProfileField
  switch (field) {
    case 'age':
      return values.length === 2
        ? `${values[0]} से ${values[1]} वर्ष`
        : criterion.expected.startsWith('At least')
          ? `कम से कम ${values[0]} वर्ष`
          : `अधिकतम ${values[0]} वर्ष`
    case 'annual_family_income':
      return `अधिकतम ${formatRupees(Number(values[0]), 'hi')} प्रति वर्ष`
    case 'disability':
      return 'आवेदक दिव्यांग होना चाहिए'
    default: {
      const labels = values.map((v) => VALUE_LABELS[field]?.[String(v)]?.hi ?? String(v))
      return `इनमें से एक: ${labels.join(', ')}`
    }
  }
}

function criterionLabel(criterion: Criterion, language: Language): string {
  if (criterion.field in FIELD_LABELS)
    return FIELD_LABELS[criterion.field as ProfileField][language]
  return language === 'hi' ? 'अन्य शर्त' : criterion.label
}

interface Props {
  result: SchemeEligibility
  index?: number
  compact?: boolean
}

export function EligibilityCard({ result, index = 0, compact }: Props) {
  const { language, t } = usePreferences()
  const [open, setOpen] = useState(!compact && result.verdict !== 'ineligible')
  const eligible = result.verdict === 'eligible'
  const verdictLabel = t(`eligibility.${result.verdict === 'unknown' ? 'unknown' : result.verdict}`)
  const name = result.scheme?.names?.[language] ?? result.scheme?.name ?? result.scheme_name

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 8) * 0.06, type: 'spring', stiffness: 320, damping: 30 }}
      className={['card rounded-2xl p-4', eligible ? 'shimmer-border' : ''].join(' ')}
    >
      <div className="flex items-start gap-4">
        <ProgressRing
          value={result.total ? result.met / result.total : 0}
          highlight={eligible}
          label={t('eligibility.criteria', { met: result.met, total: result.total })}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={[
                'rounded-full px-2.5 py-0.5 text-xs font-bold',
                eligible
                  ? 'bg-accent text-on-accent'
                  : result.verdict === 'ineligible'
                    ? 'bg-brand text-on-brand'
                    : 'border border-line bg-surface-2 text-fg',
              ].join(' ')}
            >
              {verdictLabel}
            </span>
            {!result.rules_reviewed && (
              <span className="inline-flex items-center gap-1 text-xs text-fg-muted">
                <ShieldAlert className="size-3.5" aria-hidden />
                {t('eligibility.unreviewed')}
              </span>
            )}
            {result.scheme?.is_sample && <SampleBadge />}
          </div>
          <h3 className="mt-1 text-base font-bold leading-snug">
            <Link to={`/schemes/${result.scheme_id}`} className="rounded hover:underline">
              {name}
            </Link>
          </h3>
          <p className="text-sm text-fg-muted">
            {t('eligibility.criteria', { met: result.met, total: result.total })}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="btn-ghost mt-2 w-full justify-between px-2 py-1.5 text-sm"
        aria-expanded={open}
      >
        {open ? t('eligibility.hide') : t('eligibility.details')}
        <motion.span animate={{ rotate: open ? 180 : 0 }}>
          <ChevronDown className="size-4" aria-hidden />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            {result.criteria.map((criterion, i) => (
              <li
                key={`${criterion.field}-${i}`}
                className="flex gap-3 border-t border-line/70 py-2.5 text-sm"
              >
                <StatusIcon status={criterion.status} />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">
                    {criterionLabel(criterion, language)}
                    <span className="sr-only">
                      {': '}
                      {criterion.status === 'met'
                        ? t('eligibility.met')
                        : criterion.status === 'unmet'
                          ? t('eligibility.unmet')
                          : t('eligibility.notKnown')}
                    </span>
                  </p>
                  <p className="text-fg-muted">
                    {criterion.resolvable
                      ? `${t('eligibility.required')}: `
                      : `${t('eligibility.manual')}: `}
                    {localizedExpected(criterion, language)}
                  </p>
                  {criterion.actual && (
                    <p className="text-fg-muted">
                      {t('eligibility.you')}: {criterion.actual}
                    </p>
                  )}
                </div>
                {criterion.source?.source_url && (
                  <a
                    href={criterion.source.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="self-start rounded-md p-1 text-fg-muted hover:text-fg"
                    title={criterion.source.text}
                    aria-label={t('citation.visit')}
                  >
                    <ExternalLink className="size-4" aria-hidden />
                  </a>
                )}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.article>
  )
}
