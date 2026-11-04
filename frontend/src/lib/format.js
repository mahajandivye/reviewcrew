/** Small formatting helpers shared by the pages. */

/**
 * The API may return a timestamp without a timezone (SQLite drops it), e.g.
 * "2026-11-02T11:19:57". JavaScript would read that as *local* time while the
 * server stored UTC, so relative times would be hours off. Add the Z back.
 */
export function parseDate(value) {
  if (!value) return null
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
  return new Date(hasZone ? value : `${value}Z`)
}

export function timeAgo(value) {
  const date = parseDate(value)
  if (!date || Number.isNaN(date.getTime())) return '—'

  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  const future = seconds < 0
  const abs = Math.abs(seconds)

  const units = [
    ['year', 31_536_000],
    ['month', 2_592_000],
    ['day', 86_400],
    ['hour', 3_600],
    ['minute', 60],
  ]

  for (const [unit, size] of units) {
    if (abs >= size) {
      const amount = Math.floor(abs / size)
      const label = `${amount} ${unit}${amount === 1 ? '' : 's'}`
      return future ? `in ${label}` : `${label} ago`
    }
  }
  return future ? 'in a moment' : 'just now'
}

export function formatDateTime(value) {
  const date = parseDate(value)
  if (!date || Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 8450 ms -> "8.45s"; 92300 -> "1m 32s" */
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const value = Number(seconds)
  if (!Number.isFinite(value)) return '—'
  if (value < 60) return `${value.toFixed(value < 10 ? 2 : 1)}s`
  const minutes = Math.floor(value / 60)
  const rest = Math.round(value % 60)
  return `${minutes}m ${rest}s`
}

export function shortSha(sha) {
  if (!sha) return '—'
  return sha.slice(0, 7)
}

const numberFormatter = new Intl.NumberFormat()

export function formatNumber(value) {
  if (value === null || value === undefined) return '0'
  return numberFormatter.format(Number(value) || 0)
}

export const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 }

export function groupFindingsByFile(findings) {
  const groups = new Map()
  for (const finding of findings || []) {
    if (!groups.has(finding.file_path)) groups.set(finding.file_path, [])
    groups.get(finding.file_path).push(finding)
  }
  return [...groups.entries()]
    .map(([path, items]) => ({
      path,
      items: [...items].sort(
        (a, b) =>
          (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) ||
          a.line_number - b.line_number,
      ),
    }))
    .sort((a, b) => a.path.localeCompare(b.path))
}

/** Strip ``` fences so suggestions display as plain code/text. */
export function cleanSuggestion(text) {
  if (!text) return ''
  return text.replace(/```[a-zA-Z0-9]*\n?/g, '').replace(/```/g, '').trim()
}
