import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'framer-motion'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { ChatProvider } from './state/chat'
import { CompareProvider } from './state/compare'
import { PreferencesProvider } from './state/preferences'
import { ProfileProvider } from './state/profile'
import { ToastProvider } from './state/toasts'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <BrowserRouter>
          <PreferencesProvider>
            <ProfileProvider>
              <ToastProvider>
                <CompareProvider>
                  <ChatProvider>
                    <App />
                  </ChatProvider>
                </CompareProvider>
              </ToastProvider>
            </ProfileProvider>
          </PreferencesProvider>
        </BrowserRouter>
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
)
