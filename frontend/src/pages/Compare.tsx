import { useQueries, useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageTransition } from '../components/PageTransition'
import { SampleBadge } from '../components/SampleBadge'
import { EmptyState, Skeleton } from '../components/States'
import { getScheme, listSchemes } from '../lib/api'
import { formatRupees } from '../lib/format'
import { VALUE_LABELS } from '../lib/i18n'
import type { MessageKey } from '../lib/i18n'
import type { Language, SchemeDetail } from '../lib/types'
import { COMPARE_LIMIT, useCompare } from '../state/compare'
import { usePreferences } from '../state/preferences'

type Row = { key: MessageKey; value: (s: SchemeDetail, language: Language) => string }

function firstLines(text: string, count = 3): string {
  return text
    .split('\n')
    .map((line) => line.replace(/^\s*[-•*]\s+/, '').trim())
    .filter(Boolean)
    .slice(0, count)
    .join('\n')
}

const ROWS: Row[] = [
  { key: 'compare.row.ministry', value: (s) => s.ministry ?? '-' },
  {
    key: 'compare.row.state',
    value: (s, l) => (s.state === 'ALL' ? (l === 'hi' ? 'पूरे भारत में' : 'All India') : s.state),
  },
  { key: 'compare.row.category', value: (s, l) => s.category_label[l] },
  {
    key: 'compare.row.benefits',
    value: (s) =>
      firstLines(
        s.sections
          .filter((x) => x.name === 'benefits')
          .map((x) => x.text)
          .join('\n'),
      ) || '-',
  },
  {
    key: 'compare.row.age',
    value: (s) => {
      const low = s.rules?.rules.min_age.value
      const high = s.rules?.rules.max_age.value
      if (low == null && high == null) return '-'
      if (low != null && high != null) return `${low} – ${high}`
      return low != null ? `≥ ${low}` : `≤ ${high}`
    },
  },
  {
    key: 'compare.row.income',
    value: (s, l) => {
      const limit = s.rules?.rules.max_annual_family_income.value
      return limit == null ? '-' : `≤ ${formatRupees(limit, l)}`
    },
  },
  {
    key: 'compare.row.groups',
    value: (s, l) => {
      const rules = s.rules?.rules
      if (!rules) return '-'
      const parts: string[] = []
      const add = (field: string, values: string[] | null) =>
        values?.forEach((v) => parts.push(VALUE_LABELS[field]?.[v]?.[l] ?? v))
      add('gender', rules.genders.value)
      add('social_category', rules.social_categories.value)
      add('occupation', rules.occupations.value)
      add('education_level', rules.education_levels.value)
      if (rules.disability_required.value)
        parts.push(l === 'hi' ? 'दिव्यांगजन' : 'Persons with disabilities')
      if (rules.residence.value)
        parts.push(VALUE_LABELS.residence[rules.residence.value]?.[l] ?? rules.residence.value)
      return parts.join(', ') || '-'
    },
  },
  { key: 'compare.row.documents', value: (s) => s.checklist.map((c) => c.text).join('\n') || '-' },
]

export default function Compare() {
  const { t, language } = usePreferences()
  const { ids, remove, toggle } = useCompare()
  const [adding, setAdding] = useState(false)
  const schemes = useQueries({
    queries: ids.map((id) => ({ queryKey: ['scheme', id], queryFn: () => getScheme(id) })),
  })
  const all = useQuery({
    queryKey: ['schemes', 'all'],
    queryFn: () => listSchemes({}),
    enabled: adding,
  })

  if (!ids.length && !adding) {
    return (
      <PageTransition>
        <EmptyState
          illustration="compare"
          title={t('compare.empty.title')}
          body={t('compare.empty.body')}
          action={
            <Link to="/schemes" className="btn-brand">
              {t('nav.explorer')}
            </Link>
          }
        />
      </PageTransition>
    )
  }

  const loaded = schemes.map((q) => q.data).filter((s): s is SchemeDetail => Boolean(s))
  const count = Math.max(ids.length, 1)
  const columns = `minmax(7rem, 11rem) repeat(${count}, minmax(13rem, 1fr))`
  const minWidth = `${7 + count * 13 + count * 0.75}rem`

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-extrabold">{t('compare.title')}</h1>
          {ids.length < COMPARE_LIMIT && (
            <button
              type="button"
              className="btn-ghost ms-auto border border-line"
              onClick={() => setAdding((v) => !v)}
              aria-expanded={adding}
            >
              <Plus className="size-4" aria-hidden />
              {t('compare.add')}
            </button>
          )}
        </div>
        <AnimatePresence>
          {adding && (
            <motion.ul
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-3 flex flex-wrap gap-2 overflow-hidden"
            >
              {(all.data?.items ?? [])
                .filter((s) => !ids.includes(s.scheme_id))
                .map((s) => (
                  <li key={s.scheme_id}>
                    <button
                      type="button"
                      className="chip"
                      onClick={() => {
                        toggle(s.scheme_id)
                        setAdding(false)
                      }}
                    >
                      <Plus className="size-3.5" aria-hidden />
                      {s.names[language] ?? s.name}
                    </button>
                  </li>
                ))}
            </motion.ul>
          )}
        </AnimatePresence>

        <div className="mt-6 overflow-x-auto pb-2">
          <div
            className="grid gap-x-3"
            style={{ gridTemplateColumns: columns, minWidth }}
            role="table"
          >
            <div role="row" className="contents">
              <div role="columnheader" />
              {ids.map((id, index) => {
                const scheme = schemes[index]?.data
                return (
                  <motion.div
                    key={id}
                    role="columnheader"
                    initial={{ opacity: 0, x: 30 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{
                      delay: index * 0.08,
                      type: 'spring',
                      stiffness: 300,
                      damping: 30,
                    }}
                    className="card mb-3 p-4"
                  >
                    {scheme ? (
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          <Link
                            to={`/schemes/${id}`}
                            className="font-bold leading-snug hover:underline"
                          >
                            {scheme.names[language] ?? scheme.name}
                          </Link>
                          {scheme.is_sample && <SampleBadge className="mt-1" />}
                        </div>
                        <button
                          type="button"
                          onClick={() => remove(id)}
                          className="btn-ghost p-1.5"
                          aria-label={t('compare.remove')}
                        >
                          <X className="size-4" aria-hidden />
                        </button>
                      </div>
                    ) : (
                      <Skeleton className="h-6 w-full" />
                    )}
                  </motion.div>
                )
              })}
            </div>
            {ROWS.map((row) => {
              const values = loaded.map((s) => row.value(s, language))
              const differs = loaded.length > 1 && new Set(values).size > 1
              return (
                <div role="row" key={row.key} className="group contents">
                  <div
                    role="rowheader"
                    className="border-t border-line py-3 pe-2 text-sm font-semibold"
                  >
                    {t(row.key)}
                    {differs && (
                      <span className="ms-2 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase text-on-accent">
                        {t('compare.differs')}
                      </span>
                    )}
                  </div>
                  {ids.map((id, index) => {
                    const scheme = schemes[index]?.data
                    return (
                      <div
                        role="cell"
                        key={id}
                        className={[
                          'whitespace-pre-line border-t border-line px-3 py-3 text-sm transition-colors',
                          differs ? 'bg-surface' : '',
                        ].join(' ')}
                      >
                        {scheme ? row.value(scheme, language) : <Skeleton className="h-4 w-2/3" />}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </PageTransition>
  )
}
