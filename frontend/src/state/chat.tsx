import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { compactProfile } from '../lib/format'
import { STAGES } from '../lib/i18n'
import { postEventStream } from '../lib/sse'
import type {
  Citation,
  ClarifyQuestion,
  Language,
  ProviderInfo,
  SchemeEligibility,
  StageName,
  StageState,
  UserProfile,
} from '../lib/types'
import { usePreferences } from './preferences'
import { useProfile } from './profile'
import { useToasts } from './toasts'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  language: Language
  stages: Record<StageName, StageState>
  citations: Citation[]
  provider?: ProviderInfo
  switchedFrom?: string
  eligibility?: { results: SchemeEligibility[]; pending_review: string[] }
  clarify?: ClarifyQuestion
  error?: { code: string; message: string }
  streaming: boolean
  intent?: string
  abstained?: boolean
}

interface ChatState {
  messages: ChatMessage[]
  busy: boolean
  send: (text: string, profileOverride?: UserProfile) => Promise<void>
  stop: () => void
  reset: () => void
}

const ChatContext = createContext<ChatState | null>(null)

function freshStages(): Record<StageName, StageState> {
  return Object.fromEntries(STAGES.map((stage) => [stage, { status: 'pending' }])) as Record<
    StageName,
    StageState
  >
}

let counter = 0
function newId(): string {
  counter += 1
  return `${Date.now().toString(36)}-${counter}`
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const askedFields = useRef<string[]>([])
  const controller = useRef<AbortController | null>(null)
  const { language, t } = usePreferences()
  const { profile, merge } = useProfile()
  const { notify } = useToasts()

  const update = useCallback((id: string, change: (message: ChatMessage) => ChatMessage) => {
    setMessages((current) =>
      current.map((message) => (message.id === id ? change(message) : message)),
    )
  }, [])

  const send = useCallback(
    async (text: string, profileOverride?: UserProfile) => {
      const trimmed = text.trim()
      if (!trimmed || busy) return
      const userMessage: ChatMessage = {
        id: newId(),
        role: 'user',
        text: trimmed,
        language,
        stages: freshStages(),
        citations: [],
        streaming: false,
      }
      const assistantId = newId()
      const assistant: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        text: '',
        language,
        stages: freshStages(),
        citations: [],
        streaming: true,
      }
      const history = messages
        .filter((m) => m.text)
        .slice(-12)
        .map((m) => ({ role: m.role, content: m.text }))
      setMessages((current) => [...current, userMessage, assistant])
      setBusy(true)
      const abort = new AbortController()
      controller.current = abort

      try {
        const stream = postEventStream(
          '/api/chat',
          {
            message: trimmed,
            history,
            profile: compactProfile(profileOverride ?? profile),
            language,
            asked_fields: askedFields.current,
          },
          abort.signal,
        )
        for await (const { event, data } of stream) {
          const payload = data as Record<string, unknown>
          switch (event) {
            case 'stage': {
              const stage = payload.stage as StageName
              const ended = payload.status === 'end'
              update(assistantId, (m) => ({
                ...m,
                language: (payload.language as Language) ?? m.language,
                intent: (payload.intent as string) ?? m.intent,
                stages: {
                  ...m.stages,
                  [stage]: ended
                    ? { status: 'done', ms: payload.ms as number }
                    : { status: 'active' },
                },
              }))
              if (ended && stage === 'understanding' && payload.profile_updates) {
                merge(payload.profile_updates as UserProfile)
              }
              break
            }
            case 'token':
              update(assistantId, (m) => ({ ...m, text: m.text + String(payload.text ?? '') }))
              break
            case 'citations':
              update(assistantId, (m) => ({ ...m, citations: payload.sources as Citation[] }))
              break
            case 'eligibility':
              update(assistantId, (m) => ({
                ...m,
                eligibility: payload as unknown as ChatMessage['eligibility'],
              }))
              break
            case 'clarify': {
              const question = payload as unknown as ClarifyQuestion
              askedFields.current = [...new Set([...askedFields.current, question.field])]
              update(assistantId, (m) => ({ ...m, clarify: question }))
              break
            }
            case 'provider':
              update(assistantId, (m) => ({ ...m, provider: payload as unknown as ProviderInfo }))
              break
            case 'provider_switch': {
              const label = String(payload.label ?? payload.to)
              update(assistantId, (m) => ({
                ...m,
                text: '',
                switchedFrom: m.provider?.label,
                provider: {
                  name: String(payload.to),
                  label,
                  model: '',
                  offline: String(payload.to) === 'ollama',
                  cached: false,
                },
              }))
              notify(t('chat.switched', { provider: label }))
              break
            }
            case 'error':
              update(assistantId, (m) => ({
                ...m,
                error: { code: String(payload.code), message: String(payload.message ?? '') },
              }))
              break
            case 'done':
              update(assistantId, (m) => ({
                ...m,
                streaming: false,
                abstained: Boolean(payload.abstained),
                stages: Object.fromEntries(
                  Object.entries(m.stages).map(([name, state]) => [
                    name,
                    state.status === 'pending' || state.status === 'active'
                      ? { status: state.status === 'active' ? 'done' : 'skipped', ms: state.ms }
                      : state,
                  ]),
                ) as Record<StageName, StageState>,
              }))
              break
            default:
              break
          }
        }
      } catch (error) {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          update(assistantId, (m) => ({
            ...m,
            error: { code: 'network', message: t('chat.error') },
          }))
        }
      } finally {
        update(assistantId, (m) => ({ ...m, streaming: false }))
        setBusy(false)
        controller.current = null
      }
    },
    [busy, language, merge, messages, notify, profile, t, update],
  )

  const stop = useCallback(() => controller.current?.abort(), [])
  const reset = useCallback(() => {
    controller.current?.abort()
    askedFields.current = []
    setMessages([])
  }, [])

  const value = useMemo(
    () => ({ messages, busy, send, stop, reset }),
    [messages, busy, send, stop, reset],
  )
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatState {
  const context = useContext(ChatContext)
  if (!context) throw new Error('useChat must be used inside ChatProvider')
  return context
}
