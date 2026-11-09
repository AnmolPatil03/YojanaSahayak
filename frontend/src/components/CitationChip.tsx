import { AnimatePresence, motion } from 'framer-motion'
import { useId, useState } from 'react'
import type { Citation } from '../lib/types'
import { usePreferences } from '../state/preferences'

interface Props {
  citation: Citation
  context: string
  onOpen: (citation: Citation, context: string) => void
}

function snippet(text: string, limit = 220): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1).replace(/\s\S*$/, '')}…`
}

/** Inline `[n]` chip: hover or focus previews the source, click opens the drawer. */
export function CitationChip({ citation, context, onOpen }: Props) {
  const { t } = usePreferences()
  const [show, setShow] = useState(false)
  const tooltipId = useId()

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => onOpen(citation, context)}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onFocus={() => setShow(true)}
        onBlur={() => setShow(false)}
        className="mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-md bg-accent px-1 text-[11px] font-bold leading-none text-on-accent transition-transform hover:scale-110"
        aria-label={t('citation.open', { n: citation.n })}
        aria-describedby={show ? tooltipId : undefined}
      >
        {citation.n}
      </button>
      <AnimatePresence>
        {show && (
          <motion.span
            id={tooltipId}
            role="tooltip"
            initial={{ opacity: 0, y: 4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            className="card pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 block w-72 max-w-[80vw] -translate-x-1/2 p-3 text-left text-xs font-normal leading-relaxed text-fg"
          >
            <span className="mb-1 block font-bold">
              {citation.scheme_name} · {citation.section_label}
            </span>
            <span lang={citation.language} className="block text-fg-muted">
              {snippet(citation.text)}
            </span>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}
