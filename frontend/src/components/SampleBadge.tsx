import { FlaskConical } from 'lucide-react'
import { usePreferences } from '../state/preferences'

export function SampleBadge({ className = '' }: { className?: string }) {
  const { t } = usePreferences()
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-dashed border-fg-muted px-2 py-0.5 text-[11px] font-semibold text-fg-muted ${className}`}
      title={t('scheme.sample')}
    >
      <FlaskConical className="size-3" aria-hidden />
      {t('scheme.sample')}
    </span>
  )
}
