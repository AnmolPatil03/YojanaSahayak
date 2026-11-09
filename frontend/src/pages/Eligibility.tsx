import { useMutation } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ClipboardCheck, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { EligibilityCard } from '../components/EligibilityCard'
import { PageTransition } from '../components/PageTransition'
import { QuickReplies } from '../components/QuickReplies'
import { EmptyState, ErrorState } from '../components/States'
import { checkEligibility } from '../lib/api'
import { compactProfile } from '../lib/format'
import { FIELD_LABELS, STATES, VALUE_LABELS } from '../lib/i18n'
import type { ProfileField, QuickReply, UserProfile, Verdict } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { useProfile } from '../state/profile'

const CHOICE_FIELDS: ProfileField[] = [
  'gender',
  'social_category',
  'occupation',
  'education_level',
  'residence',
]
const GROUPS: Verdict[] = ['eligible', 'partial', 'unknown', 'ineligible']

export default function Eligibility() {
  const { t, language } = usePreferences()
  const { profile, replace } = useProfile()
  const [draft, setDraft] = useState<UserProfile>(profile)
  const [asked, setAsked] = useState<string[]>([])
  const mutation = useMutation({
    mutationFn: (input: { profile: UserProfile; asked: string[] }) =>
      checkEligibility(compactProfile(input.profile), undefined, input.asked),
  })

  const set = <K extends ProfileField>(field: K, value: UserProfile[K]) =>
    setDraft((current) => ({ ...current, [field]: value }))

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    replace(draft)
    mutation.mutate({ profile: draft, asked })
  }

  const answer = (option: QuickReply | { value: number }) => {
    const field = mutation.data?.question?.field
    if (!field) return
    const next = { ...draft, [field]: option.value }
    const nextAsked = [...asked, field]
    setDraft(next)
    setAsked(nextAsked)
    replace(next)
    mutation.mutate({ profile: next, asked: nextAsked })
  }

  const label = (field: ProfileField) => FIELD_LABELS[field][language]
  const data = mutation.data

  return (
    <PageTransition>
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[360px_1fr]">
        <section aria-labelledby="eligibility-title">
          <h1 id="eligibility-title" className="text-3xl font-extrabold">
            {t('eligibility.title')}
          </h1>
          <p className="mt-2 text-sm text-fg-muted">{t('eligibility.intro')}</p>
          <form onSubmit={submit} className="card mt-5 space-y-4 p-5">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="age" className="label">
                  {label('age')}
                </label>
                <input
                  id="age"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={120}
                  value={draft.age ?? ''}
                  onChange={(e) => set('age', e.target.value ? Number(e.target.value) : null)}
                  className="field"
                />
              </div>
              <div>
                <label htmlFor="income" className="label">
                  {label('annual_family_income')} (₹)
                </label>
                <input
                  id="income"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1000}
                  value={draft.annual_family_income ?? ''}
                  onChange={(e) =>
                    set('annual_family_income', e.target.value ? Number(e.target.value) : null)
                  }
                  className="field"
                />
              </div>
            </div>
            <div>
              <label htmlFor="state" className="label">
                {label('state')}
              </label>
              <select
                id="state"
                value={draft.state ?? ''}
                onChange={(e) => set('state', e.target.value || null)}
                className="field"
              >
                <option value="">{t('common.notSet')}</option>
                {STATES.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>
            {CHOICE_FIELDS.map((field) => (
              <div key={field}>
                <label htmlFor={field} className="label">
                  {label(field)}
                </label>
                <select
                  id={field}
                  value={(draft[field] as string | null | undefined) ?? ''}
                  onChange={(e) => set(field, (e.target.value || null) as never)}
                  className="field"
                >
                  <option value="">{t('common.notSet')}</option>
                  {Object.entries(VALUE_LABELS[field] ?? {}).map(([value, names]) => (
                    <option key={value} value={value}>
                      {names[language]}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <fieldset>
              <legend className="label">{label('disability')}</legend>
              <div className="flex gap-2">
                {[
                  { value: null, text: t('common.notSet') },
                  { value: true, text: t('common.yes') },
                  { value: false, text: t('common.no') },
                ].map((option) => (
                  <label
                    key={String(option.value)}
                    className={[
                      'chip cursor-pointer',
                      draft.disability === option.value ||
                      (option.value === null && draft.disability == null)
                        ? 'border-accent bg-accent text-on-accent hover:bg-accent'
                        : '',
                    ].join(' ')}
                  >
                    <input
                      type="radio"
                      name="disability"
                      className="sr-only"
                      checked={
                        draft.disability === option.value ||
                        (option.value === null && draft.disability == null)
                      }
                      onChange={() => set('disability', option.value)}
                    />
                    {option.text}
                  </label>
                ))}
              </div>
            </fieldset>
            <button type="submit" className="btn-primary w-full" disabled={mutation.isPending}>
              <ClipboardCheck className="size-4" aria-hidden />
              {t('eligibility.check')}
            </button>
          </form>
        </section>

        <section aria-live="polite" aria-busy={mutation.isPending}>
          {mutation.isError ? (
            <ErrorState onRetry={() => submit()} />
          ) : !data ? (
            <EmptyState
              illustration="documents"
              title={t('eligibility.empty.title')}
              body={t('eligibility.empty.body')}
            />
          ) : (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-2">
                {GROUPS.filter((g) => data.counts[g]).map((group) => (
                  <span key={group} className="chip">
                    <strong>{data.counts[group]}</strong> {t(`eligibility.${group}`)}
                  </span>
                ))}
              </div>
              {data.question && (
                <QuickReplies
                  question={data.question}
                  onAnswer={answer}
                  disabled={mutation.isPending}
                />
              )}
              {data.pending_review.length > 0 && (
                <p className="flex items-center gap-2 text-sm text-fg-muted">
                  <ShieldAlert className="size-4" aria-hidden />
                  {t('eligibility.pending', { count: data.pending_review.length })}
                </p>
              )}
              {GROUPS.map((group) => {
                const items = data.results.filter((r) => r.verdict === group)
                if (!items.length) return null
                return (
                  <div key={group}>
                    <h2 className="mb-3 text-lg font-bold">{t(`eligibility.${group}`)}</h2>
                    <div className="grid gap-3 xl:grid-cols-2">
                      <AnimatePresence>
                        {items.map((result, index) => (
                          <motion.div key={result.scheme_id} layout>
                            <EligibilityCard
                              result={result}
                              index={index}
                              compact={group !== 'eligible'}
                            />
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </PageTransition>
  )
}
