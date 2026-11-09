import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { compactProfile } from '../lib/format'
import { readStored, removeStored, writeStored } from '../lib/storage'
import type { ProfileField, UserProfile } from '../lib/types'

interface ProfileState {
  profile: UserProfile
  setField: <K extends ProfileField>(field: K, value: UserProfile[K]) => void
  removeField: (field: ProfileField) => void
  merge: (update: UserProfile) => void
  replace: (profile: UserProfile) => void
  clear: () => void
}

const ProfileContext = createContext<ProfileState | null>(null)

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile>(() => readStored('profile', {}))

  useEffect(() => {
    writeStored('profile', compactProfile(profile))
  }, [profile])

  const setField = useCallback(<K extends ProfileField>(field: K, value: UserProfile[K]) => {
    setProfile((current) => compactProfile({ ...current, [field]: value }))
  }, [])
  const removeField = useCallback((field: ProfileField) => {
    setProfile((current) => {
      const next = { ...current }
      delete next[field]
      return next
    })
  }, [])
  const merge = useCallback((update: UserProfile) => {
    setProfile((current) => compactProfile({ ...current, ...compactProfile(update) }))
  }, [])
  const replace = useCallback((next: UserProfile) => setProfile(compactProfile(next)), [])
  const clear = useCallback(() => {
    setProfile({})
    removeStored('profile')
  }, [])

  const value = useMemo(
    () => ({ profile, setField, removeField, merge, replace, clear }),
    [profile, setField, removeField, merge, replace, clear],
  )
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export function useProfile(): ProfileState {
  const context = useContext(ProfileContext)
  if (!context) throw new Error('useProfile must be used inside ProfileProvider')
  return context
}
