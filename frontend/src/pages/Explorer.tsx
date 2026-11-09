import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AnimatePresence, LayoutGroup, motion } from 'framer-motion'
import { Search } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { PageTransition } from '../components/PageTransition'
import { SchemeCard } from '../components/SchemeCard'
import { EmptyState, ErrorState, Skeleton } from '../components/States'
import { useDebounced } from '../hooks/useDebounced'
import { listSchemes } from '../lib/api'
import { usePreferences } from '../state/preferences'

export default function Explorer() {
  const { t, language } = usePreferences()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const state = params.get('state') ?? ''
  const category = params.get('category') ?? ''
  const debouncedQ = useDebounced(q)

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const query = useQuery({
    queryKey: ['schemes', debouncedQ, state, category],
    queryFn: () => listSchemes({ q: debouncedQ, state, category }),
    placeholderData: keepPreviousData,
  })
  const facets = useQuery({ queryKey: ['schemes', 'facets'], queryFn: () => listSchemes({}) })
  const categories = facets.data?.facets.categories ?? []
  const states = (facets.data?.facets.states ?? []).filter((s) => s !== 'ALL')

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-3xl font-extrabold">{t('explorer.title')}</h1>
        <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto]">
          <label className="card search-shell flex items-center gap-2 px-4">
            <Search className="size-5 text-fg-muted" aria-hidden />
            <span className="sr-only">{t('explorer.search')}</span>
            <input
              value={q}
              onChange={(event) => update('q', event.target.value)}
              placeholder={t('explorer.search')}
              className="min-w-0 flex-1 bg-transparent py-3 placeholder:text-fg-muted focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="sr-only">{t('compare.row.state')}</span>
            <select
              value={state}
              onChange={(event) => update('state', event.target.value)}
              className="field h-full min-h-12 md:w-56"
            >
              <option value="">{t('explorer.allStates')}</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div
          className="mt-3 flex flex-wrap gap-2"
          role="group"
          aria-label={t('compare.row.category')}
        >
          {[
            {
              key: '',
              label: { en: t('explorer.allCategories'), hi: t('explorer.allCategories') },
            },
            ...categories,
          ].map((option) => {
            const active = category === option.key
            return (
              <button
                key={option.key || 'all'}
                type="button"
                onClick={() => update('category', option.key)}
                aria-pressed={active}
                className={[
                  'relative rounded-full px-3.5 py-1.5 text-sm font-semibold transition-colors',
                  active ? 'text-on-accent' : 'border border-line bg-surface hover:bg-surface-2',
                ].join(' ')}
              >
                {active && (
                  <motion.span
                    layoutId="category-pill"
                    className="absolute inset-0 rounded-full bg-accent"
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <span className="relative">{option.label[language]}</span>
              </button>
            )
          })}
        </div>
        <p className="mt-4 text-sm text-fg-muted" aria-live="polite">
          {query.data ? t('explorer.count', { count: query.data.total }) : ' '}
        </p>

        {query.isError ? (
          <ErrorState onRetry={() => void query.refetch()} />
        ) : query.isPending ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-56" />
            ))}
          </div>
        ) : query.data.items.length === 0 ? (
          facets.data?.total === 0 ? (
            <EmptyState title={t('explorer.none.title')} body={t('explorer.none.body')} />
          ) : (
            <EmptyState title={t('explorer.empty.title')} body={t('explorer.empty.body')} />
          )
        ) : (
          <LayoutGroup>
            <motion.div layout className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <AnimatePresence mode="popLayout">
                {query.data.items.map((scheme) => (
                  <SchemeCard key={scheme.scheme_id} scheme={scheme} />
                ))}
              </AnimatePresence>
            </motion.div>
          </LayoutGroup>
        )}
      </div>
    </PageTransition>
  )
}
