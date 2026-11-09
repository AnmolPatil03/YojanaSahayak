import { motion } from 'framer-motion'
import { AlertTriangle, BookOpen, Square, Volume2 } from 'lucide-react'
import { stripCitations } from '../lib/format'
import type { Citation, QuickReply } from '../lib/types'
import type { ChatMessage } from '../state/chat'
import { usePreferences } from '../state/preferences'
import { AnswerText } from './AnswerText'
import { EligibilityCard } from './EligibilityCard'
import { PipelineTracker } from './PipelineTracker'
import { ProviderPill } from './ProviderPill'
import { QuickReplies } from './QuickReplies'

interface Props {
  message: ChatMessage
  isLast: boolean
  busy: boolean
  onCitation: (citation: Citation, context: string) => void
  onAnswer: (message: ChatMessage, option: QuickReply) => void
  speech: {
    supported: boolean
    speakingId: string | null
    speak: (id: string, text: string, language: 'en' | 'hi') => void
    cancel: () => void
  }
}

export function ChatMessageView({ message, isLast, busy, onCitation, onAnswer, speech }: Props) {
  const { t } = usePreferences()

  if (message.role === 'user') {
    return (
      <motion.div
        initial={{ opacity: 0, x: 24 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ type: 'spring', stiffness: 380, damping: 30 }}
        className="flex justify-end"
      >
        <p
          className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-on-brand"
          lang={message.language}
        >
          {message.text}
        </p>
      </motion.div>
    )
  }

  const cited = message.citations.filter((c) => c.cited)
  const showTracker =
    message.streaming || Object.values(message.stages).some((s) => s.status === 'done')
  const speaking = speech.speakingId === message.id
  const results = message.eligibility?.results ?? []

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 30 }}
      className="card p-4 sm:p-5"
    >
      {showTracker && (
        <div className="mb-3">
          <PipelineTracker stages={message.stages} />
        </div>
      )}
      {message.error && (
        <div
          className="mb-3 flex items-start gap-2 rounded-xl bg-accent-soft p-3 text-sm"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            {message.error.code === 'all_providers_exhausted'
              ? t('chat.exhausted')
              : message.error.message || t('chat.error')}
          </p>
        </div>
      )}
      <div
        aria-live={isLast ? 'polite' : undefined}
        aria-busy={message.streaming}
        lang={message.language}
      >
        <AnswerText
          text={message.text}
          citations={message.citations}
          onOpen={onCitation}
          streaming={message.streaming}
        />
      </div>
      {message.clarify && isLast && (
        <QuickReplies
          question={message.clarify}
          onAnswer={(option) => onAnswer(message, option)}
          disabled={busy}
        />
      )}
      {results.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-semibold text-fg-muted">{t('chat.eligibility')}</p>
          <div className="grid gap-3 md:grid-cols-2">
            {results.slice(0, 4).map((result, index) => (
              <EligibilityCard key={result.scheme_id} result={result} index={index} compact />
            ))}
          </div>
        </div>
      )}
      {cited.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
            <BookOpen className="size-3.5" aria-hidden />
            {t('chat.sources')}
          </p>
          <ul className="flex flex-wrap gap-2">
            {cited.map((citation) => (
              <li key={citation.n}>
                <button
                  type="button"
                  onClick={() => onCitation(citation, '')}
                  className="chip text-xs"
                >
                  <span className="rounded bg-accent px-1 font-bold text-on-accent">
                    {citation.n}
                  </span>
                  <span className="max-w-48 truncate">
                    {citation.scheme_name} · {citation.section_label}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <ProviderPill provider={message.provider} id={message.id} />
        {speech.supported && message.text && !message.streaming && (
          <button
            type="button"
            className="btn-ghost px-2 py-1 text-xs"
            onClick={() =>
              speaking
                ? speech.cancel()
                : speech.speak(message.id, stripCitations(message.text), message.language)
            }
            aria-pressed={speaking}
          >
            {speaking ? (
              <Square className="size-3.5" aria-hidden />
            ) : (
              <Volume2 className="size-3.5" aria-hidden />
            )}
            {speaking ? t('chat.stopReading') : t('chat.readAloud')}
          </button>
        )}
      </div>
    </motion.div>
  )
}
