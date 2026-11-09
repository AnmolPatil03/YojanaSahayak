import { useMemo } from 'react'
import { cssVarRgb } from '../lib/color'
import { usePreferences } from '../state/preferences'

function rgb(name: string, alpha = 1): string {
  const [r, g, b] = cssVarRgb(name)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Resolved theme colours for SVG chart attributes, which cannot read CSS variables. */
export function useThemeColors() {
  const { theme } = usePreferences()
  return useMemo(() => {
    const fg = theme === 'dark' ? '--sand' : '--teal'
    return {
      theme,
      accent: rgb('--marigold'),
      fg: rgb(fg),
      muted: rgb(fg, 0.6),
      grid: rgb(fg, 0.15),
      series: [rgb(fg, 0.35), rgb(fg, 0.55), rgb(fg, 0.8), rgb('--marigold')],
    }
  }, [theme])
}
