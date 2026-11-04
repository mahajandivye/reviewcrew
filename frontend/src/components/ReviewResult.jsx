import { Link } from 'react-router-dom'
import { formatDuration } from '../lib/format.js'
import { IconExternal } from './icons.jsx'

const SEV_DOT = {
  high: 'bg-danger',
  medium: 'bg-warn',
  low: 'bg-ok',
}

const STATUS_LABEL = {
  queued: 'Queued',
  running: 'Reviewing',
  completed: 'Completed',
  failed: 'Failed',
}

function Count({ label, value, tone }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${tone}`} />
      <span className="text-[13px] font-medium text-ink">{value}</span>
      <span className="text-[11.5px] text-muted">{label}</span>
    </span>
  )
}

/**
 * The review, rendered as a message in the conversation.
 * Kept visually quiet: a bordered surface, not a dashboard card.
 */
export default function ReviewResult({ review, findings = [], pending = false }) {
  if (pending) {
    return (
      <div className="rounded-2xl border border-line bg-panel p-4">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink" />
          {review?.status === 'queued' ? 'Queued' : 'Reviewing'}
        </div>
        <p className="mt-2 text-[13.5px] leading-6 text-muted">
          Parsing the diff, running pyflakes and the secret scanner, then asking the model for a
          second opinion.
        </p>
        <div className="mt-3 space-y-1.5">
          {[82, 64, 72].map((width, index) => (
            <div
              key={index}
              className="h-2 animate-pulse rounded bg-soft"
              style={{ width: `${width}%`, animationDelay: `${index * 120}ms` }}
            />
          ))}
        </div>
      </div>
    )
  }

  const counts = review.counts_by_severity || {}
  const total = review.findings_count ?? findings.length
  const top = findings.slice(0, 4)
  const failed = review.status === 'failed'

  return (
    <div className="rounded-2xl border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2">
        <span className="truncate text-[12px] text-muted">
          {review.repo_name}
          {review.pr_number > 0 ? ` · #${review.pr_number}` : ''}
        </span>
        <span className="ml-auto flex items-center gap-2 text-[11.5px]">
          <span className={`h-1.5 w-1.5 rounded-full ${failed ? 'bg-danger' : 'bg-ok'}`} />
          <span className={failed ? 'text-danger' : 'text-muted'}>
            {STATUS_LABEL[review.status] || review.status}
          </span>
          {review.duration_seconds != null && (
            <span className="text-muted">{formatDuration(review.duration_seconds)}</span>
          )}
        </span>
      </div>

      <div className="px-4 py-3.5">
        {failed ? (
          <p className="text-[13.5px] leading-6 text-danger">
            {review.error_message || 'The review could not be completed.'}
          </p>
        ) : total === 0 ? (
          <p className="text-[13.5px] leading-6 text-muted">
            No issues found on the changed lines. Static analysis and the model both came back
            clean.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
              <span className="text-[20px] font-semibold leading-none text-ink">{total}</span>
              <span className="text-[12.5px] text-muted">
                {total === 1 ? 'finding' : 'findings'}
              </span>
              <span className="ml-auto flex flex-wrap items-baseline gap-3">
                <Count label="critical" value={counts.high || 0} tone={SEV_DOT.high} />
                <Count label="bugs" value={counts.medium || 0} tone={SEV_DOT.medium} />
                <Count label="style" value={counts.low || 0} tone={SEV_DOT.low} />
              </span>
            </div>

            {top.length > 0 && (
              <ul className="mt-3 space-y-2 border-t border-line pt-3">
                {top.map((finding) => (
                  <li key={finding.id} className="flex gap-2.5">
                    <span
                      className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${
                        SEV_DOT[finding.severity] || 'bg-muted'
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="truncate font-mono text-[11px] text-muted">
                        {finding.file_path}:{finding.line_number}
                      </p>
                      <p className="line-clamp-2 text-[13px] leading-snug text-ink">
                        {finding.message}
                      </p>
                    </div>
                  </li>
                ))}
                {total > top.length && (
                  <li className="pl-4 text-[11.5px] text-muted">
                    + {total - top.length} more in the full review
                  </li>
                )}
              </ul>
            )}
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2.5">
        <Link
          to={`/reviews/${review.id}`}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-[13px] font-semibold text-onaccent shadow-sm transition hover:bg-accenth focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-panel"
        >
          Open full review <span aria-hidden="true">→</span>
        </Link>
        <Link
          to={`/reviews/${review.id}?view=diff`}
          className="inline-flex min-h-9 items-center rounded-lg border border-line bg-bg px-3.5 py-2 text-[13px] font-medium text-ink shadow-sm transition hover:border-accent/60 hover:bg-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-panel"
        >
          View diff
        </Link>
        {review.pr_url && (
          <a
            href={review.pr_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium text-muted underline decoration-muted/50 underline-offset-4 transition hover:bg-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            GitHub
            <IconExternal className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  )
}
