import { motion } from 'framer-motion'
import { BadgeCheck, GraduationCap, Lock, Quote, Rocket, Sprout } from 'lucide-react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { HeroMesh } from '../components/HeroMesh'
import { PageTransition } from '../components/PageTransition'
import { RotatingWord } from '../components/RotatingWord'
import { SearchBar } from '../components/SearchBar'
import { translate } from '../lib/i18n'
import type { MessageKey } from '../lib/i18n'
import { usePreferences } from '../state/preferences'

const CHIPS: { key: MessageKey; icon: typeof GraduationCap }[] = [
  { key: 'home.chip.students', icon: GraduationCap },
  { key: 'home.chip.farmers', icon: Sprout },
  { key: 'home.chip.startup', icon: Rocket },
]

const FEATURES: { title: MessageKey; body: MessageKey; icon: typeof Quote }[] = [
  { title: 'home.feature.cited.title', body: 'home.feature.cited.body', icon: Quote },
  { title: 'home.feature.rules.title', body: 'home.feature.rules.body', icon: BadgeCheck },
  { title: 'home.feature.private.title', body: 'home.feature.private.body', icon: Lock },
]

export default function Home() {
  const { t, language } = usePreferences()
  const navigate = useNavigate()

  const words = useMemo(() => {
    const english = translate('en', 'home.hero.words').split('|')
    const hindi = translate('hi', 'home.hero.words').split('|')
    return english.flatMap((word, i) => [
      { text: word, lang: 'en' },
      { text: hindi[i] ?? word, lang: 'hi' },
    ])
  }, [])

  const ask = (text: string) => navigate(`/chat?q=${encodeURIComponent(text)}`)

  return (
    <PageTransition>
      <section className="relative isolate overflow-hidden">
        <HeroMesh />
        <div className="mx-auto flex min-h-[70dvh] max-w-4xl flex-col items-center justify-center px-4 py-16 text-center sm:py-24">
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-4 rounded-full border border-line bg-surface/70 px-3 py-1 text-sm font-semibold backdrop-blur"
          >
            {t('app.tagline')}
          </motion.p>
          <h1 className="text-balance text-4xl font-extrabold leading-[1.15] tracking-tight sm:text-6xl">
            {language === 'hi' ? (
              <>
                {t('home.hero.before')} <RotatingWord words={words} /> {t('home.hero.after')}
              </>
            ) : (
              <>
                {t('home.hero.before')} <RotatingWord words={words} />
                <br className="hidden sm:block" /> {t('home.hero.after')}
              </>
            )}
          </h1>
          <p className="mt-5 max-w-2xl text-pretty text-base text-fg-muted sm:text-lg">
            {t('home.hero.sub')}
          </p>
          <div className="mt-8 w-full max-w-2xl">
            <SearchBar onSubmit={ask} placeholder={t('home.search.placeholder')} size="lg" />
          </div>
          <motion.ul
            className="mt-5 flex flex-wrap justify-center gap-2"
            initial="hidden"
            animate="show"
            variants={{ show: { transition: { staggerChildren: 0.08, delayChildren: 0.2 } } }}
          >
            {CHIPS.map(({ key, icon: Icon }) => (
              <motion.li
                key={key}
                variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0 } }}
              >
                <button
                  type="button"
                  className="chip bg-surface/80 backdrop-blur"
                  onClick={() => ask(t(key))}
                >
                  <Icon className="size-4" aria-hidden />
                  {t(key)}
                </button>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      </section>
      <section className="mx-auto grid max-w-5xl gap-4 px-4 pb-16 sm:grid-cols-3">
        {FEATURES.map(({ title, body, icon: Icon }, index) => (
          <motion.div
            key={title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-40px' }}
            transition={{ delay: index * 0.08 }}
            className="card p-5"
          >
            <span className="mb-3 flex size-10 items-center justify-center rounded-xl bg-accent text-on-accent">
              <Icon className="size-5" aria-hidden />
            </span>
            <h2 className="font-bold">{t(title)}</h2>
            <p className="mt-1 text-sm text-fg-muted">{t(body)}</p>
          </motion.div>
        ))}
      </section>
    </PageTransition>
  )
}
