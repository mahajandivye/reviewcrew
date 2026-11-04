import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { ErrorBanner, Spinner } from '../components/Feedback.jsx'
import { IconCheck, IconEye, IconEyeOff, IconTrash } from '../components/icons.jsx'

const REVIEW_MODELS = [
  'openai/gpt-4o-mini',
  'openai/gpt-4o',
  'anthropic/claude-3.5-sonnet',
  'google/gemini-2.0-flash-001',
]
const CHAT_MODELS = [
  'openai/gpt-4o-mini',
  'openai/gpt-4o',
  'anthropic/claude-3.5-sonnet',
  'google/gemini-2.0-flash-001',
  'meta-llama/llama-3.3-70b-instruct',
]

const inputClass =
  'w-full rounded-md border border-line bg-bg px-2.5 py-2 text-[13px] text-ink outline-none transition placeholder:text-muted/50 focus:border-accent/60'

function Field({ label, hint, children }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-[11px] text-muted">
          {label}
        </span>
        {hint && <span className="font-mono text-[9.5px] text-muted/70">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

function Secret({ id, value, onChange, placeholder, configured, masked, onClear, disabled }) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="space-y-1.5">
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          className={`${inputClass} pr-9 font-mono text-[12px]`}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide value' : 'Show value'}
          className="absolute inset-y-0 right-0 grid w-9 place-items-center text-muted hover:text-ink"
        >
          {visible ? <IconEyeOff className="h-3.5 w-3.5" /> : <IconEye className="h-3.5 w-3.5" />}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.08em]">
        {configured ? (
          <>
            <span className="inline-flex items-center gap-1 text-ok">
              <IconCheck className="h-3 w-3" /> configured
            </span>
            <span className="normal-case tracking-normal text-muted">{masked}</span>
            {onClear && (
              <button
                type="button"
                onClick={onClear}
                className="text-muted underline-offset-2 hover:text-danger hover:underline"
              >
                clear
              </button>
            )}
          </>
        ) : (
          <span className="text-muted/70">not configured</span>
        )}
      </div>
    </div>
  )
}

function Section({ title, note, children }) {
  return (
    <section className="grid gap-4 border-t border-line py-6 sm:grid-cols-[190px_minmax(0,1fr)] sm:gap-8">
      <div>
        <h2 className="text-[16px] font-semibold tracking-tight text-ink">{title}</h2>
        {note && <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">{note}</p>}
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  )
}

export default function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const [rules, setRules] = useState([])
  const [rulesSaving, setRulesSaving] = useState(false)
  const [rulesMessage, setRulesMessage] = useState('')
  const rulesFileRef = useRef(null)

  const [githubToken, setGithubToken] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [openrouterKey, setOpenrouterKey] = useState('')
  // The key normally comes from the server; the input is only revealed if
  // someone deliberately wants to replace it.
  const [editingOpenrouter, setEditingOpenrouter] = useState(false)
  const [editingOpenai, setEditingOpenai] = useState(false)
  const [model, setModel] = useState('gpt-4o-mini')
  const [reviewerPersona, setReviewerPersona] = useState('balanced')
  const [chatModel, setChatModel] = useState('openai/gpt-4o-mini')
  const [postComments, setPostComments] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [data, ruleList] = await Promise.all([
        api.settings(),
        api.rules().catch(() => []),
      ])
      setSettings(data)
      setRules(ruleList || [])
      setModel(data.openai_model || 'gpt-4o-mini')
      setReviewerPersona(data.reviewer_persona || 'balanced')
      setChatModel(data.chat_model || 'openai/gpt-4o-mini')
      setPostComments(Boolean(data.post_pr_comments))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function addRule() {
    setRules((prev) => [
      ...prev,
      {
        name: '',
        pattern: '',
        message: '',
        severity: 'medium',
        category: 'style',
        enabled: true,
      },
    ])
  }

  function updateRule(index, patch) {
    setRules((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  function removeRule(index) {
    setRules((prev) => prev.filter((_, i) => i !== index))
  }

  async function saveRulesList() {
    setRulesSaving(true)
    setRulesMessage('')
    try {
      const savedRules = await api.saveRules(rules)
      setRules(savedRules)
      setRulesMessage('Rules saved. They run on the next review.')
    } catch (err) {
      setRulesMessage(err.message)
    } finally {
      setRulesSaving(false)
    }
  }

  function exportRules() {
    const blob = new Blob([JSON.stringify({ name: 'ReviewCrew rules', version: 1, rules }, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'reviewcrew-rules.json'
    anchor.click()
    URL.revokeObjectURL(url)
    setRulesMessage('Rule set exported.')
  }

  async function importRules(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const payload = JSON.parse(await file.text())
      const imported = Array.isArray(payload) ? payload : payload.rules
      if (!Array.isArray(imported) || imported.length > 50) {
        throw new Error('Choose a rule-set JSON file containing up to 50 rules.')
      }
      setRules(imported)
      setRulesMessage(`${imported.length} rule(s) loaded. Click Save rules to apply them.`)
    } catch (err) {
      setRulesMessage(err.message || 'Could not read that rule-set file.')
    }
  }

  async function patch(body, message) {
    setSaving(true)
    setError('')
    setSaved('')
    try {
      const data = await api.updateSettings(body)
      setSettings(data)
      setModel(data.openai_model || model)
      setReviewerPersona(data.reviewer_persona || reviewerPersona)
      setChatModel(data.chat_model || chatModel)
      setPostComments(Boolean(data.post_pr_comments))
      setSaved(message)
      window.setTimeout(() => setSaved(''), 4000)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function save(event) {
    event.preventDefault()
    const body = {}
    if (githubToken.trim()) body.github_token = githubToken.trim()
    if (openaiKey.trim()) body.openai_api_key = openaiKey.trim()
    if (openrouterKey.trim()) body.openrouter_api_key = openrouterKey.trim()
    if (model && model !== settings?.openai_model) body.openai_model = model
    if (reviewerPersona !== (settings?.reviewer_persona || 'balanced')) {
      body.reviewer_persona = reviewerPersona
    }
    if (chatModel.trim() && chatModel !== settings?.chat_model) body.chat_model = chatModel.trim()
    if (postComments !== settings?.post_pr_comments) body.post_pr_comments = postComments

    if (!Object.keys(body).length) {
      setSaved('Nothing changed.')
      window.setTimeout(() => setSaved(''), 2500)
      return
    }
    await patch(body, 'Saved. New reviews and chats use these values.')
    setGithubToken('')
    setOpenaiKey('')
    setOpenrouterKey('')
    setEditingOpenrouter(false)
    setEditingOpenai(false)
  }

  if (loading && !settings) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-5 py-10">
        <div className="h-8 w-40 animate-pulse rounded bg-panel2" />
        <div className="h-40 animate-pulse rounded-lg bg-panel2" />
        <div className="h-40 animate-pulse rounded-lg bg-panel2" />
      </div>
    )
  }

  return (
    <form onSubmit={save} className="mx-auto w-full max-w-4xl px-5 py-8">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">Workspace</p>
      <h1 className="mt-2 text-[28px] font-semibold tracking-tight text-ink">Settings</h1>
      <p className="mt-1.5 max-w-xl text-[13px] leading-relaxed text-muted">
        Keys saved here are stored server-side and override <code className="font-mono text-[12px]">.env</code>.
        They are never returned in full — only a masked preview.
      </p>

      {error && <div className="mt-4"><ErrorBanner message={error} onRetry={load} /></div>}
      {saved && (
        <div className="mt-4 flex items-center gap-2 border-l-2 border-l-ok pl-3 py-1 text-[11.5px] text-ok">
          <IconCheck className="h-3.5 w-3.5" />
          {saved}
        </div>
      )}

      <div className="mt-6">
        <Section
          title="GitHub"
          note="Reads pull requests and posts review comments. Needs Contents: read and Pull requests: write."
        >
          <Field label="Personal access token" hint="fine-grained or classic">
            <Secret
              id="github"
              value={githubToken}
              onChange={setGithubToken}
              placeholder={settings?.github_token_configured ? 'Leave blank to keep current' : 'ghp_… or github_pat_…'}
              configured={settings?.github_token_configured}
              masked={settings?.github_token}
              onClear={() => patch({ github_token: '' }, 'GitHub token cleared.')}
              disabled={saving}
            />
          </Field>
          <p className="text-[11px] leading-relaxed text-muted">
            Optional for public pull requests. Required for private repositories, posting comments,
            and webhooks. Pasting code or a diff never needs it.
          </p>
        </Section>

        <Section
          title="Review engine"
          note="Reads the pasted code or diff and writes the findings. Runs through OpenRouter too, so the same key covers reviews and chat."
        >
          <Field label="API key" hint="server-side">
            {settings?.openai_api_key_configured && !editingOpenai ? (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg px-2.5 py-2">
                <IconCheck className="h-3.5 w-3.5 text-ok" />
                <span className="text-[12.5px] text-ink">Using the server key</span>
                <code className="font-mono text-[11px] text-muted">
                  {settings.openai_api_key}
                </code>
                <button
                  type="button"
                  onClick={() => setEditingOpenai(true)}
                  className="ml-auto text-[11.5px] text-muted underline underline-offset-2 hover:text-ink"
                >
                  Replace
                </button>
              </div>
            ) : (
              <Secret
                id="openai"
                value={openaiKey}
                onChange={setOpenaiKey}
                placeholder="sk-or-v1-…"
                configured={false}
                masked=""
                disabled={saving}
              />
            )}
          </Field>
          <Field label="Review model">
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={saving}
              className={inputClass}
            >
              {(REVIEW_MODELS.includes(model) ? REVIEW_MODELS : [model, ...REVIEW_MODELS]).map(
                (option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ),
              )}
            </select>
          </Field>
          <Field label="Reviewer persona">
            <select
              value={reviewerPersona}
              onChange={(event) => setReviewerPersona(event.target.value)}
              disabled={saving}
              className={inputClass}
            >
              <option value="balanced">Balanced senior engineer</option>
              <option value="security">Security specialist</option>
              <option value="performance">Performance specialist</option>
              <option value="mentor">Supportive mentor</option>
            </select>
          </Field>
          <p className="text-[11px] leading-relaxed text-muted">
            Persona guides the review’s emphasis. Security and correctness checks remain active for every persona.
          </p>
          <p className="text-[11px] leading-relaxed text-muted">
            Model ids follow OpenRouter (<code className="font-mono text-[11px]">vendor/model</code>).
            Without a key, reviews still run pyflakes and the secret scanner.
          </p>
        </Section>

        <Section
          title="Assistant"
          note="Powers the chat bar. Routed through OpenRouter, so any supported model works."
        >
          <Field label="OpenRouter API key" hint="server-side">
            {settings?.openrouter_api_key_configured && !editingOpenrouter ? (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg px-2.5 py-2">
                <IconCheck className="h-3.5 w-3.5 text-ok" />
                <span className="text-[12.5px] text-ink">Key is configured on the server</span>
                <code className="font-mono text-[11px] text-muted">
                  {settings.openrouter_api_key}
                </code>
                <button
                  type="button"
                  onClick={() => setEditingOpenrouter(true)}
                  className="ml-auto text-[11.5px] text-muted underline underline-offset-2 hover:text-ink"
                >
                  Replace
                </button>
              </div>
            ) : (
              <Secret
                id="openrouter"
                value={openrouterKey}
                onChange={setOpenrouterKey}
                placeholder="sk-or-v1-…"
                configured={false}
                masked=""
                disabled={saving}
              />
            )}
          </Field>
          <Field label="Chat model" hint="OpenRouter model id">
            <>
              <input
                value={chatModel}
                onChange={(event) => setChatModel(event.target.value)}
                list="chat-models"
                spellCheck={false}
                disabled={saving}
                className={`${inputClass} font-mono text-[12px]`}
              />
              <datalist id="chat-models">
                {CHAT_MODELS.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            </>
          </Field>
          <p className="text-[11px] leading-relaxed text-muted">
            The key is supplied by the server (<code className="font-mono text-[11px]">OPENROUTER_API_KEY</code>
            ), so visitors never have to enter one. The chat bar streams responses and can see the
            review you have open.
          </p>
        </Section>

        <Section title="Behaviour" note="How the worker reports findings on real pull requests.">
          <label className="flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={postComments}
              onChange={(event) => setPostComments(event.target.checked)}
              disabled={saving}
              className="mt-0.5 h-3.5 w-3.5 rounded border-line accent-[var(--accent)]"
            />
            <span>
              <span className="block text-[13px] text-ink">Comment on the pull request</span>
              <span className="mt-0.5 block text-[11.5px] leading-relaxed text-muted">
                Off: findings stay in this workspace. On: inline comments are posted with the
                review.
              </span>
            </span>
          </label>
        </Section>

        <Section
          title="Custom rules"
          note="Your own regex checks. They run on added lines next to pyflakes and the secret scanner, and appear in the review with a 'custom rule' tag."
        >
          {rules.length === 0 && (
            <p className="text-[11.5px] leading-relaxed text-muted">
              No rules yet. Example: block <code className="font-mono">print(</code> in production
              code, or require <code className="font-mono">strict: true</code> in tsconfig.
            </p>
          )}

          {rules.map((rule, index) => (
            <div key={index} className="space-y-2 rounded-lg border border-line p-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={(event) => updateRule(index, { enabled: event.target.checked })}
                  className="h-3.5 w-3.5 rounded border-line accent-[var(--accent)]"
                  aria-label="Rule enabled"
                />
                <input
                  value={rule.name}
                  onChange={(event) => updateRule(index, { name: event.target.value })}
                  placeholder="Rule name"
                  className={`${inputClass} !w-auto min-w-[9rem] flex-1`}
                />
                <select
                  value={rule.severity}
                  onChange={(event) => updateRule(index, { severity: event.target.value })}
                  className={`${inputClass} !w-auto`}
                  aria-label="Severity"
                >
                  <option value="high">high</option>
                  <option value="medium">medium</option>
                  <option value="low">low</option>
                </select>
                <select
                  value={rule.category}
                  onChange={(event) => updateRule(index, { category: event.target.value })}
                  className={`${inputClass} !w-auto`}
                  aria-label="Category"
                >
                  <option value="bug">bug</option>
                  <option value="security">security</option>
                  <option value="style">style</option>
                </select>
                <button
                  type="button"
                  onClick={() => removeRule(index)}
                  className="grid h-8 w-8 place-items-center rounded-md text-muted transition hover:bg-soft hover:text-danger"
                  aria-label={`Delete rule ${rule.name || index + 1}`}
                >
                  <IconTrash className="h-3.5 w-3.5" />
                </button>
              </div>
              <input
                value={rule.pattern}
                onChange={(event) => updateRule(index, { pattern: event.target.value })}
                placeholder="regex, e.g. \\bprint\\("
                spellCheck={false}
                className={`${inputClass} font-mono text-[12px]`}
              />
              <input
                value={rule.message}
                onChange={(event) => updateRule(index, { message: event.target.value })}
                placeholder="Message shown on the finding"
                className={inputClass}
              />
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-2">
            <input ref={rulesFileRef} type="file" accept="application/json,.json" onChange={importRules} className="hidden" />
            <button
              type="button"
              onClick={addRule}
              className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink transition hover:bg-soft"
            >
              + Add rule
            </button>
            <button type="button" onClick={() => rulesFileRef.current?.click()} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink transition hover:bg-soft">
              Import rules
            </button>
            <button type="button" onClick={exportRules} disabled={!rules.length} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink transition hover:bg-soft disabled:opacity-50">
              Export rules
            </button>
            <button
              type="button"
              onClick={saveRulesList}
              disabled={rulesSaving}
              className="inline-flex items-center gap-2 rounded-md bg-accent px-2.5 py-1.5 text-[12px] font-medium text-onaccent transition hover:bg-accenth disabled:opacity-60"
            >
              {rulesSaving && <Spinner className="h-3 w-3" />}
              Save rules
            </button>
            {rulesMessage && (
              <span className="text-[11.5px] text-muted">{rulesMessage}</span>
            )}
          </div>
        </Section>

        <Section title="Webhook" note="How GitHub reaches the review pipeline.">
          <div className="flex items-center justify-between gap-4 border-b border-line py-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">endpoint</span>
            <code className="font-mono text-[11.5px] text-ink">POST /webhook/github</code>
          </div>
          <div className="flex items-center justify-between gap-4 border-b border-line py-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">signature</span>
            <span className="font-mono text-[11px] text-ink">HMAC-SHA256 · raw body</span>
          </div>
          <p className="font-mono text-[10px] leading-relaxed text-muted/80">
            Secret lives in <code>GITHUB_WEBHOOK_SECRET</code>. Local test:{' '}
            <code>python scripts/send_test_webhook.py</code>
          </p>
        </Section>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-line pt-5">
        <button
          type="button"
          onClick={load}
          disabled={saving}
          className="rounded-md border border-line px-3 py-1.5 text-[12.5px] text-ink transition hover:border-accent/50 disabled:opacity-60"
        >
          Reset
        </button>
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-onaccent transition hover:bg-accenth disabled:opacity-60"
        >
          {saving && <Spinner className="h-3.5 w-3.5" />}
          Save changes
        </button>
      </div>
    </form>
  )
}
