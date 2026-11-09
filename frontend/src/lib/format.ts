import type { Language, UserProfile } from './types'

export function formatRupees(amount: number, language: Language = 'en'): string {
  return new Intl.NumberFormat(language === 'hi' ? 'hi-IN' : 'en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

export function formatLakh(amount: number, language: Language = 'en'): string {
  if (amount < 100_000) return formatRupees(amount, language)
  const lakhs = Math.round((amount / 100_000) * 100) / 100
  return language === 'hi' ? `₹${lakhs} लाख` : `₹${lakhs} lakh`
}

export function formatMs(ms: number): string {
  if (ms < 1) return '<1 ms'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function stripCitations(text: string): string {
  return text
    .replace(/\[\d+(?:\s*,\s*\d+)*\]/g, '')
    .replace(/\*\*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function compactProfile(profile: UserProfile): UserProfile {
  return Object.fromEntries(
    Object.entries(profile).filter(([, value]) => value !== null && value !== undefined),
  ) as UserProfile
}
