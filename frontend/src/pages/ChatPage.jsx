import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { streamChat } from '../lib/chat.js'
import Composer from '../components/Composer.jsx'
import Message, { RichText } from '../components/Message.jsx'
import ReviewResult from '../components/ReviewResult.jsx'

let counter = 0
const uid = () => `m${++counter}`

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const SAMPLE_CODE = `import sqlite3

API_KEY = "sk-live-9f8e7d6c5b4a3210"

def get_user(user_id):
    # build the query from the request parameter
    query = "SELECT * FROM users WHERE id = " + user_id
    return sqlite3.connect("app.db").execute(query)

def total(items):
    return sum(items) + discount`

const SUGGESTIONS = [
  { mode: 'code', label: 'Paste a file' },
  { mode: 'diff', label: 'Paste a diff' },
  { mode: 'files', label: 'Paste a project' },
  { mode: 'pr', label: 'Review a pull request' },
]

const SAMPLE_PROJECT = `=== app/models.py ===
class User:
    def __init__(self, email):
        self.email = email

def load_user(user_id):
    return User(user_id)

=== app/routes.py ===
from app.models import load_user

def get_user(user_id):
    user = load_user()
    return user.email
`

/** Split "=== path ===" sections into files. */
function parseFileBundle(text) {
  const parts = text.split(/^===\s*(.+?)\s*===\s*$/gm)
  const files = []
  for (let index = 1; index < parts.length; index += 2) {
    const path = (parts[index] || '').trim()
    const code = (parts[index + 1] || '').replace(/^\n/, '')
    if (path && code.trim()) files.push({ path, code })
  }
  return files
}

function notifySidebar() {
  window.dispatchEvent(new Event('reviewpilot:refresh'))
}

/** Stored messages reference a review by id; rehydrate the card data. */
async function hydrateMessages(stored) {
  return Promise.all(
    stored.map(async (message, index) => {
      const base = {
        id: `s${index}-${message.created_at || index}`,
        role: message.role,
        kind: message.kind,
        content: message.content || '',
        review_id: message.review_id ?? null,
      }
      if (message.kind === 'review' && message.review_id) {
        try {
          const review = await api.review(message.review_id)
          return { ...base, review, findings: review.findings || [] }
        } catch {
          return { ...base, kind: 'error', content: 'That review is no longer available.' }
        }
      }
      return base
    }),
  )
}

export default function ChatPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [messages, setMessages] = useState([])
  const [mode, setMode] = useState('ask')
  const [busy, setBusy] = useState(false)
  const [context, setContext] = useState(null)
  const [composerKey, setComposerKey] = useState(0)
  const [draft, setDraft] = useState({ text: '', filePath: '' })
  const [conversationId, setConversationId] = useState(null)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [reviewerPersona, setReviewerPersona] = useState('balanced')
  const [personaSaving, setPersonaSaving] = useState(false)
  const [personaNotice, setPersonaNotice] = useState('')

  const endRef = useRef(null)
  const prefilled = useRef(false)
  const messagesRef = useRef(messages)

  useEffect(() => {
    let alive = true
    api.settings().then((data) => {
      if (alive) setReviewerPersona(data.reviewer_persona || 'balanced')
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  async function changeReviewerPersona(nextPersona) {
    const previous = reviewerPersona
    setReviewerPersona(nextPersona)
    setPersonaSaving(true)
    setPersonaNotice('')
    try {
      const data = await api.updateSettings({ reviewer_persona: nextPersona })
      setReviewerPersona(data.reviewer_persona || nextPersona)
    } catch {
      setReviewerPersona(previous)
      setPersonaNotice('Could not save reviewer persona.')
    } finally {
      setPersonaSaving(false)
    }
  }

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const scrollToEnd = useCallback(() => {
    window.requestAnimationFrame(() => {
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    })
  }, [])

  useEffect(scrollToEnd, [messages, scrollToEnd])

  // "New review" in the sidebar starts a fresh chat.
  useEffect(() => {
    if (!location.state?.newChat) return
    setMessages([])
    setContext(null)
    setBusy(false)
    setMode('ask')
    setDraft({ text: '', filePath: '' })
    setConversationId(null)
    setComposerKey((key) => key + 1)
    window.history.replaceState(null, '', '/')
  }, [location.state])

  // Load a saved conversation from ?c=<id>.
  useEffect(() => {
    const id = searchParams.get('c')
    if (!id) {
      setConversationId(null)
      if (!searchParams.get('review')) setMessages([])
      return undefined
    }

    let alive = true
    setLoadingConversation(true)
    api
      .conversation(id)
      .then(async (conversation) => {
        const hydrated = await hydrateMessages(conversation.messages || [])
        if (!alive) return
        setConversationId(conversation.id)
        setMessages(hydrated)
        setLoadingConversation(false)
      })
      .catch(() => {
        if (!alive) return
        setConversationId(null)
        setMessages([])
        setLoadingConversation(false)
      })

    return () => {
      alive = false
    }
  }, [searchParams])

  // ?review=<id> loads a review as chat context (from "Ask about this").
  useEffect(() => {
    const id = searchParams.get('review')
    if (!id || searchParams.get('c')) return
    api
      .review(id)
      .then((review) => {
        setContext({
          reviewId: review.id,
          label:
            review.pr_number > 0 ? `${review.repo_name} #${review.pr_number}` : review.pr_title,
        })
        if (!prefilled.current) {
          prefilled.current = true
          setMessages([
            {
              id: uid(),
              role: 'assistant',
              kind: 'text',
              content:
                `I have this review loaded as context: **${review.pr_title}** ` +
                `(${review.findings_count} findings).\n\n` +
                'Ask me why a finding matters, how to fix it, or to write the patch.',
            },
          ])
        }
      })
      .catch(() => {
        /* stale id - ignore */
      })
  }, [searchParams])

  function appendDelta(id, delta) {
    setMessages((prev) =>
      prev.map((message) =>
        message.id === id ? { ...message, content: message.content + delta } : message,
      ),
    )
  }

  function patchMessage(id, patch) {
    setMessages((prev) =>
      prev.map((message) => (message.id === id ? { ...message, ...patch } : message)),
    )
  }

  /** Create the conversation row on the first message, then pin it in the URL. */
  async function ensureConversation() {
    if (conversationId) return conversationId
    const conversation = await api.createConversation()
    setConversationId(conversation.id)
    window.history.replaceState(null, '', `/?c=${conversation.id}`)
    return conversation.id
  }

  /** Save a message; a failed save must not break the UI. */
  async function persist(cid, message) {
    if (!cid) return
    try {
      await api.appendMessage(cid, message)
      notifySidebar()
    } catch {
      /* keep the local copy */
    }
  }

  /**
   * The review this conversation is "about": the explicitly attached one, or
   * the most recent review card. That is what gives follow-ups their memory -
   * "now optimise this for memory" needs the code from the earlier review.
   */
  function latestReviewId() {
    for (let index = messagesRef.current.length - 1; index >= 0; index -= 1) {
      const message = messagesRef.current[index]
      const id = message.review_id ?? message.review?.id
      if (message.kind === 'review' && id) return id
    }
    return null
  }

  async function handleSubmit({ mode: submitMode, text, filePath, error }) {
    if (error) {
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: 'assistant', kind: 'error', content: error },
      ])
      return
    }
    if (submitMode === 'ask') await ask(text)
    else await review({ mode: submitMode, text, filePath })
  }

  async function ask(text) {
    const history = messagesRef.current
      .filter((message) => message.kind === 'text' || message.kind === 'error')
      .map((message) => ({ role: message.role, content: message.content }))
      .slice(-10)

    const assistantId = uid()
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: 'user', kind: 'text', content: text },
      { id: assistantId, role: 'assistant', kind: 'text', content: '', streaming: true },
    ])
    setBusy(true)

    let cid = conversationId
    try {
      cid = await ensureConversation()
      await persist(cid, { role: 'user', kind: 'text', content: text })

      let full = ''
      await streamChat({
        messages: [...history, { role: 'user', content: text }],
        reviewId: context?.reviewId || latestReviewId(),
        onDelta: (delta) => {
          full += delta
          appendDelta(assistantId, delta)
        },
      })

      const finalText = full.trim()
        ? full
        : 'The model returned an empty response. Check the model name in Settings, then try again.'

      patchMessage(assistantId, { content: finalText, streaming: false })
      await persist(cid, { role: 'assistant', kind: 'text', content: finalText })
    } catch (err) {
      const content = `**${err.message}**\n\nOpen Settings to add an OpenRouter key and pick a model.`
      patchMessage(assistantId, { kind: 'error', streaming: false, content })
      await persist(cid, { role: 'assistant', kind: 'error', content })
    } finally {
      setBusy(false)
    }
  }

  async function review({ mode: reviewMode, text, filePath }) {
    const pendingId = uid()

    // Multi-file mode: split on "=== path ===" headers.
    const bundle = reviewMode === 'files' ? parseFileBundle(text) : []
    if (reviewMode === 'files' && bundle.length === 0) {
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: 'assistant',
          kind: 'error',
          content:
            'I could not find any files. Start each file with a header line like `=== app/models.py ===`.',
        },
      ])
      return
    }

    const label =
      reviewMode === 'code'
        ? filePath || 'pasted file'
        : reviewMode === 'diff'
          ? 'pasted diff'
          : reviewMode === 'files'
            ? `${bundle.length} files`
            : text

    const userText =
      reviewMode === 'code'
        ? `Review \`${label}\` for bugs, security issues and style.`
        : reviewMode === 'diff'
          ? 'Review this diff.'
          : reviewMode === 'files'
            ? `Review these ${bundle.length} files together (${bundle.map((f) => f.path).join(', ')}).`
            : `Review ${text}`

    setMessages((prev) => [
      ...prev,
      { id: uid(), role: 'user', kind: 'text', content: userText },
      {
        id: pendingId,
        role: 'assistant',
        kind: 'review',
        pending: true,
        review: { status: 'queued', repo_name: 'starting', pr_number: 0 },
        findings: [],
      },
    ])
    setBusy(true)
    scrollToEnd()

    let cid = conversationId
    try {
      cid = await ensureConversation()
      await persist(cid, { role: 'user', kind: 'text', content: userText })

      const payload =
        reviewMode === 'code'
          ? {
              source: 'code',
              code: text,
              file_path: filePath,
              title: filePath ? `Pasted file: ${filePath}` : 'Pasted file',
            }
          : reviewMode === 'diff'
            ? { source: 'diff', diff: text, file_path: filePath }
            : reviewMode === 'files'
              ? { source: 'files', files: bundle, title: `${bundle.length} pasted files` }
              : { source: 'pr', pr_url: text }

      let reviewData = await api.createReview(payload)
      patchMessage(pendingId, { review: reviewData, pending: reviewData.status === 'queued' })
      notifySidebar()

      for (let attempt = 0; attempt < 80; attempt += 1) {
        if (reviewData.status === 'completed' || reviewData.status === 'failed') break
        await sleep(1500)
        reviewData = await api.review(reviewData.id)
        patchMessage(pendingId, { review: reviewData })
      }

      const detail = await api.review(reviewData.id)
      patchMessage(pendingId, {
        pending: false,
        review: detail,
        findings: detail.findings || [],
      })
      await persist(cid, { role: 'assistant', kind: 'review', review_id: detail.id })
      notifySidebar()
    } catch (err) {
      patchMessage(pendingId, {
        pending: false,
        kind: 'error',
        review: { status: 'failed' },
        content: err.message,
      })
      await persist(cid, { role: 'assistant', kind: 'error', content: err.message })
    } finally {
      setBusy(false)
    }
  }

  function useSuggestion(suggestion) {
    setMode(suggestion.mode)
    setDraft({ text: '', filePath: '' })
    setComposerKey((key) => key + 1)
  }

  function fillSample() {
    setMode('code')
    setDraft({ text: SAMPLE_CODE, filePath: 'app/db.py' })
    setComposerKey((key) => key + 1)
  }

  function fillProjectSample() {
    setMode('files')
    setDraft({ text: SAMPLE_PROJECT, filePath: '' })
    setComposerKey((key) => key + 1)
  }

  const empty = messages.length === 0 && !loadingConversation

  return (
    <div className="flex h-full flex-col">
      {loadingConversation ? (
        <div className="mx-auto w-full max-w-4xl space-y-5 px-5 py-8">
          <div className="h-5 w-1/3 animate-pulse rounded bg-soft" />
          <div className="h-16 animate-pulse rounded-2xl bg-soft" />
          <div className="h-5 w-1/4 animate-pulse rounded bg-soft" />
          <div className="h-10 animate-pulse rounded bg-soft" />
        </div>
      ) : empty ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col justify-center px-5 py-8">
            <h1 className="text-center text-[36px] font-normal tracking-tight text-ink sm:text-[40px]">
              What should we review?
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-center text-[16px] leading-relaxed text-muted">
              Paste a file, a diff, or a pull request link. Static analysis and a model review it,
              and you can ask follow-up questions right here.
            </p>

            <div className="mx-auto mt-10 w-full">
              <Composer
                key={`empty-${composerKey}`}
                mode={mode}
                onModeChange={setMode}
                onSubmit={handleSubmit}
                busy={busy}
                context={context}
                onClearContext={() => setContext(null)}
                initialText={draft.text}
                initialFilePath={draft.filePath}
                reviewerPersona={reviewerPersona}
                onReviewerPersonaChange={changeReviewerPersona}
                personaSaving={personaSaving}
                personaNotice={personaNotice}
              />
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion.mode}
                  type="button"
                  onClick={() => useSuggestion(suggestion)}
                  className="rounded-full border border-line px-4 py-2 text-[14px] text-ink transition hover:bg-soft"
                >
                  {suggestion.label}
                </button>
              ))}
              <button
                type="button"
                onClick={fillSample}
                className="rounded-full px-4 py-2 text-[14px] text-muted underline underline-offset-2 transition hover:text-ink"
              >
                Load a broken sample
              </button>
              <button
                type="button"
                onClick={fillProjectSample}
                className="rounded-full px-4 py-2 text-[14px] text-muted underline underline-offset-2 transition hover:text-ink"
              >
                Load a 2-file project
              </button>
            </div>

            <p className="mt-7 text-center text-[12.5px] text-muted">
              ReviewCrew can make mistakes. Verify findings before applying them.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-4xl space-y-7 px-5 py-7">
              {messages.map((message) => (
                <Message key={message.id} role={message.role} streaming={message.streaming}>
                  {message.kind === 'review' ? (
                    <ReviewResult
                      review={message.review}
                      findings={message.findings}
                      pending={message.pending}
                    />
                  ) : (
                    <RichText text={message.content} />
                  )}
                </Message>
              ))}
              <div ref={endRef} />
            </div>
          </div>

          <div className="shrink-0 px-5 pb-3">
            <div className="mx-auto w-full max-w-4xl">
              <Composer
                key={composerKey}
                mode={mode}
                onModeChange={setMode}
                onSubmit={handleSubmit}
                busy={busy}
                context={context}
                onClearContext={() => setContext(null)}
                initialText={draft.text}
                initialFilePath={draft.filePath}
                reviewerPersona={reviewerPersona}
                onReviewerPersonaChange={changeReviewerPersona}
                personaSaving={personaSaving}
                personaNotice={personaNotice}
              />
              <p className="mt-2.5 pb-1 text-center text-[12.5px] text-muted">
                ReviewCrew can make mistakes. Verify findings before applying them.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
