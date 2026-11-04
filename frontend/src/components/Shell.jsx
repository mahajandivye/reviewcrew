import { useEffect, useMemo, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useTheme } from '../lib/theme.js'
import {
  IconChevronDown,
  IconMoon,
  IconPanelLeft,
  IconPencil,
  IconPlay,
  IconSearch,
  IconSettings,
  IconSun,
  IconTrash,
} from './icons.jsx'

function groupByDate(items) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000
  const groups = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Earlier', items: [] },
  ]

  for (const item of items) {
    const raw = item.updated_at || item.created_at || ''
    const parsed = new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`)
    const time = parsed.getTime()
    if (Number.isNaN(time)) groups[3].items.push(item)
    else if (time >= startOfToday) groups[0].items.push(item)
    else if (time >= startOfToday - day) groups[1].items.push(item)
    else if (time >= startOfToday - 7 * day) groups[2].items.push(item)
    else groups[3].items.push(item)
  }
  return groups.filter((group) => group.items.length > 0)
}

export default function Shell() {
  const { theme, toggle } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [open, setOpen] = useState(() => window.innerWidth >= 1024)
  const [query, setQuery] = useState('')
  const [conversations, setConversations] = useState([])
  const [apiState, setApiState] = useState('checking')
  const [demoOpen, setDemoOpen] = useState(false)

  const activeId = searchParams.get('c')

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const data = await api.conversations(50)
        if (!cancelled) {
          setConversations(data || [])
          setApiState('ok')
        }
      } catch {
        if (!cancelled) setApiState('offline')
      }
    }

    load()
    const timer = window.setInterval(load, 25_000)
    window.addEventListener('reviewpilot:refresh', load)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('reviewpilot:refresh', load)
    }
  }, [location.pathname, location.search])

  useEffect(() => {
    if (window.innerWidth < 1024) setOpen(false)
  }, [location.pathname, location.search])

  useEffect(() => {
    if (!demoOpen) return undefined
    function closeOnEscape(event) {
      if (event.key === 'Escape') setDemoOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [demoOpen])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return conversations
    return conversations.filter(
      (item) =>
        (item.title || '').toLowerCase().includes(term) ||
        (item.preview || '').toLowerCase().includes(term),
    )
  }, [conversations, query])

  const groups = useMemo(() => groupByDate(filtered), [filtered])

  function startNew() {
    navigate('/', { state: { newChat: Date.now() } })
    if (window.innerWidth < 1024) setOpen(false)
  }

  async function remove(id, event) {
    event.preventDefault()
    event.stopPropagation()
    if (!window.confirm('Delete this chat? This cannot be undone.')) return
    try {
      await api.deleteConversation(id)
      setConversations((prev) => prev.filter((item) => item.id !== id))
      if (String(id) === activeId) navigate('/')
    } catch {
      /* the list refreshes on the next poll anyway */
    }
  }

  return (
    <div className="flex h-full overflow-hidden bg-bg">
      {open && (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-30 bg-black/30 lg:hidden"
        />
      )}

      {open && (
        <aside className="fixed inset-y-0 left-0 z-40 flex w-[280px] shrink-0 flex-col bg-surface lg:static">
          <div className="flex items-center justify-between px-2 pb-2.5 pt-3">
            <Link to="/" className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-soft">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-accent text-[13px] font-semibold text-onaccent">
                R
              </span>
              <span className="text-[15px] font-medium">ReviewCrew</span>
            </Link>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close sidebar"
              className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-soft hover:text-ink"
            >
              <IconPanelLeft className="h-4 w-4" />
            </button>
          </div>

          <div className="px-2">
            <button
              type="button"
              onClick={startNew}
              className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2.5 text-[15px] font-medium hover:bg-soft"
            >
              <span className="grid h-6 w-6 place-items-center rounded-full border border-line">
                <IconPencil className="h-3.5 w-3.5" />
              </span>
              New review
            </button>
          </div>

          <div className="px-2 pt-2">
            <div className="flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2">
              <IconSearch className="h-3.5 w-3.5 shrink-0 text-muted" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search chats"
                className="w-full bg-transparent text-[14px] outline-none placeholder:text-placeholder"
              />
            </div>
          </div>

          <nav className="mt-3 flex-1 overflow-y-auto px-2 pb-3">
            {groups.length === 0 ? (
              <p className="px-2 py-6 text-[14px] leading-relaxed text-muted">
                {query ? 'No chats match that search.' : 'No chats yet. Start one from the composer.'}
              </p>
            ) : (
              groups.map((group) => (
                <div key={group.label} className="mb-3">
                  <p className="px-2 pb-1.5 text-[12px] font-medium text-muted">{group.label}</p>
                  {group.items.map((conversation) => {
                    const active = String(conversation.id) === activeId
                    return (
                      <div
                        key={conversation.id}
                        className={`group flex items-center rounded-lg pr-1 transition ${
                          active ? 'bg-soft' : 'hover:bg-soft'
                        }`}
                      >
                        <Link
                          to={`/?c=${conversation.id}`}
                          title={conversation.preview || conversation.title}
                          className="min-w-0 flex-1 truncate px-2 py-2 text-[14.5px] text-ink/90"
                        >
                          {conversation.title}
                        </Link>
                        <button
                          type="button"
                          onClick={(event) => remove(conversation.id, event)}
                          aria-label={`Delete chat: ${conversation.title}`}
                          title="Delete chat"
                          className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted opacity-0 transition hover:bg-line hover:text-danger focus:opacity-100 group-hover:opacity-100"
                        >
                          <IconTrash className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )
                  })}
                </div>
              ))
            )}
          </nav>

          <div className="border-t border-line/70 p-2">
            <div className="flex items-center justify-between rounded-lg px-1.5 py-1">
              <span
                className="flex items-center gap-1.5 text-[12px] text-muted"
                title={apiState === 'ok' ? 'Connected' : 'API unreachable'}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    apiState === 'ok' ? 'bg-ok' : apiState === 'offline' ? 'bg-danger' : 'bg-muted'
                  }`}
                />
                {apiState === 'ok' ? 'Connected' : apiState === 'offline' ? 'Offline' : '…'}
              </span>
              <button
                type="button"
                onClick={toggle}
                aria-label="Toggle dark mode"
                className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-soft hover:text-ink"
              >
                {theme === 'dark' ? <IconSun className="h-4 w-4" /> : <IconMoon className="h-4 w-4" />}
              </button>
            </div>

            <Link
              to="/settings"
              className={`flex items-center gap-2.5 rounded-lg px-1.5 py-1.5 hover:bg-soft ${
                location.pathname === '/settings' ? 'bg-soft' : ''
              }`}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full border border-line bg-bg text-[11px] font-medium">
                RP
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium">Workspace</span>
                <span className="block truncate text-[12px] text-muted">Settings &amp; keys</span>
              </span>
              <IconSettings className="h-4 w-4 text-muted" />
            </Link>
          </div>
        </aside>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-1 px-2">
          {!open && (
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open sidebar"
              className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-soft hover:text-ink"
            >
              <IconPanelLeft className="h-4 w-4" />
            </button>
          )}
          <Link
            to="/settings"
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[15px] font-medium hover:bg-soft"
          >
            ReviewCrew
            <IconChevronDown className="h-4 w-4 text-muted" />
          </Link>

          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setDemoOpen(true)}
              aria-label="Show website demo"
              title="How to use ReviewCrew"
              className="inline-flex h-10 items-center gap-2.5 rounded-lg px-3.5 text-[15px] font-medium text-muted transition hover:bg-soft hover:text-ink"
            >
              <IconPlay className="h-6 w-6" />
              Demo
            </button>
            <button
              type="button"
              onClick={startNew}
              aria-label="New review"
              className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-soft hover:text-ink lg:hidden"
            >
              <IconPencil className="h-4 w-4" />
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>

      {demoOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="presentation"
          onClick={() => setDemoOpen(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="demo-title"
            className="w-full max-w-2xl rounded-2xl border border-line bg-panel p-6 text-ink shadow-2xl sm:p-8"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[12px] font-medium uppercase tracking-[0.12em] text-muted">
                  Quick tour
                </p>
                <h2 id="demo-title" className="mt-1 text-[26px] font-semibold tracking-tight">
                  How to use ReviewCrew
                </h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">
                  Review a snippet, a pull request, or a small project, then explore the results.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDemoOpen(false)}
                aria-label="Close demo"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted hover:bg-soft hover:text-ink"
              >
                <span aria-hidden="true" className="text-[24px] leading-none">×</span>
              </button>
            </div>

            <ol className="mt-6 space-y-3">
              {[
                {
                  title: 'Choose what to review',
                  description: 'Use the + menu for code, a diff, several project files, or a GitHub pull request.',
                },
                {
                  title: 'Pick a reviewer persona',
                  description: 'Choose Balanced, Security, Performance, or Mentor beside the prompt. Your choice is saved for future reviews.',
                },
                {
                  title: 'Read the review',
                  description: 'Open findings and the diff. Secret exposures get a clear warning, and the metrics summarize complexity and maintainability.',
                },
                {
                  title: 'Keep working',
                  description: 'Generate unit tests from the Tests tab, or ask a follow-up question in the chat.',
                },
              ].map((step, index) => (
                <li key={step.title} className="flex gap-3 rounded-xl border border-line bg-bg p-3.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-soft text-[14px] font-semibold">
                    {index + 1}
                  </span>
                  <div>
                    <h3 className="text-[15px] font-semibold">{step.title}</h3>
                    <p className="mt-1 text-[13.5px] leading-relaxed text-muted">
                      {step.description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>

            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => setDemoOpen(false)}
                className="rounded-full border border-line px-4 py-2 text-[14px] font-medium hover:bg-soft"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => {
                  setDemoOpen(false)
                  startNew()
                }}
                className="rounded-full bg-accent px-4 py-2 text-[14px] font-medium text-onaccent hover:bg-accenth"
              >
                Start a review
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
