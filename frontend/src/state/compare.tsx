import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { readStored, writeStored } from '../lib/storage'

export const COMPARE_LIMIT = 3

interface CompareState {
  ids: string[]
  has: (id: string) => boolean
  toggle: (id: string) => boolean
  remove: (id: string) => void
  clear: () => void
}

const CompareContext = createContext<CompareState | null>(null)

export function CompareProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<string[]>(() => readStored('compare', []))

  useEffect(() => writeStored('compare', ids), [ids])

  const has = useCallback((id: string) => ids.includes(id), [ids])
  const toggle = useCallback(
    (id: string) => {
      if (ids.includes(id)) {
        setIds(ids.filter((existing) => existing !== id))
        return true
      }
      if (ids.length >= COMPARE_LIMIT) return false
      setIds([...ids, id])
      return true
    },
    [ids],
  )
  const remove = useCallback(
    (id: string) => setIds((current) => current.filter((x) => x !== id)),
    [],
  )
  const clear = useCallback(() => setIds([]), [])

  const value = useMemo(
    () => ({ ids, has, toggle, remove, clear }),
    [ids, has, toggle, remove, clear],
  )
  return <CompareContext.Provider value={value}>{children}</CompareContext.Provider>
}

export function useCompare(): CompareState {
  const context = useContext(CompareContext)
  if (!context) throw new Error('useCompare must be used inside CompareProvider')
  return context
}
