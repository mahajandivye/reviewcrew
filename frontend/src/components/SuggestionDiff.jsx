import { useState } from 'react'

/**
 * A suggested fix the developer can actually use: copy it, or see the exact
 * before/after. "Before" comes from the stored line snapshot, so it stays
 * accurate even if the file changed after the review ran.
 */
export default function SuggestionDiff({ original, suggestion }) {
  const [showDiff, setShowDiff] = useState(false)
  const [copied, setCopied] = useState(false)

  if (!suggestion) return null

  async function copy() {
    try {
      await navigator.clipboard?.writeText(suggestion)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked - the code is still selectable */
    }
  }

  return (
    <div className="mt-2.5 overflow-hidden rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-soft px-2.5 py-1.5">
        <span className="text-[13px] font-medium text-muted">Suggested fix</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setShowDiff((value) => !value)}
            className="rounded-md px-2.5 py-1.5 text-[13px] text-muted transition hover:bg-line/60 hover:text-ink"
          >
            {showDiff ? 'Hide diff' : 'Show diff'}
          </button>
          <button
            type="button"
            onClick={copy}
            className="rounded-md bg-accent px-2.5 py-1.5 text-[13px] font-medium text-onaccent transition hover:bg-accenth"
          >
            {copied ? 'Copied' : 'Copy fixed code'}
          </button>
        </div>
      </div>

      {showDiff ? (
        <div className="grid divide-y divide-line sm:grid-cols-2 sm:divide-x sm:divide-y-0">
          <div>
            <p className="px-3 pt-2 text-[11.5px] font-semibold uppercase tracking-[0.1em] text-danger">
              Before
            </p>
            <pre className="max-h-56 overflow-auto px-3 py-2 font-mono text-[13px] leading-6 text-ink">
              {original || '(line not captured for this finding)'}
            </pre>
          </div>
          <div>
            <p className="px-3 pt-2 text-[11.5px] font-semibold uppercase tracking-[0.1em] text-ok">
              After
            </p>
            <pre className="max-h-56 overflow-auto px-3 py-2 font-mono text-[13px] leading-6 text-ink">
              {suggestion}
            </pre>
          </div>
        </div>
      ) : (
        <pre className="max-h-56 overflow-auto bg-code px-3 py-2.5 font-mono text-[13px] leading-6 text-codeink">
          {suggestion}
        </pre>
      )}
    </div>
  )
}
