import { AnimatePresence } from 'framer-motion'
import { Suspense } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { Layout } from './components/Layout'
import { PageTransition } from './components/PageTransition'
import { EmptyState, Skeleton } from './components/States'
import Chat from './pages/Chat'
import Home from './pages/Home'
import { usePreferences } from './state/preferences'

function NotFound() {
  const { t } = usePreferences()
  return (
    <PageTransition>
      <EmptyState
        title={t('notFound.title')}
        body={t('notFound.body')}
        action={
          <Link to="/" className="btn-brand">
            {t('nav.home')}
          </Link>
        }
      />
    </PageTransition>
  )
}

function PageFallback() {
  return (
    <div className="mx-auto max-w-5xl space-y-4 px-4 py-8">
      <Skeleton className="h-9 w-56" />
      <Skeleton className="h-40 w-full" />
    </div>
  )
}

export default function App() {
  const location = useLocation()
  return (
    <Layout>
      <Suspense fallback={<PageFallback />}>
        <AnimatePresence mode="wait">
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<Home />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AnimatePresence>
      </Suspense>
    </Layout>
  )
}
