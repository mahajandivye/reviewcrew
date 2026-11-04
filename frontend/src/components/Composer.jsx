import { useEffect, useRef, useState } from 'react'
import { IconChat, IconCode, IconDiff, IconExternal, IconPlus, IconSend } from './icons.jsx'

const MODES = [
  {
    id: 'ask',
    label: 'Ask',
    hint: 'Ask about a finding or a diff',
    icon: IconChat,
    placeholder: 'Ask anything',
  },
  {
    id: 'code',
    label: 'Review code',
    hint: 'Full-file review of a pasted file',
    icon: IconCode,
    placeholder: 'Paste a file to review',
  },
  {
    id: 'diff',
    label: 'Review diff',
    hint: 'Only the lines that changed',
    icon: IconDiff,
    placeholder: 'Paste a unified diff (@@ hunks)',
  },
  {
    id: 'files',
    label: 'Files',
    hint: 'Several files, reviewed together',
    icon: IconCode,
    placeholder: '=== app/models.py ===\nclass User: ...\n=== app/routes.py ===\nfrom app.models import User',
  },
  {
    id: 'pr',
    label: 'Pull request',
    hint: 'Fetch a GitHub PR by URL',
    icon: IconExternal,
    placeholder: 'Paste a pull request URL',
  },
]

/**
 * The composer is the product's front door: one bar that can start a review or
 * ask a question. The "+" menu switches intent explicitly, so pasting a diff is
 * never mistaken for a chat message.
 */
export default function Composer({
  onSubmit,
  busy,
  context,
  onClearContext,
  mode = 'ask',
  onModeChange,
  initialText = '',
  initialFilePath = '',
  reviewerPersona = 'balanced',
  onReviewerPersonaChange,
  personaSaving = false,
  personaNotice = '',
}) {
  const [text, setText] = useState(initialText)
  const [filePath, setFilePath] = useState(initialFilePath)
  const [menuOpen, setMenuOpen] = useState(false)
  const textareaRef = useRef(null)
  const menuRef = useRef(null)

  const active = MODES.find((item) => item.id === mode) || MODES[0]

  useEffect(() => {
    if (!busy) textareaRef.current?.focus()
  }, [busy])

  useEffect(() => {
    if (!menuOpen) return undefined
    const close = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  function pickMode(next) {
    onModeChange?.(next)
    setMenuOpen(false)
    setText('')
    setFilePath('')
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  function submit() {
    const value = text.trim()
    if (!value || busy) return
    // Same shape the backend accepts: a real https URL, with or without www.
    if (mode === 'pr' && !/^https?:\/\/(?:www\.)?github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+/.test(value)) {
      onSubmit({
        mode,
        error:
          'That does not look like a pull request URL. Expected https://github.com/owner/repo/pull/123',
      })
      return
    }
    onSubmit({ mode, text: value, filePath: filePath.trim() || undefined })
    setText('')
  }

  function onKeyDown(event) {
    if (event.key !== 'Enter') return
    if (mode === 'ask') {
      if (!event.shiftKey) {
        event.preventDefault()
        submit()
      }
      return
    }
    if (event.metaKey || event.ctrlKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="w-full">
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2.5 px-2">
        <label htmlFor="reviewer-persona" className="text-[13px] text-muted">
          Code reviewer
        </label>
        <select
          id="reviewer-persona"
          aria-label="Code reviewer persona"
          value={reviewerPersona}
          onChange={(event) => onReviewerPersonaChange?.(event.target.value)}
          disabled={personaSaving}
          className="rounded-full border border-line bg-panel px-3.5 py-1.5 text-[13.5px] text-ink outline-none transition hover:bg-soft disabled:opacity-60"
        >
          <option value="balanced">Balanced senior engineer</option>
          <option value="security">Security specialist</option>
          <option value="performance">Performance specialist</option>
          <option value="mentor">Supportive mentor</option>
        </select>
        {personaSaving && <span className="text-[12px] text-muted">Saving…</span>}
        {personaNotice && <span role="status" className="text-[12px] text-danger">{personaNotice}</span>}
      </div>
      {context && (
        <div className="mb-2.5 flex items-center gap-2 pl-1">
          <span className="inline-flex max-w-full items-center gap-2 rounded-full bg-soft px-3 py-1.5 text-[13px] text-ink">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            <span className="truncate">Context: {context.label}</span>
            <button
              type="button"
              onClick={onClearContext}
              className="ml-0.5 text-muted hover:text-ink"
              aria-label="Clear context"
            >
              ✕
            </button>
          </span>
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
        className="rounded-[26px] border border-line bg-panel shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition focus-within:border-ink/20"
      >
        {mode !== 'ask' && (
          <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
            <span className="inline-flex items-center gap-2 rounded-full bg-soft px-3 py-1.5 text-[13px] text-ink">
              <active.icon className="h-4 w-4" />
              {active.label}
              <button
                type="button"
                onClick={() => pickMode('ask')}
                className="ml-0.5 text-muted hover:text-ink"
                aria-label="Back to Ask"
              >
                ✕
              </button>
            </span>
            {mode === 'code' && (
              <input
                value={filePath}
                onChange={(event) => setFilePath(event.target.value)}
                placeholder="file path (optional)"
                spellCheck={false}
                className="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-placeholder"
              />
            )}
          </div>
        )}

        <div className="flex items-end gap-2 px-3 py-3">
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((value) => !value)}
              aria-label="Choose review mode"
              aria-expanded={menuOpen}
              className={`mb-0.5 grid h-10 w-10 place-items-center rounded-full border text-ink transition hover:bg-soft ${
                menuOpen ? 'border-ink/25 bg-soft' : 'border-line'
              }`}
            >
              <IconPlus className="h-5 w-5" />
            </button>

            {menuOpen && (
              <div className="absolute bottom-12 left-0 z-30 w-72 overflow-hidden rounded-xl border border-line bg-panel p-1.5 shadow-xl">
                {MODES.map((item) => {
                  const Icon = item.icon
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => pickMode(item.id)}
                      className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-soft ${
                        mode === item.id ? 'bg-soft' : ''
                      }`}
                    >
                      <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0 text-muted" />
                      <span className="min-w-0">
                        <span className="block text-[14px] font-medium text-ink">{item.label}</span>
                        <span className="block text-[13px] leading-snug text-muted">
                          {item.hint}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {mode === 'pr' ? (
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder={active.placeholder}
              spellCheck={false}
              className="min-w-0 flex-1 bg-transparent px-1.5 py-2 text-[17px] text-ink outline-none placeholder:text-placeholder"
            />
          ) : (
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder={active.placeholder}
              rows={1}
              spellCheck={false}
              className="max-h-64 min-w-0 flex-1 resize-none bg-transparent px-1.5 py-2 text-[17px] leading-7 text-ink outline-none placeholder:text-placeholder"
            />
          )}

          <button
            type="submit"
            disabled={busy || !text.trim()}
            aria-label="Send"
            className="mb-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent text-onaccent transition hover:bg-accenth disabled:cursor-not-allowed disabled:bg-soft disabled:text-placeholder"
          >
            <IconSend className="h-5 w-5" />
          </button>
        </div>
      </form>

      {mode === 'pr' && (
        <p className="mt-2 px-2 text-[13px] leading-relaxed text-muted">
          Paste the URL from the PR page, e.g.{' '}
          <code className="font-mono text-[12px] text-ink">
            https://github.com/owner/repo/pull/123
          </code>
          . Public pull requests work without a token; add one in Settings for private repos and
          comments.
        </p>
      )}

      {mode === 'files' && (
        <p className="mt-2 px-2 text-[13px] leading-relaxed text-muted">
          Start each file with a header line:{' '}
          <code className="font-mono text-[12px] text-ink">=== path/to/file.py ===</code>. Files are
          reviewed together, so cross-file bugs are visible.
        </p>
      )}
    </div>
  )
}
