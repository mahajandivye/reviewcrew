import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import {
  cleanSuggestion,
  formatDateTime,
  formatDuration,
  groupFindingsByFile,
  shortSha,
  timeAgo,
} from '../lib/format.js'
import DiffViewer from '../components/DiffViewer.jsx'
import SuggestionDiff from '../components/SuggestionDiff.jsx'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback.jsx'
import {
  IconAlert,
  IconArrowLeft,
  IconChat,
  IconExternal,
  IconFile,
  IconRefresh,
} from '../components/icons.jsx'

const SEV_TEXT = { high: 'text-danger', medium: 'text-warn', low: 'text-ok' }
const SEV_BORDER = { high: 'border-l-danger', medium: 'border-l-warn', low: 'border-l-ok' }
const SOURCE_LABEL = { ai: 'AI', static: 'pyflakes', secret: 'secret scan', rule: 'custom rule' }
const STATUS_TONE = {
  completed: 'text-ok',
  failed: 'text-danger',
  running: 'text-accent',
  queued: 'text-warn',
}

// The three buckets the review is presented in. Severity stays high/medium/low
// internally; these labels are what a reader scans for.
const SECTIONS = [
  { key: 'high', emoji: '🔴', label: 'Critical / Security', dot: 'bg-danger', text: 'text-danger' },
  { key: 'medium', emoji: '🟡', label: 'Bugs / Performance', dot: 'bg-warn', text: 'text-warn' },
  { key: 'low', emoji: '🟢', label: 'Best practices / Style', dot: 'bg-ok', text: 'text-ok' },
]

function getEditableFiles(diff) {
  return (diff?.files || [])
    .filter((file) => !file.is_binary)
    .map((file) => ({
      path: file.path,
      code: file.hunks
        .flatMap((hunk) => hunk.lines)
        .filter((line) => line.kind === 'add')
        .map((line) => line.content)
        .join('\n'),
    }))
    .filter((file) => file.code.length > 0)
}

function Meta({ label, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12.5px] text-muted">{label}</dt>
      <dd className="mt-1 truncate text-[15px] text-ink">{children}</dd>
    </div>
  )
}

function FindingRow({ finding, showPath = false }) {
  const suggestion = cleanSuggestion(finding.suggestion)
  return (
    <article
      className={`border-l-2 ${SEV_BORDER[finding.severity] || 'border-l-line'} pl-3.5 py-1`}
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {showPath && (
        <span className="font-mono text-[12px] text-ink/80">
            {finding.file_path}:{finding.line_number}
          </span>
        )}
        <span className="text-[12px] text-muted">
          {finding.category} · {SOURCE_LABEL[finding.source] || finding.source} · line{' '}
          {finding.line_number}
        </span>
      </div>
      <p className="mt-1.5 text-[15px] leading-relaxed text-ink">{finding.message}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
        <span className="rounded-full border border-line px-2 py-0.5">{finding.source === 'ai' ? 'AI confidence' : 'Tool confidence'} {Math.round((finding.confidence ?? (finding.source === 'ai' ? 0.65 : 0.98)) * 100)}%</span>
        {finding.source === 'ai' && Number(finding.confidence ?? 0.65) < 0.7 && <span className="text-warn">Verify this finding</span>}
      </div>
      {finding.evidence && (
        <blockquote className="mt-2 rounded-md border border-line bg-soft px-3 py-2">
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Evidence · {finding.file_path}:{finding.line_number}</span>
          <code className="mt-1 block whitespace-pre-wrap break-words font-mono text-[12.5px] text-ink">{finding.evidence}</code>
        </blockquote>
      )}
      <SuggestionDiff original={finding.original_snippet} suggestion={suggestion} />
    </article>
  )
}

function FindingsList({ findings }) {
  const sections = useMemo(() => {
    return SECTIONS.map((section) => ({
      ...section,
      items: (findings || [])
        .filter((finding) => (finding.severity || '').toLowerCase() === section.key)
        .sort(
          (a, b) =>
            a.file_path.localeCompare(b.file_path) || a.line_number - b.line_number,
        ),
    })).filter((section) => section.items.length > 0)
  }, [findings])

  if (sections.length === 0) {
    return (
      <EmptyState
        icon={<IconFile className="h-5 w-5" />}
        title="No issues found"
        description="Static analysis and the model both came back clean on the changed lines."
      />
    )
  }

  return (
    <div className="space-y-8">
      {sections.map((section) => (
        <section key={section.key}>
          <div className="mb-3 flex items-center gap-2 border-b border-line pb-1.5">
            <span className={`h-2 w-2 rounded-full ${section.dot}`} />
              <span className={`text-[14px] font-semibold ${section.text}`}>
              {section.emoji} {section.label}
            </span>
            <span className="ml-auto text-[12.5px] text-muted">
              {section.items.length} {section.items.length === 1 ? 'finding' : 'findings'}
            </span>
          </div>
          <div className="space-y-4">
            {section.items.map((finding) => (
              <FindingRow key={finding.id} finding={finding} showPath />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export default function ReviewDetailPage() {
  const { reviewId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [review, setReview] = useState(null)
  const [diff, setDiff] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [view, setView] = useState(searchParams.get('view') === 'diff' ? 'diff' : 'findings')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retrying, setRetrying] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [testsError, setTestsError] = useState('')
  const [selectedFile, setSelectedFile] = useState('')
  const [comparison, setComparison] = useState(null)
  const [editableFiles, setEditableFiles] = useState([])
  const [originalFiles, setOriginalFiles] = useState([])
  const [activeEditFile, setActiveEditFile] = useState('')
  const [submittingEdit, setSubmittingEdit] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [reviewData, diffData, metricsData] = await Promise.all([
        api.review(reviewId),
        api.reviewDiff(reviewId).catch(() => null),
        api.reviewMetrics(reviewId).catch(() => null),
      ])
      setReview(reviewData)
      setDiff(diffData)
      setMetrics(metricsData)
      setSelectedFile(diffData?.files?.[0]?.path || '')
      const pastedFiles = getEditableFiles(diffData)
      setOriginalFiles(pastedFiles)
      setEditableFiles(pastedFiles)
      setActiveEditFile(pastedFiles[0]?.path || '')
      setComparison(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [reviewId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!review || !['queued', 'running'].includes(review.status)) return undefined
    const timer = window.setInterval(() => {
      api.review(reviewId).then(setReview).catch(() => {})
    }, 1500)
    return () => window.clearInterval(timer)
  }, [review?.status, reviewId])

  useEffect(() => {
    if (!review || review.status !== 'completed') {
      setComparison(null)
      return undefined
    }
    let active = true
    async function compareWithPrevious() {
      const history = await api.reviews({ page: 1, pageSize: 100, repo: review.repo_name }).catch(() => null)
      const previous = history?.items?.find((item) =>
        item.id < review.id && item.status === 'completed' &&
        item.pr_number === review.pr_number &&
        (review.pr_number > 0 || item.source === review.source),
      )
      if (!previous) return
      const oldReview = await api.review(previous.id).catch(() => null)
      if (!oldReview || !active) return
      const signature = (finding) => `${finding.file_path}:${finding.category}:${finding.message.trim().toLowerCase()}`
      const oldKeys = new Set((oldReview.findings || []).map(signature))
      const newKeys = new Set((review.findings || []).map(signature))
      setComparison({
        previous,
        added: (review.findings || []).filter((finding) => !oldKeys.has(signature(finding))).length,
        resolved: (oldReview.findings || []).filter((finding) => !newKeys.has(signature(finding))).length,
      })
    }
    compareWithPrevious()
    return () => { active = false }
  }, [review?.id, review?.status, reviewId])

  async function handleRetry() {
    setRetrying(true)
    setError('')
    try {
      await api.retryReview(reviewId)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setRetrying(false)
    }
  }

  async function handleGenerateTests() {
    setGenerating(true)
    setTestsError('')
    try {
      const result = await api.generateTests(reviewId)
      setReview((prev) => (prev ? { ...prev, generated_tests: result.tests } : prev))
      setView('tests')
    } catch (err) {
      setTestsError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  async function handleReviewEdits() {
    const files = editableFiles.filter((file) => file.code.trim())
    if (!files.length) {
      setError('Add code to at least one file before starting a review.')
      return
    }
    setSubmittingEdit(true)
    setError('')
    try {
      const payload = review.source === 'code' && files.length === 1
        ? { source: 'code', file_path: files[0].path, code: files[0].code, title: review.pr_title }
        : { source: 'files', files, title: review.pr_title }
      const nextReview = await api.createReview(payload)
      navigate(`/reviews/${nextReview.id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmittingEdit(false)
    }
  }

  function updateEditedCode(path, code) {
    setEditableFiles((current) => current.map((file) => file.path === path ? { ...file, code } : file))
  }

  if (loading && !review) {
    return (
      <div className="h-full overflow-y-auto overscroll-contain">
        <div className="mx-auto max-w-7xl space-y-5 px-6 py-10" aria-busy="true">
          <div className="h-4 w-40 animate-pulse rounded bg-panel2" />
          <div className="h-9 w-2/3 animate-pulse rounded bg-panel2" />
          <div className="h-24 animate-pulse rounded-lg bg-panel2" />
          <div className="h-64 animate-pulse rounded-lg bg-panel2" />
        </div>
      </div>
    )
  }

  if (!review) {
    return (
      <div className="h-full overflow-y-auto overscroll-contain">
        <div className="mx-auto max-w-4xl space-y-4 px-6 py-10">
          <Link to="/" className="text-[13px] text-muted hover:text-ink">
            ← workspace
          </Link>
          <ErrorBanner message={error || 'Review not found.'} onRetry={load} />
        </div>
      </div>
    )
  }

  const counts = review.counts_by_severity || {}
  const files = diff?.files || []
  const hasDiff = Boolean(diff?.has_diff && files.length)
  const isFailed = review.status === 'failed'
  const canEditPasted = ['code', 'files'].includes(review.source) && editableFiles.length > 0
  const hasEdits = editableFiles.some((file, index) => file.code !== originalFiles[index]?.code)
  const secretCount = review.findings.filter((item) => item.source === 'secret').length

  return (
    <div className="h-full overflow-y-auto overscroll-contain">
    <div className="mx-auto w-full max-w-7xl px-6 py-8">
      <div className="flex items-center gap-2 text-[13px] text-muted">
        <button type="button" onClick={() => navigate('/')} className="hover:text-ink">
          workspace
        </button>
        <span className="text-line">/</span>
        <span className="truncate text-ink">
          {review.pr_number > 0 ? `${review.repo_name} #${review.pr_number}` : review.pr_title}
        </span>
      </div>

      {error && <div className="mt-4"><ErrorBanner message={error} onRetry={load} /></div>}

      {/* Header */}
      <header className="mt-4 border-b border-line pb-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px]">
          <span className={`flex items-center gap-1.5 ${STATUS_TONE[review.status] || 'text-muted'}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {review.status}
          </span>
          <span className="text-muted">commit {shortSha(review.head_sha)}</span>
          <span className="text-muted">{review.source === 'github' ? 'pull request' : 'pasted'}</span>
        </div>

        <h1 className="mt-2 max-w-4xl text-[30px] font-semibold leading-tight tracking-tight text-ink sm:text-[36px]">
          {review.pr_title || `Review #${review.id}`}
        </h1>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link
            to={`/?review=${review.id}`}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-3 py-2 text-[14px] font-medium text-onaccent transition hover:bg-accenth"
          >
            <IconChat className="h-3.5 w-3.5" />
            Ask about this
          </Link>
          {review.pr_url && (
            <a
              href={review.pr_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-[14px] text-ink transition hover:border-accent/50"
            >
              <IconExternal className="h-3.5 w-3.5" />
              Pull request
            </a>
          )}
          {isFailed && (
            <button
              type="button"
              onClick={handleRetry}
              disabled={retrying}
              className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-[14px] text-ink transition hover:border-accent/50 disabled:opacity-60"
            >
              {retrying ? <Spinner className="h-3.5 w-3.5" /> : <IconRefresh className="h-3.5 w-3.5" />}
              Retry
            </button>
          )}
          <span className="ml-auto font-mono text-[10px] text-muted">
            {timeAgo(review.created_at)}
          </span>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
          <Meta label="Findings">{review.findings_count}</Meta>
          <Meta label="Files">{review.files_changed}</Meta>
          <Meta label="Lines">
            <span className="text-ok">+{review.additions}</span>{' '}
            <span className="text-danger">−{review.deletions}</span>
          </Meta>
          <Meta label="Duration">{formatDuration(review.duration_seconds)}</Meta>
          <Meta label="Completed">
            <span title={formatDateTime(review.completed_at)}>
              {review.completed_at ? timeAgo(review.completed_at) : '—'}
            </span>
          </Meta>
          <Meta label="Author">{review.pr_author || '—'}</Meta>
        </dl>
      </header>

      {comparison && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-panel px-4 py-3 text-[13px]">
          <span className="font-medium text-ink">Compared with previous review</span>
          <span className="text-danger">{comparison.added} new</span>
          <span className="text-ok">{comparison.resolved} resolved</span>
          <Link to={`/reviews/${comparison.previous.id}`} className="ml-auto text-muted underline underline-offset-2 hover:text-ink">
            Review #{comparison.previous.id}
          </Link>
        </div>
      )}

      {secretCount > 0 && (
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-danger/40 bg-danger/5 px-4 py-3">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div>
            <p className="text-[15px] font-semibold text-danger">
              {secretCount} hardcoded secret{secretCount === 1 ? '' : 's'} detected
            </p>
            <p className="mt-1 text-[14px] leading-relaxed text-ink/80">
              Rotate the credential now, then move it to <code className="font-mono">.env</code> and
              make sure <code className="font-mono">.env</code> is in{' '}
              <code className="font-mono">.gitignore</code>.
            </p>
          </div>
        </div>
      )}

      {metrics?.available && metrics.maintainability?.grade && (
        <div className="mt-4">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
            {[
              {
                label: 'Maintainability',
                value: `${metrics.maintainability.grade} · ${metrics.maintainability.score}`,
              },
              { label: 'Avg complexity', value: metrics.complexity?.average ?? '—' },
              { label: 'Max complexity', value: metrics.complexity?.max ?? '—' },
              { label: 'Max nesting', value: metrics.complexity?.max_nesting ?? '—' },
              { label: 'Functions', value: metrics.totals?.functions ?? 0 },
              { label: 'Code lines', value: metrics.totals?.code_lines ?? 0 },
            ].map((item) => (
              <div key={item.label} className="bg-bg px-3 py-2.5">
                <p className="text-[12px] uppercase tracking-[0.08em] text-muted">{item.label}</p>
                <p className="mt-1 text-[16px] font-semibold text-ink">{item.value}</p>
              </div>
            ))}
          </div>
          {metrics.bottleneck_warnings?.length > 0 && (
            <div className="mt-3 space-y-2" aria-label="Estimated bottleneck warnings">
              {metrics.bottleneck_warnings.map((warning, index) => (
                <div
                  key={`${warning.path}:${warning.line}:${index}`}
                className="rounded-lg border border-warn/30 bg-warn/5 px-3.5 py-2.5 text-[14px]"
                >
                  <span className="font-mono text-muted">
                    {warning.path}:{warning.line}
                  </span>
                  <span className="ml-2 text-ink">{warning.message}</span>
                </div>
              ))}
              <p className="text-[12px] text-muted">
                Estimated from Python syntax; confirm with profiling.
              </p>
            </div>
          )}
        </div>
      )}

      {review.error_message && (
        <div
          className={`mt-4 border-l-2 pl-3 py-1 text-[12.5px] leading-relaxed ${
            isFailed ? 'border-l-danger text-danger' : 'border-l-warn text-warn'
          }`}
        >
          <span className="text-[11px]">
            {isFailed ? 'Failed' : 'Note'}
          </span>
          <p className="mt-0.5 text-ink/90">{review.error_message}</p>
        </div>
      )}

      {/* Tabs + counts */}
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3 border-b border-line">
        <div className="flex gap-5">
          {[
            { id: 'findings', label: 'Findings' },
            { id: 'diff', label: 'Diff' },
            { id: 'tests', label: 'Tests' },
            ...(canEditPasted ? [{ id: 'edit', label: 'Edit code' }] : []),
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setView(tab.id)}
              className={`-mb-px border-b-2 pb-2.5 text-[15px] font-medium transition ${
                view === tab.id
                  ? 'border-accent text-ink'
                  : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {tab.label}
              {tab.id === 'findings' && (
          <span className="ml-1.5 font-mono text-[12px] text-muted">
                  {review.findings_count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-4 pb-2 text-[13px]">
          <span className="text-danger">{counts.high || 0} high</span>
          <span className="text-warn">{counts.medium || 0} med</span>
          <span className="text-accent">{counts.low || 0} low</span>
        </div>
      </div>

      <div className="pt-6">
        {view === 'tests' ? (
          <TestsPanel
            review={review}
            generating={generating}
            error={testsError}
            onGenerate={handleGenerateTests}
          />
        ) : view === 'edit' && canEditPasted ? (
          <CodeEditor
            files={editableFiles}
            originalFiles={originalFiles}
            activePath={activeEditFile}
            onSelect={setActiveEditFile}
            onChange={updateEditedCode}
            onReset={() => setEditableFiles(originalFiles.map((file) => ({ ...file })))}
            onReview={handleReviewEdits}
            hasEdits={hasEdits}
            submitting={submittingEdit}
            status={review.status}
          />
        ) : view === 'findings' ? (
          <FindingsList findings={review.findings} />
        ) : hasDiff ? (
          <DiffViewer
            files={files}
            findings={review.findings}
            selectedPath={selectedFile}
            onSelect={setSelectedFile}
          />
        ) : (
          <EmptyState
            icon={<IconFile className="h-5 w-5" />}
            title="No diff stored for this review"
            description={
              isFailed
                ? 'The review failed before the pull request could be fetched, so there is no diff. Fix the problem above and retry.'
                : 'This review had no textual changes (empty or binary-only diff).'
            }
          />
        )}
      </div>
    </div>
    </div>
  )
}

function TestsPanel({ review, generating, error, onGenerate }) {
  const [copied, setCopied] = useState(false)
  const tests = review.generated_tests

  async function copy() {
    try {
      await navigator.clipboard?.writeText(tests)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked */
    }
  }

  if (!tests) {
    return (
      <div className="space-y-4">
        {error && <ErrorBanner message={error} onRetry={onGenerate} />}
        <EmptyState
          icon={<IconFile className="h-5 w-5" />}
          title="No tests generated yet"
          description="Generate a pytest file that covers the risky behaviour found in this review. Python only for now."
          action={
            <button
              type="button"
              onClick={onGenerate}
              disabled={generating}
              className="inline-flex items-center gap-2 rounded-xl bg-accent px-3.5 py-2 text-sm font-medium text-onaccent transition hover:bg-accenth disabled:opacity-60"
            >
              {generating ? <Spinner /> : null}
              {generating ? 'Writing tests…' : 'Generate unit tests'}
            </button>
          }
        />
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-soft px-3 py-2">
        <span className="text-[12px] font-medium text-ink">Generated tests</span>
        <span className="text-[11px] text-muted">pytest</span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            onClick={copy}
            className="rounded-md border border-line bg-panel px-2 py-1 text-[11.5px] text-ink hover:bg-soft"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="rounded-md border border-line bg-panel px-2 py-1 text-[11.5px] text-ink hover:bg-soft disabled:opacity-60"
          >
            {generating ? 'Regenerating…' : 'Regenerate'}
          </button>
        </div>
      </div>
      {error && <div className="px-3 pt-2"><ErrorBanner message={error} /></div>}
      <pre className="overflow-x-auto bg-code px-4 py-3 font-mono text-[12.5px] leading-6 text-codeink">
        {tests}
      </pre>
    </div>
  )
}

function CodeEditor({
  files,
  originalFiles,
  activePath,
  onSelect,
  onChange,
  onReset,
  onReview,
  hasEdits,
  submitting,
  status,
}) {
  const activeFile = files.find((file) => file.path === activePath) || files[0]
  const busy = submitting || ['queued', 'running'].includes(status)

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-soft px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ink">Edit your pasted code</h2>
          <p className="mt-0.5 text-[12px] text-muted">Make changes, then run the review again.</p>
        </div>
        {files.length > 1 && (
          <label className="flex items-center gap-2 text-[12px] text-muted">
            File
            <select
              value={activeFile?.path || ''}
              onChange={(event) => onSelect(event.target.value)}
              className="max-w-[min(48vw,24rem)] rounded-lg border border-line bg-panel px-2.5 py-2 text-[13px] text-ink"
            >
              {files.map((file) => <option key={file.path} value={file.path}>{file.path}</option>)}
            </select>
          </label>
        )}
      </div>

      {activeFile && (
        <div>
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
            <code className="truncate font-mono text-[12px] text-muted">{activeFile.path}</code>
            <span className="shrink-0 text-[11px] text-muted">
              {activeFile.code.split('\n').length} lines
              {activeFile.code !== originalFiles.find((file) => file.path === activeFile.path)?.code && ' · edited'}
            </span>
          </div>
          <textarea
            aria-label={`Edit source code in ${activeFile.path}`}
            value={activeFile.code}
            onChange={(event) => onChange(activeFile.path, event.target.value)}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            className="block min-h-[420px] w-full resize-y bg-code px-4 py-4 font-mono text-[13px] leading-6 text-codeink outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
        <p className="mr-auto max-w-xl text-[11.5px] leading-relaxed text-muted">
          Your edits are reviewed with the same security scan, custom rules, and reviewer persona. Code is analyzed, never executed.
        </p>
        <button
          type="button"
          onClick={onReset}
          disabled={!hasEdits || submitting}
          className="min-h-9 rounded-lg border border-line px-3 py-2 text-[12.5px] font-medium text-ink transition hover:bg-soft disabled:cursor-not-allowed disabled:opacity-45"
        >
          Reset edits
        </button>
        <button
          type="button"
          onClick={onReview}
          disabled={!hasEdits || busy}
          className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-[12.5px] font-semibold text-onaccent transition hover:bg-accenth disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting || ['queued', 'running'].includes(status) ? <Spinner className="h-3.5 w-3.5" /> : null}
          {submitting ? 'Starting review…' : ['queued', 'running'].includes(status) ? 'Review in progress…' : 'Review changes'}
        </button>
      </div>
    </section>
  )
}
