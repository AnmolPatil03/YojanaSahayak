import { formatLakh } from './format'
import { VALUE_LABELS } from './i18n'
import type { Language, ProfileField, UserProfile } from './types'

export function describeValue(
  field: ProfileField,
  value: UserProfile[ProfileField],
  language: Language,
): string {
  if (value === null || value === undefined) return ''
  if (field === 'annual_family_income') return `≤ ${formatLakh(Number(value), language)}`
  if (field === 'disability') {
    return value ? (language === 'hi' ? 'हाँ' : 'Yes') : language === 'hi' ? 'नहीं' : 'No'
  }
  if (field === 'age') return String(value)
  const label = VALUE_LABELS[field]?.[String(value)]
  return label ? label[language] : String(value)
}
