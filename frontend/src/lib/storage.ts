const PREFIX = 'ys.'

/** localStorage can throw in private windows or when storage is blocked. */
export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // Storage full or unavailable; the app keeps working without persistence.
  }
}

export function removeStored(key: string): void {
  try {
    window.localStorage.removeItem(PREFIX + key)
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}

export function clearAllStored(): void {
  try {
    const keys: string[] = []
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i)
      if (key?.startsWith(PREFIX)) keys.push(key)
    }
    keys.forEach((key) => window.localStorage.removeItem(key))
  } catch {
    // Nothing stored to clear.
  }
}
