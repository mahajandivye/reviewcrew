/**
 * Small pills used in the diff viewer and anywhere a finding needs a label.
 * Colour carries severity; the label carries the meaning, so it survives
 * greyscale and colour-blindness.
 */

const SEVERITY = {
  high: 'border-danger/40 text-danger',
  medium: 'border-warn/40 text-warn',
  low: 'border-accent/40 text-accent',
}

const SOURCE = {
  ai: 'border-line text-muted',
  static: 'border-line text-muted',
  secret: 'border-danger/40 text-danger',
  rule: 'border-warn/40 text-warn',
}

const SOURCE_LABEL = { ai: 'AI', static: 'pyflakes', secret: 'secret scan', rule: 'custom rule' }

function Pill({ className = '', children, title }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${className}`}
    >
      {children}
    </span>
  )
}

export function SeverityBadge({ severity }) {
  const key = (severity || 'low').toLowerCase()
  return <Pill className={SEVERITY[key] || SEVERITY.low}>{key}</Pill>
}

export function SourceBadge({ source }) {
  const key = (source || 'ai').toLowerCase()
  return (
    <Pill className={SOURCE[key] || SOURCE.ai} title={`Reported by ${key}`}>
      {SOURCE_LABEL[key] || key}
    </Pill>
  )
}

export function CategoryBadge({ category }) {
  return <Pill className="border-line text-muted">{category}</Pill>
}

export function StatusBadge({ status }) {
  const key = (status || 'queued').toLowerCase()
  const tone =
    key === 'completed'
      ? 'text-ok'
      : key === 'failed'
        ? 'text-danger'
        : key === 'running'
          ? 'text-accent'
          : 'text-warn'
  return (
    <Pill className={`border-line ${tone}`}>
      <span className="h-1 w-1 rounded-full bg-current" />
      {key}
    </Pill>
  )
}
