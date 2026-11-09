import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Activity, Cpu, Gauge, Lock, Quote, Timer } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CountUp } from '../components/CountUp'
import { PageTransition } from '../components/PageTransition'
import { EmptyState, Skeleton } from '../components/States'
import { useThemeColors } from '../hooks/useThemeColors'
import { ApiError, getLatestEval, getProviders } from '../lib/api'
import type { EvalReport, ProviderStatus } from '../lib/types'
import { usePreferences } from '../state/preferences'

const RECALL_KEYS = ['recall@1', 'recall@3', 'recall@5', 'recall@10']

function StatTile({
  icon: Icon,
  label,
  value,
  decimals = 2,
  suffix = '',
  index,
}: {
  icon: typeof Activity
  label: string
  value: number | null | undefined
  decimals?: number
  suffix?: string
  index: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className="card p-4"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </p>
      <p className="mt-2 text-2xl font-extrabold">
        {value === null || value === undefined ? (
          '-'
        ) : (
          <CountUp value={value} decimals={decimals} suffix={suffix} />
        )}
      </p>
    </motion.div>
  )
}

function StatusDot({ status }: { status: ProviderStatus['status'] }) {
  const tone = status === 'ok' ? 'bg-brand' : status === 'cooldown' ? 'bg-accent' : 'bg-fg-muted/50'
  return (
    <span className="relative flex size-3 shrink-0" aria-hidden>
      {status === 'ok' && (
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand opacity-40" />
      )}
      <span className={`relative inline-flex size-3 rounded-full ${tone}`} />
    </span>
  )
}

function ProviderRow({ provider, elapsed }: { provider: ProviderStatus; elapsed: number }) {
  const { t } = usePreferences()
  const remaining = Math.max(0, Math.round(provider.cooldown_seconds - elapsed))
  const status = provider.status === 'cooldown' && remaining === 0 ? 'ok' : provider.status
  return (
    <li className="flex flex-wrap items-center gap-3 border-t border-line py-3 first:border-t-0">
      <StatusDot status={status} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-semibold">
          {provider.label}
          {provider.offline && <Cpu className="size-3.5 text-fg-muted" aria-label="offline" />}
          {provider.trains_on_free_tier_data && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-fg-muted"
              title={t('insights.privacy')}
            >
              <Lock className="size-3" aria-hidden />
              {t('insights.privacy')}
            </span>
          )}
        </p>
        <p className="truncate text-xs text-fg-muted">{provider.model}</p>
      </div>
      <div className="text-end text-sm">
        <p className="font-semibold">
          {status === 'cooldown'
            ? t('insights.cooldown', { seconds: remaining })
            : t(`insights.status.${status}`)}
        </p>
        <p className="text-xs text-fg-muted">
          {provider.usage_today.requests}
          {provider.limits.rpd ? ` / ${provider.limits.rpd}` : ''} {t('insights.requestsToday')}
        </p>
      </div>
    </li>
  )
}

function Providers() {
  const { t } = usePreferences()
  const query = useQuery({
    queryKey: ['providers'],
    queryFn: getProviders,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  })
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 1000)
    return () => {
      window.clearInterval(timer)
      setElapsed(0)
    }
  }, [query.dataUpdatedAt])

  return (
    <section className="card p-5" aria-labelledby="providers-title">
      <h2 id="providers-title" className="mb-2 flex items-center gap-2 text-lg font-bold">
        <Activity className="size-5" aria-hidden />
        {t('insights.providers')}
      </h2>
      {query.isPending ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : query.isError ? (
        <p className="text-sm text-fg-muted">{t('error.body')}</p>
      ) : (
        <ul aria-live="polite">
          {query.data.providers.map((provider) => (
            <ProviderRow key={provider.name} provider={provider} elapsed={elapsed} />
          ))}
        </ul>
      )}
    </section>
  )
}

function Charts({ report }: { report: EvalReport }) {
  const { t } = usePreferences()
  const colors = useThemeColors()
  const ok = report.runs.filter((run) => run.status === 'ok')
  const skipped = report.runs.filter((run) => run.status !== 'ok')
  const bars = ok.map((run) => ({ name: run.label, ...run.retrieval }))
  const axis = { stroke: colors.muted, fontSize: 12 }
  const tooltip = {
    contentStyle: {
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      color: 'var(--fg)',
    },
  }

  return (
    <div className="space-y-6">
      <section className="card p-5" aria-labelledby="retrieval-title">
        <h2 id="retrieval-title" className="mb-4 text-lg font-bold">
          {t('insights.retrieval')}
        </h2>
        {ok.length > 0 && (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={false} interval={0} />
                <YAxis domain={[0, 1]} tick={axis} tickLine={false} axisLine={false} />
                <Tooltip {...tooltip} cursor={{ fill: colors.grid }} />
                <Legend itemSorter={null} wrapperStyle={{ fontSize: 12, color: colors.fg }} />
                {RECALL_KEYS.map((key, index) => (
                  <Bar
                    key={key}
                    dataKey={key}
                    fill={colors.series[index]}
                    radius={[6, 6, 0, 0]}
                    animationDuration={900}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {ok.length > 1 && (
          <div className="mt-6 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={bars} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={false} />
                <YAxis domain={[0, 1]} tick={axis} tickLine={false} axisLine={false} />
                <Tooltip {...tooltip} />
                <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="mrr" stroke={colors.fg} strokeWidth={2.5} dot />
                <Line
                  type="monotone"
                  dataKey="ndcg@5"
                  stroke={colors.accent}
                  strokeWidth={2.5}
                  dot
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {skipped.length > 0 && (
          <ul className="mt-4 space-y-1 text-sm text-fg-muted">
            {skipped.map((run) => (
              <li key={run.name}>
                <span className="font-semibold text-fg">{run.label}</span>: {run.reason}
              </li>
            ))}
          </ul>
        )}
      </section>

      {report.abstention && (
        <section className="card p-5" aria-labelledby="abstention-title">
          <h2 id="abstention-title" className="mb-4 text-lg font-bold">
            {t('insights.abstention')}
          </h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={report.abstention.sweep}
                margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
              >
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis dataKey="threshold" tick={axis} tickLine={false} axisLine={false} />
                <YAxis domain={[0, 1]} tick={axis} tickLine={false} axisLine={false} />
                <Tooltip {...tooltip} />
                <Line
                  type="monotone"
                  dataKey="balanced"
                  stroke={colors.fg}
                  strokeWidth={2.5}
                  dot={false}
                />
                {report.abstention.recommended_threshold !== null && (
                  <ReferenceLine
                    x={report.abstention.recommended_threshold}
                    stroke={colors.accent}
                    strokeWidth={2}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {report.notes.length > 0 && (
        <ul className="list-disc space-y-1 ps-5 text-sm text-fg-muted">
          {report.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function Insights() {
  const { t } = usePreferences()
  const report = useQuery({ queryKey: ['eval'], queryFn: getLatestEval, retry: false })
  const data = report.data
  const ok = data?.runs.filter((run) => run.status === 'ok') ?? []
  const best = (key: string) =>
    ok.length ? Math.max(...ok.map((run) => run.retrieval[key] ?? 0)) : null
  const generation = data?.generation?.status === 'ok' ? data.generation : null

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        <div>
          <h1 className="text-3xl font-extrabold">{t('insights.title')}</h1>
          {data && (
            <p className="mt-1 text-sm text-fg-muted">
              {data.example ? `${t('insights.example')} · ` : ''}
              {data.questions} {t('insights.questions')} ·{' '}
              {new Date(data.created_at).toLocaleString()}
            </p>
          )}
        </div>
        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          <div className="space-y-6">
            {report.isPending ? (
              <Skeleton className="h-80" />
            ) : report.isError ? (
              <EmptyState
                title={
                  report.error instanceof ApiError && report.error.status === 404
                    ? t('insights.noReport')
                    : t('error.title')
                }
              />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  <StatTile index={0} icon={Gauge} label="Recall@5" value={best('recall@5')} />
                  <StatTile index={1} icon={Gauge} label="MRR" value={best('mrr')} />
                  <StatTile index={2} icon={Gauge} label="nDCG@5" value={best('ndcg@5')} />
                  <StatTile
                    index={3}
                    icon={Quote}
                    label={t('insights.faithfulness')}
                    value={generation?.faithfulness}
                  />
                  <StatTile
                    index={4}
                    icon={Quote}
                    label={t('insights.citationPrecision')}
                    value={generation?.citation_precision}
                  />
                  <StatTile
                    index={5}
                    icon={Timer}
                    label={`${t('insights.latency')} p50`}
                    value={generation?.latency ? generation.latency.p50_ms / 1000 : null}
                    decimals={1}
                    suffix=" s"
                  />
                </div>
                {data && <Charts report={data} />}
              </>
            )}
          </div>
          <div>
            <Providers />
          </div>
        </div>
      </div>
    </PageTransition>
  )
}
