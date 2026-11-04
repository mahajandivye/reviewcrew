import { Fragment, useMemo } from 'react'
import { cleanSuggestion } from '../lib/format.js'
import { SeverityBadge, SourceBadge } from './Badges.jsx'
import FileTree from './FileTree.jsx'
import { IconAlert } from './icons.jsx'

/**
 * Split diff viewer.
 *
 * A note on the library choice: `react-diff-viewer-continued` (the usual
 * suggestion) expects the FULL old and new file contents so it can compute a
 * diff again in the browser. We do not have those files - we only store the
 * unified diff we received from GitHub, which is what the findings' line
 * numbers refer to. Re-diffing would risk drifting from those anchors, so this
 * component renders the authoritative hunks directly: same split layout,
 * exact line numbers, and annotations that cannot land on the wrong line.
 */

/** Pair removed/added lines like GitHub's split view. */
function buildRows(lines) {
  const rows = []
  let removed = []
  let added = []

  const flush = () => {
    const max = Math.max(removed.length, added.length)
    for (let index = 0; index < max; index += 1) {
      rows.push({ old: removed[index] || null, new: added[index] || null })
    }
    removed = []
    added = []
  }

  for (const line of lines) {
    if (line.kind === 'del') {
      removed.push(line)
    } else if (line.kind === 'add') {
      added.push(line)
    } else {
      flush()
      rows.push({ old: line, new: line, context: true })
    }
  }
  flush()
  return rows
}

function lineNumber(value) {
  return value === null || value === undefined ? '' : value
}

function Cell({ line }) {
  if (!line) {
    return <div className="bg-panel2/50" />
  }

  const isAdd = line.kind === 'add'
  const isDel = line.kind === 'del'
  const tone = isAdd
    ? 'bg-ok/10'
    : isDel
      ? 'bg-danger/10'
      : ''

  return (
    <div className={`flex min-w-0 ${tone}`}>
      <span className="w-12 shrink-0 select-none border-r border-line py-1 pr-2 text-right font-mono text-[12px] leading-5 text-muted/70">
        {lineNumber(line.new_line ?? line.old_line)}
      </span>
      <span
        className={`w-4 shrink-0 select-none text-center font-mono text-[12px] leading-5 ${
          isAdd
            ? 'text-ok'
            : isDel
              ? 'text-danger'
              : 'text-transparent'
        }`}
      >
        {isAdd ? '+' : isDel ? '-' : ' '}
      </span>
      <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre px-2.5 py-1 font-mono text-[13.5px] leading-6 text-ink">
        {line.content === '' ? ' ' : line.content}
      </pre>
    </div>
  )
}

function Annotation({ finding }) {
  const border = {
    high: 'border-l-danger',
    medium: 'border-l-warn',
    low: 'border-l-accent',
  }[finding.severity] || 'border-l-line'

  return (
    <div
      className={`border-l-2 ${border} bg-panel px-3.5 py-2.5 border-y border-y-line`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <SourceBadge source={finding.source} />
        <span className="text-[12px] uppercase tracking-wide text-muted/70">
          {finding.category} · line {finding.line_number}
        </span>
      </div>
      <p className="mt-1.5 text-[14px] leading-relaxed text-ink">{finding.message}</p>
      {finding.suggestion && (
        <pre className="mt-2 overflow-x-auto rounded-lg bg-code p-2.5 font-mono text-[13px] leading-6 text-ink border border-line">
          {cleanSuggestion(finding.suggestion)}
        </pre>
      )}
    </div>
  )
}

function Hunk({ hunk, findingsByLine }) {
  const rows = buildRows(hunk.lines)

  return (
    <div className="min-w-[560px]">
      <div className="border-y border-y border-line bg-panel2 px-3 py-1.5 font-mono text-[12px] text-muted">
        {hunk.header}
        {hunk.section ? <span className="ml-2 opacity-70">{hunk.section}</span> : null}
      </div>

      {rows.map((row, index) => {
        const lineFindings = row.new?.new_line
          ? findingsByLine.get(row.new.new_line) || []
          : []

        return (
          <Fragment key={`${hunk.header}-${index}`}>
            <div className="grid grid-cols-2 divide-x divide-line">
              <Cell line={row.old} />
              <Cell line={row.new} />
            </div>
            {lineFindings.map((finding) => (
              <Annotation key={finding.id} finding={finding} />
            ))}
          </Fragment>
        )
      })}
    </div>
  )
}

export default function DiffViewer({ files, findings, selectedPath, onSelect }) {
  const findingsByFile = useMemo(() => {
    const map = new Map()
    for (const finding of findings) {
      if (!map.has(finding.file_path)) map.set(finding.file_path, [])
      map.get(finding.file_path).push(finding)
    }
    return map
  }, [findings])

  const selected = files.find((file) => file.path === selectedPath) || files[0]
  if (!selected) return null

  const fileFindings = findingsByFile.get(selected.path) || []
  const anchoredLines = new Set(
    selected.hunks.flatMap((hunk) =>
      hunk.lines.filter((line) => line.new_line).map((line) => line.new_line),
    ),
  )
  const anchored = fileFindings.filter((finding) => anchoredLines.has(finding.line_number))
  const floating = fileFindings.filter((finding) => !anchoredLines.has(finding.line_number))

  const findingsByLine = new Map()
  for (const finding of anchored) {
    if (!findingsByLine.has(finding.line_number)) findingsByLine.set(finding.line_number, [])
    findingsByLine.get(finding.line_number).push(finding)
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
      {/* File tree */}
      <aside className="rounded-2xl border border-line bg-panel p-2.5">
        <p className="px-2 pb-2 text-[12px] font-semibold uppercase tracking-wide text-muted/70">
          Changed files ({files.length})
        </p>
        <div className="max-h-[26rem] overflow-y-auto">
          <FileTree
            files={files}
            selected={selected.path}
            onSelect={onSelect}
            findingsByFile={findingsByFile}
          />
        </div>
      </aside>

      {/* Diff */}
      <div className="min-w-0 overflow-hidden rounded-lg border border-line bg-panel">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5 ">
          <span className="truncate font-mono text-[14px] font-medium text-ink">
            {selected.path}
          </span>
          {selected.old_path && selected.old_path !== selected.path && (
            <span className="truncate text-[13px] text-muted">← {selected.old_path}</span>
          )}
          <span className="ml-auto flex items-center gap-2 text-[13px]">
            <span className="text-ok">+{selected.additions}</span>
            <span className="text-danger">−{selected.deletions}</span>
            <span className="rounded-full bg-panel2 px-2 py-0.5 text-muted">
              {selected.language}
            </span>
          </span>
        </div>

        {floating.length > 0 && (
          <div className="border-b border-b border-line bg-warn/5 px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[13px] font-medium text-warn">
              <IconAlert className="h-3.5 w-3.5" />
              {floating.length} finding{floating.length === 1 ? '' : 's'} on lines outside this
              diff
            </p>
            {floating.map((finding) => (
              <p key={finding.id} className="mt-1 text-[13px] text-muted">
                <span className="font-mono">line {finding.line_number}</span> — {finding.message}
              </p>
            ))}
          </div>
        )}

        {selected.is_binary ? (
          <p className="px-4 py-10 text-center text-[12.5px] text-muted">
            Binary file — no text diff to display.
          </p>
        ) : selected.hunks.length === 0 ? (
          <p className="px-4 py-10 text-center text-[12.5px] text-muted">
            {selected.status === 'removed'
              ? 'This file was deleted — no new lines to review.'
              : 'No diff hunks were stored for this file.'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            {selected.hunks.map((hunk) => (
              <Hunk key={hunk.header} hunk={hunk} findingsByLine={findingsByLine} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
