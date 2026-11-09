import { AnimatePresence, motion } from 'framer-motion'
import { Languages, Menu, Moon, Sun, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { clearAllStored } from '../lib/storage'
import type { MessageKey } from '../lib/i18n'
import { useChat } from '../state/chat'
import { useCompare } from '../state/compare'
import { usePreferences } from '../state/preferences'
import { useProfile } from '../state/profile'
import { useToasts } from '../state/toasts'
import { Logo } from './Logo'

const LINKS: { to: string; key: MessageKey }[] = [
  { to: '/chat', key: 'nav.chat' },
  { to: '/schemes', key: 'nav.explorer' },
  { to: '/eligibility', key: 'nav.eligibility' },
  { to: '/compare', key: 'nav.compare' },
  { to: '/insights', key: 'nav.insights' },
]

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    'relative rounded-lg px-3 py-2 text-sm font-semibold transition-colors',
    isActive ? 'text-fg' : 'text-fg-muted hover:text-fg',
  ].join(' ')
}

export function Layout({ children }: { children: ReactNode }) {
  const { t, theme, toggleTheme, toggleLanguage, language } = usePreferences()
  const { clear: clearProfile } = useProfile()
  const { clear: clearCompare, ids } = useCompare()
  const { reset } = useChat()
  const { notify } = useToasts()
  const [open, setOpen] = useState(false)

  const clearData = () => {
    if (!window.confirm(t('data.confirm'))) return
    clearAllStored()
    clearProfile()
    clearCompare()
    reset()
    notify(t('data.cleared'))
  }

  const controls = (
    <>
      <button
        type="button"
        onClick={toggleLanguage}
        className="btn-ghost px-3"
        aria-label={t('lang.switch')}
        title={t('lang.switch')}
      >
        <Languages className="size-4" aria-hidden />
        <span lang={language === 'en' ? 'hi' : 'en'}>{language === 'en' ? 'हिं' : 'EN'}</span>
      </button>
      <button
        type="button"
        onClick={toggleTheme}
        className="btn-ghost px-3"
        aria-label={theme === 'dark' ? t('theme.light') : t('theme.dark')}
        title={theme === 'dark' ? t('theme.light') : t('theme.dark')}
      >
        {theme === 'dark' ? (
          <Sun className="size-4" aria-hidden />
        ) : (
          <Moon className="size-4" aria-hidden />
        )}
      </button>
      <button type="button" onClick={clearData} className="btn-ghost px-3" title={t('data.clear')}>
        <Trash2 className="size-4" aria-hidden />
        <span className="lg:sr-only">{t('data.clear')}</span>
      </button>
    </>
  )

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-accent px-4 py-2 font-semibold text-on-accent focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        {t('common.skip')}
      </a>
      <header className="no-print sticky top-0 z-40 border-b border-line/70 bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4">
          <NavLink
            to="/"
            className="flex items-center gap-2 rounded-lg font-extrabold tracking-tight"
          >
            <Logo className="size-8" />
            <span className="text-lg">{t('app.name')}</span>
          </NavLink>
          <nav className="ms-6 hidden items-center gap-1 md:flex" aria-label="Main">
            {LINKS.map((link) => (
              <NavLink key={link.to} to={link.to} className={navClass}>
                {({ isActive }) => (
                  <>
                    {t(link.key)}
                    {link.to === '/compare' && ids.length > 0 && (
                      <span className="ms-1 rounded-full bg-accent px-1.5 text-xs text-on-accent">
                        {ids.length}
                      </span>
                    )}
                    {isActive && (
                      <motion.span
                        layoutId="nav-underline"
                        className="absolute inset-x-3 -bottom-[13px] h-[3px] rounded-full bg-accent"
                        transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="ms-auto hidden items-center gap-1 md:flex">{controls}</div>
          <button
            type="button"
            className="btn-ghost ms-auto px-3 md:hidden"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={t('nav.menu')}
          >
            {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </button>
        </div>
        <AnimatePresence>
          {open && (
            <motion.nav
              id="mobile-menu"
              aria-label="Main"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-line md:hidden"
            >
              <div className="flex flex-col gap-1 px-4 py-3">
                {LINKS.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    className={navClass}
                    onClick={() => setOpen(false)}
                  >
                    {t(link.key)}
                  </NavLink>
                ))}
                <div className="mt-2 flex flex-wrap gap-1 border-t border-line pt-3">
                  {controls}
                </div>
              </div>
            </motion.nav>
          )}
        </AnimatePresence>
      </header>
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="no-print border-t border-line/70 py-6 text-center text-sm text-fg-muted">
        {t('app.name')} · {t('app.tagline')}
      </footer>
    </div>
  )
}
