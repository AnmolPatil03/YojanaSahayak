import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  ExternalLink,
  GitCompare,
  MapPin,
  MessageSquare,
  ShieldAlert,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Checklist } from '../components/Checklist'
import { EligibilityCard } from '../components/EligibilityCard'
import { PageTransition } from '../components/PageTransition'
import { SampleBadge } from '../components/SampleBadge'
import { EmptyState, ErrorState, Skeleton } from '../components/States'
import { ApiError, checkEligibility, getScheme } from '../lib/api'
import { compactProfile } from '../lib/format'
import type { MessageKey } from '../lib/i18n'
import { useCompare } from '../state/compare'
import { usePreferences } from '../state/preferences'
import { useProfile } from '../state/profile'
import { useToasts } from '../state/toasts'

type Tab = 'overview' | 'eligibility' | 'documents' | 'sources'
const TABS: { key: Tab; label: MessageKey }[] = [
  { key: 'overview', label: 'scheme.overview' },
  { key: 'eligibility', label: 'scheme.eligibility' },
  { key: 'documents', label: 'scheme.documents' },
  { key: 'sources', label: 'scheme.sources' },
]

export default function SchemeDetail() {
  const { id = '' } = useParams()
  const { t, language } = usePreferences()
  const { profile } = useProfile()
  const compare = useCompare()
  const { notify } = useToasts()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('overview')

  const scheme = useQuery({ queryKey: ['scheme', id], queryFn: () => getScheme(id) })
  const compact = compactProfile(profile)
  const eligibility = useQuery({
    queryKey: ['eligibility', id, compact],
    queryFn: () => checkEligibility(compact, [id]),
    enabled: Boolean(scheme.data?.rules_usable),
  })

  if (scheme.isPending) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-8">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-12 w-3/4" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (scheme.isError) {
    if (scheme.error instanceof ApiError && scheme.error.status === 404) {
      return (
        <EmptyState
          title={t('scheme.notFound')}
          action={
            <Link to="/schemes" className="btn-brand">
              {t('nav.explorer')}
            </Link>
          }
        />
      )
    }
    return <ErrorState onRetry={() => void scheme.refetch()} />
  }

  const data = scheme.data
  const name = data.names[language] ?? data.name
  const inCompare = compare.has(id)
  const result = eligibility.data?.results[0]
  const mainSections = data.sections.filter((s) =>
    ['overview', 'benefits', 'application', 'exclusions', 'faq', 'other'].includes(s.name),
  )
  const eligibilitySections = data.sections.filter((s) => s.name === 'eligibility')

  const toggleCompare = () => {
    if (!compare.toggle(id)) notify(t('compare.limit'))
  }

  return (
    <PageTransition>
      <div className="mx-auto max-w-4xl px-4 py-8">
        <Link to="/schemes" className="btn-ghost -ms-3 mb-4 text-sm">
          <ArrowLeft className="size-4" aria-hidden />
          {t('nav.explorer')}
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold">
            {data.category_label[language]}
          </span>
          <span className="inline-flex items-center gap-1 text-sm text-fg-muted">
            <MapPin className="size-4" aria-hidden />
            {data.state === 'ALL' ? t('scheme.national') : data.state}
          </span>
          {data.is_sample && <SampleBadge />}
        </div>
        <h1 className="mt-2 text-3xl font-extrabold leading-tight" lang={data.languages[0]}>
          {name}
        </h1>
        {data.ministry && <p className="mt-1 text-fg-muted">{data.ministry}</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={() =>
              navigate(`/chat?q=${encodeURIComponent(t('scheme.askPrompt', { name }))}`)
            }
          >
            <MessageSquare className="size-4" aria-hidden />
            {t('scheme.ask')}
          </button>
          <button
            type="button"
            className="btn-ghost border border-line"
            onClick={toggleCompare}
            aria-pressed={inCompare}
          >
            <GitCompare className="size-4" aria-hidden />
            {inCompare ? t('scheme.comparing') : t('scheme.compare')}
          </button>
        </div>

        <div
          className="no-print mt-8 flex gap-1 overflow-x-auto border-b border-line"
          role="tablist"
        >
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`tab-${key}`}
              aria-selected={tab === key}
              aria-controls={`panel-${key}`}
              onClick={() => setTab(key)}
              className={[
                'relative shrink-0 px-4 py-2.5 text-sm font-semibold transition-colors',
                tab === key ? 'text-fg' : 'text-fg-muted hover:text-fg',
              ].join(' ')}
            >
              {t(label)}
              {tab === key && (
                <motion.span
                  layoutId="scheme-tab"
                  className="absolute inset-x-2 -bottom-px h-[3px] rounded-full bg-accent"
                />
              )}
            </button>
          ))}
        </div>

        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          className="mt-6"
        >
          {tab === 'overview' && (
            <div className="space-y-4">
              {mainSections.map((section, index) => (
                <section
                  key={`${section.name}-${index}`}
                  className="card p-5"
                  lang={section.language}
                >
                  <h2 className="mb-2 text-lg font-bold">{section.label}</h2>
                  <SectionText text={section.text} />
                </section>
              ))}
            </div>
          )}
          {tab === 'eligibility' && (
            <div className="space-y-4">
              {data.rules_usable && result ? (
                <div>
                  <p className="mb-2 text-sm font-semibold text-fg-muted">
                    {t('scheme.checkWithProfile')}
                  </p>
                  <EligibilityCard result={{ ...result, scheme: data }} />
                </div>
              ) : (
                <p className="flex items-center gap-2 rounded-xl bg-accent-soft p-3 text-sm">
                  <ShieldAlert className="size-4" aria-hidden />
                  {data.rules ? t('scheme.rulesPending') : t('scheme.noRules')}
                </p>
              )}
              {eligibilitySections.map((section, index) => (
                <section key={index} className="card p-5" lang={section.language}>
                  <h2 className="mb-2 text-lg font-bold">{section.label}</h2>
                  <SectionText text={section.text} />
                </section>
              ))}
            </div>
          )}
          {tab === 'documents' && (
            <Checklist schemeId={id} schemeName={data.name} items={data.checklist} />
          )}
          {tab === 'sources' && (
            <ul className="space-y-2">
              {data.source_urls.map((url) => (
                <li key={url}>
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="card flex items-center gap-3 p-4 hover:bg-surface-2"
                  >
                    <ExternalLink className="size-4 shrink-0" aria-hidden />
                    <span className="break-all text-sm">{url}</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </motion.div>
      </div>
    </PageTransition>
  )
}

function SectionText({ text }: { text: string }) {
  const lines = text.split('\n').filter((line) => line.trim())
  const bullets = lines.filter((line) => /^\s*[-•*]\s+/.test(line))
  if (bullets.length >= Math.max(1, lines.length - 1)) {
    return (
      <ul className="list-disc space-y-1 ps-5">
        {lines.map((line, i) =>
          /^\s*[-•*]\s+/.test(line) ? (
            <li key={i}>{line.replace(/^\s*[-•*]\s+/, '')}</li>
          ) : (
            <p key={i} className="-ms-5 font-semibold">
              {line}
            </p>
          ),
        )}
      </ul>
    )
  }
  return (
    <div className="space-y-2 leading-relaxed">
      {lines.map((line, i) => (
        <p key={i}>{line}</p>
      ))}
    </div>
  )
}
