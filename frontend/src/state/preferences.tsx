import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { translate, type MessageKey } from '../lib/i18n'
import { readStored, writeStored } from '../lib/storage'
import type { Language } from '../lib/types'

type Theme = 'light' | 'dark'

interface Preferences {
  language: Language
  setLanguage: (language: Language) => void
  toggleLanguage: () => void
  theme: Theme
  toggleTheme: () => void
  t: (key: MessageKey, vars?: Record<string, string | number>) => string
}

const PreferencesContext = createContext<Preferences | null>(null)

function initialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem('ys.theme')
    if (stored === 'dark' || stored === 'light') return stored
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => readStored('language', 'en'))
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.lang = language
    writeStored('language', language)
  }, [language])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    // The inline script in index.html reads this key before React loads.
    try {
      window.localStorage.setItem('ys.theme', theme)
    } catch {
      // Theme still applies for this session.
    }
  }, [theme])

  const setLanguage = useCallback((next: Language) => setLanguageState(next), [])
  const toggleLanguage = useCallback(
    () => setLanguageState((current) => (current === 'en' ? 'hi' : 'en')),
    [],
  )
  const toggleTheme = useCallback(
    () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
    [],
  )
  const t = useCallback(
    (key: MessageKey, vars?: Record<string, string | number>) => translate(language, key, vars),
    [language],
  )

  const value = useMemo(
    () => ({ language, setLanguage, toggleLanguage, theme, toggleTheme, t }),
    [language, setLanguage, toggleLanguage, theme, toggleTheme, t],
  )
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
}

export function usePreferences(): Preferences {
  const context = useContext(PreferencesContext)
  if (!context) throw new Error('usePreferences must be used inside PreferencesProvider')
  return context
}
