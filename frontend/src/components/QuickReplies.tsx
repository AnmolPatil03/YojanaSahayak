import { motion } from 'framer-motion'
import { ArrowRight, HelpCircle } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ClarifyQuestion, QuickReply } from '../lib/types'
import { usePreferences } from '../state/preferences'

interface Props {
  question: ClarifyQuestion
  onAnswer: (option: QuickReply | { label: string; label_hi: string; value: number }) => void
  disabled?: boolean
}

/** Follow-up question with quick-reply chips that pop in one after another. */
export function QuickReplies({ question, onAnswer, disabled }: Props) {
  const { language, t } = usePreferences()
  const [typed, setTyped] = useState('')

  const submitNumber = (event: FormEvent) => {
    event.preventDefault()
    const value = Number(typed)
    if (!Number.isFinite(value) || value <= 0) return
    onAnswer({ label: typed, label_hi: typed, value })
    setTyped('')
  }

  return (
    <div className="mt-3 rounded-2xl border border-dashed border-line bg-surface-2/60 p-3">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <HelpCircle className="size-4" aria-hidden />
        {language === 'hi' ? question.question_hi : question.question}
      </p>
      {question.input === 'number' ? (
        <form onSubmit={submitNumber} className="flex gap-2">
          <label htmlFor={`clarify-${question.field}`} className="sr-only">
            {t('chat.typeAnswer')}
          </label>
          <input
            id={`clarify-${question.field}`}
            type="number"
            inputMode="numeric"
            min={1}
            max={120}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className="field max-w-44"
            placeholder={t('chat.typeAnswer')}
            disabled={disabled}
          />
          <button type="submit" className="btn-primary" disabled={disabled || !typed}>
            <ArrowRight className="size-4" aria-label={t('chat.send')} />
          </button>
        </form>
      ) : (
        <motion.ul
          className="flex flex-wrap gap-2"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        >
          {question.options.map((option) => (
            <motion.li
              key={String(option.value)}
              variants={{
                hidden: { opacity: 0, scale: 0.6, y: 6 },
                show: { opacity: 1, scale: 1, y: 0 },
              }}
              transition={{ type: 'spring', stiffness: 520, damping: 26 }}
            >
              <button
                type="button"
                className="chip hover:border-accent"
                onClick={() => onAnswer(option)}
                disabled={disabled}
              >
                {language === 'hi' ? option.label_hi : option.label}
              </button>
            </motion.li>
          ))}
        </motion.ul>
      )}
    </div>
  )
}
