import { Mic, Square } from 'lucide-react'
import { useSpeechRecognition } from '../hooks/useSpeech'
import { usePreferences } from '../state/preferences'

export function VoiceButton({ onText }: { onText: (text: string) => void }) {
  const { language, t } = usePreferences()
  const { supported, listening, start, stop } = useSpeechRecognition(language, onText)
  if (!supported) return null
  return (
    <button
      type="button"
      onClick={listening ? stop : start}
      className={[
        'relative inline-flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-semibold transition-colors',
        listening ? 'bg-accent text-on-accent' : 'text-fg hover:bg-surface-2',
      ].join(' ')}
      aria-label={listening ? t('voice.stop') : t('voice.start')}
      aria-pressed={listening}
      title={listening ? t('voice.stop') : t('voice.start')}
    >
      {listening ? (
        <>
          <Square className="size-3.5" aria-hidden />
          <span className="wave flex h-4 items-center" aria-hidden>
            <span />
            <span />
            <span />
            <span />
          </span>
          <span className="sr-only" role="status">
            {t('voice.listening')}
          </span>
        </>
      ) : (
        <Mic className="size-5" aria-hidden />
      )}
    </button>
  )
}
