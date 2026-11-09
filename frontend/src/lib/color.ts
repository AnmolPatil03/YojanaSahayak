/** Read a hex colour custom property (for canvas drawing) as an [r, g, b] triple. */
export function cssVarRgb(name: string): [number, number, number] {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const hex = value.replace('#', '')
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex
  const parsed = Number.parseInt(full, 16)
  if (Number.isNaN(parsed) || full.length !== 6) return [128, 128, 128]
  return [(parsed >> 16) & 255, (parsed >> 8) & 255, parsed & 255]
}
