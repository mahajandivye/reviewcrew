import { IconAlert, IconRefresh } from './icons.jsx'

export function ErrorBanner({ message, onRetry }) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="flex items-start gap-3 border-l-2 border-l-danger bg-panel px-3 py-2.5"
    >
      <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] leading-relaxed text-ink">{message}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex shrink-0 items-center gap-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted hover:text-ink"
        >
          <IconRefresh className="h-3 w-3" />
          retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center border border-dashed border-line bg-panel px-6 py-14 text-center">
      <div className="text-muted">{icon}</div>
      <h3 className="mt-3 text-[17px] font-semibold text-ink">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-muted">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Spinner({ className = 'h-4 w-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function LoadingBlock({ rows = 3 }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-14 animate-pulse rounded-md bg-panel2" />
      ))}
    </div>
  )
}
