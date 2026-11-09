export function Logo({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="var(--teal)" />
      <path
        d="M18 34c0-7.7 6.3-14 14-14s14 6.3 14 14"
        fill="none"
        stroke="var(--sand)"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <circle cx="32" cy="41" r="7" fill="var(--marigold)" />
    </svg>
  )
}
