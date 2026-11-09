import { RotateCcw, Square } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CitationDrawer } from '../components/CitationDrawer'
import { ChatMessageView } from '../components/ChatMessageView'
import { PageTransition } from '../components/PageTransition'
import { ProfileBar } from '../components/ProfileBar'
import { SearchBar } from '../components/SearchBar'
import { EmptyState } from '../components/States'
import { useSpeechSynthesis } from '../hooks/useSpeech'
import type { Citation, ProfileField, QuickReply } from '../lib/types'
import { useChat, type ChatMessage } from '../state/chat'
import { usePreferences } from '../state/preferences'
import { useProfile } from '../state/profile'

export default function Chat() {
  const { t, language } = usePreferences()
  const { messages, busy, send, stop, reset } = useChat()
  const { profile, setField } = useProfile()
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<{ citation: Citation; context: string } | null>(null)
  const speech = useSpeechSynthesis()
  const endRef = useRef<HTMLDivElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const q = params.get('q')
    if (q && !started.current) {
      started.current = true
      setParams({}, { replace: true })
      void send(q)
    }
  }, [params, send, setParams])

  const last = messages[messages.length - 1]
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, last?.text.length, last?.clarify])

  const answer = useCallback(
    (message: ChatMessage, option: QuickReply) => {
      const field = message.clarify?.field as ProfileField | undefined
      if (!field) return
      setField(field, option.value as never)
      const label = language === 'hi' ? option.label_hi : option.label
      void send(label, { ...profile, [field]: option.value })
    },
    [language, profile, send, setField],
  )

  const openCitation = useCallback(
    (citation: Citation, context: string) => setSelected({ citation, context }),
    [],
  )

  return (
    <PageTransition>
      <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 pb-40 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-extrabold">{t('chat.title')}</h1>
          {messages.length > 0 && (
            <button type="button" className="btn-ghost ms-auto text-sm" onClick={reset}>
              <RotateCcw className="size-4" aria-hidden />
              {t('chat.new')}
            </button>
          )}
        </div>
        <div className="card p-3">
          <ProfileBar />
        </div>
        {messages.length === 0 ? (
          <EmptyState
            illustration="chat"
            title={t('chat.empty.title')}
            body={t('chat.empty.body')}
          />
        ) : (
          <div className="flex flex-col gap-4">
            {messages.map((message, index) => (
              <ChatMessageView
                key={message.id}
                message={message}
                isLast={index === messages.length - 1}
                busy={busy}
                onCitation={openCitation}
                onAnswer={answer}
                speech={speech}
              />
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="no-print fixed inset-x-0 bottom-0 z-30 border-t border-line/70 bg-bg/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-3">
          <div className="flex-1">
            <SearchBar onSubmit={(text) => void send(text)} disabled={busy} autoFocus />
          </div>
          {busy && (
            <button
              type="button"
              onClick={stop}
              className="btn-brand h-12"
              aria-label={t('chat.stop')}
            >
              <Square className="size-4" aria-hidden />
            </button>
          )}
        </div>
      </div>
      <CitationDrawer
        citation={selected?.citation ?? null}
        context={selected?.context ?? ''}
        onClose={() => setSelected(null)}
      />
    </PageTransition>
  )
}
