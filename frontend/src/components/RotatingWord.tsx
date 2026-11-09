import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'

interface Word {
  text: string
  lang: string
}

/** Cycles a headline word, alternating English and Hindi, with a vertical slide. */
export function RotatingWord({ words, interval = 2600 }: { words: Word[]; interval?: number }) {
  const [index, setIndex] = useState(0)
  const reduce = useReducedMotion()

  useEffect(() => {
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % words.length), interval)
    return () => window.clearInterval(timer)
  }, [words.length, interval])

  const word = words[index] ?? words[0]
  return (
    <span className="relative inline-grid overflow-hidden align-bottom">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={`${word.text}-${index}`}
          lang={word.lang}
          initial={reduce ? { opacity: 0 } : { y: '100%', opacity: 0 }}
          animate={reduce ? { opacity: 1 } : { y: '0%', opacity: 1 }}
          exit={reduce ? { opacity: 0 } : { y: '-100%', opacity: 0 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="col-start-1 row-start-1 whitespace-nowrap rounded-xl bg-accent px-3 text-on-accent"
        >
          {word.text}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}
