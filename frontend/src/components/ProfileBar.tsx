import { AnimatePresence, LayoutGroup, motion } from 'framer-motion'
import { UserRound, X } from 'lucide-react'
import { FIELD_LABELS } from '../lib/i18n'
import { describeValue } from '../lib/profileText'
import type { ProfileField } from '../lib/types'
import { usePreferences } from '../state/preferences'
import { useProfile } from '../state/profile'

/** Captured profile fields as removable chips that animate in as the user shares them. */
export function ProfileBar() {
  const { profile, removeField } = useProfile()
  const { language, t } = usePreferences()
  const fields = (Object.keys(FIELD_LABELS) as ProfileField[]).filter(
    (field) => profile[field] !== undefined && profile[field] !== null,
  )

  return (
    <section aria-label={t('profile.title')} className="flex flex-wrap items-center gap-2">
      <span className="flex items-center gap-1.5 text-sm font-semibold text-fg-muted">
        <UserRound className="size-4" aria-hidden />
        {t('profile.title')}
      </span>
      <LayoutGroup>
        <AnimatePresence initial={false}>
          {fields.length === 0 && (
            <motion.span
              key="empty"
              layout
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-sm text-fg-muted"
            >
              {t('profile.empty')}
            </motion.span>
          )}
          {fields.map((field) => (
            <motion.span
              key={field}
              layout
              layoutId={`profile-${field}`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
              className="inline-flex items-center gap-1 rounded-full bg-brand-soft py-1 pe-1 ps-3 text-sm"
            >
              <span className="text-fg-muted">{FIELD_LABELS[field][language]}:</span>
              <span className="font-semibold">
                {describeValue(field, profile[field], language)}
              </span>
              <button
                type="button"
                onClick={() => removeField(field)}
                className="ms-0.5 rounded-full p-1 hover:bg-surface"
                aria-label={t('profile.remove', { field: FIELD_LABELS[field][language] })}
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </motion.span>
          ))}
        </AnimatePresence>
      </LayoutGroup>
    </section>
  )
}
