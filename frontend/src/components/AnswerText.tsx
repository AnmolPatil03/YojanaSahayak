import { Fragment } from 'react'
import type { ReactNode } from 'react'
import type { Citation } from '../lib/types'
import { CitationChip } from './CitationChip'

interface Props {
  text: string
  citations: Citation[]
  onOpen: (citation: Citation, context: string) => void
  streaming?: boolean
}

const INLINE = /(\*\*[^*]+\*\*|\[\d+\])/g

function renderInline(
  text: string,
  citations: Citation[],
  onOpen: Props['onOpen'],
  keyPrefix: string,
): ReactNode[] {
  const parts = text.split(INLINE).filter((part) => part !== '')
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key}>{part.slice(2, -2)}</strong>
    }
    const match = /^\[(\d+)\]$/.exec(part)
    if (match) {
      const citation = citations.find((c) => c.n === Number(match[1]))
      if (citation) {
        return <CitationChip key={key} citation={citation} context={text} onOpen={onOpen} />
      }
      return (
        <sup key={key} className="text-fg-muted">
          {part}
        </sup>
      )
    }
    return <Fragment key={key}>{part}</Fragment>
  })
}

/**
 * Minimal markdown for answers: paragraphs, bullet and numbered lists, bold, and
 * `[n]` citations. No HTML is ever injected.
 */
export function AnswerText({ text, citations, onOpen, streaming }: Props) {
  const blocks: ReactNode[] = []
  const lines = text.split('\n')
  let list: { ordered: boolean; items: string[] } | null = null

  const flushList = (key: string) => {
    if (!list) return
    const items = list.items.map((item, index) => (
      <li key={`${key}-${index}`}>{renderInline(item, citations, onOpen, `${key}-${index}`)}</li>
    ))
    blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>)
    list = null
  }

  lines.forEach((raw, index) => {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      if (list && list.ordered !== ordered) flushList(`list-${index}`)
      list ??= { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
      return
    }
    flushList(`list-${index}`)
    if (!line.trim()) return
    const heading = /^#{1,4}\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push(
        <p key={`h-${index}`} className="font-bold">
          {renderInline(heading[1], citations, onOpen, `h-${index}`)}
        </p>,
      )
      return
    }
    blocks.push(<p key={`p-${index}`}>{renderInline(line, citations, onOpen, `p-${index}`)}</p>)
  })
  flushList('list-end')

  return (
    <div className={['prose-answer', streaming ? 'caret' : ''].join(' ')}>
      {blocks.length ? blocks : streaming ? <p /> : null}
    </div>
  )
}
