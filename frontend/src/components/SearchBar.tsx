import { ArrowRight, Search } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { usePreferences } from '../state/preferences'
import { VoiceButton } from './VoiceButton'

interface Props {
  onSubmit: (text: string) => void
  placeholder?: string
  autoFocus?: boolean
  size?: 'lg' | 'md'
  disabled?: boolean
}

export function SearchBar({ onSubmit, placeholder, autoFocus, size = 'md', disabled }: Props) {
  const { t } = usePreferences()
  const [value, setValue] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!value.trim() || disabled) return
    onSubmit(value)
    setValue('')
  }

  return (
    <form
      onSubmit={submit}
      className={[
        'card search-shell flex items-center gap-2 p-2 ps-4 transition-shadow',
        size === 'lg' ? 'sm:p-2.5 sm:ps-5' : '',
      ].join(' ')}
      role="search"
    >
      <Search className="size-5 shrink-0 text-fg-muted" aria-hidden />
      <label htmlFor="ask" className="sr-only">
        {placeholder ?? t('chat.placeholder')}
      </label>
      <input
        id="ask"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder ?? t('chat.placeholder')}
        autoFocus={autoFocus}
        autoComplete="off"
        maxLength={2000}
        className={[
          'min-w-0 flex-1 bg-transparent text-fg placeholder:text-fg-muted focus:outline-none',
          size === 'lg' ? 'py-2 text-base sm:text-lg' : 'py-1.5',
        ].join(' ')}
      />
      <VoiceButton onText={setValue} />
      <button type="submit" className="btn-primary h-10 px-4" disabled={disabled || !value.trim()}>
        <span className="hidden sm:inline">{t('home.search.submit')}</span>
        <ArrowRight className="size-4" aria-hidden />
      </button>
    </form>
  )
}
