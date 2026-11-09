import { useCallback, useEffect, useRef, useState } from 'react'
import type { Language } from '../lib/types'

interface RecognitionResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>
}

interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: RecognitionResultEvent) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
}

type RecognitionConstructor = new () => Recognition

function recognitionClass(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as {
    SpeechRecognition?: RecognitionConstructor
    webkitSpeechRecognition?: RecognitionConstructor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

const LOCALES: Record<Language, string> = { en: 'en-IN', hi: 'hi-IN' }

/** Browser speech-to-text (Web Speech API). `supported` is false where it is missing. */
export function useSpeechRecognition(language: Language, onText: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const recognition = useRef<Recognition | null>(null)
  const supported = recognitionClass() !== null
  const onTextRef = useRef(onText)

  useEffect(() => {
    onTextRef.current = onText
  }, [onText])

  useEffect(() => () => recognition.current?.abort(), [])

  const start = useCallback(() => {
    const Ctor = recognitionClass()
    if (!Ctor) return
    const instance = new Ctor()
    instance.lang = LOCALES[language]
    instance.interimResults = true
    instance.continuous = false
    instance.onresult = (event) => {
      const text = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? '')
        .join(' ')
      onTextRef.current(text)
    }
    instance.onend = () => setListening(false)
    instance.onerror = () => setListening(false)
    recognition.current = instance
    setListening(true)
    instance.start()
  }, [language])

  const stop = useCallback(() => recognition.current?.stop(), [])
  return { supported, listening, start, stop }
}

/** Read text aloud with speechSynthesis in the matching Indian locale. */
export function useSpeechSynthesis() {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [speakingId, setSpeakingId] = useState<string | null>(null)

  useEffect(() => {
    if (!supported) return undefined
    return () => window.speechSynthesis.cancel()
  }, [supported])

  const speak = useCallback(
    (id: string, text: string, language: Language) => {
      if (!supported) return
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = LOCALES[language]
      const voice = window.speechSynthesis
        .getVoices()
        .find((v) => v.lang.toLowerCase().startsWith(LOCALES[language].toLowerCase().slice(0, 2)))
      if (voice) utterance.voice = voice
      utterance.onend = () => setSpeakingId(null)
      utterance.onerror = () => setSpeakingId(null)
      setSpeakingId(id)
      window.speechSynthesis.speak(utterance)
    },
    [supported],
  )

  const cancel = useCallback(() => {
    if (supported) window.speechSynthesis.cancel()
    setSpeakingId(null)
  }, [supported])

  return { supported, speakingId, speak, cancel }
}
