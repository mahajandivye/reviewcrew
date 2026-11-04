import { Fragment, useState } from 'react'

/** Inline `code` and **bold** - deliberately tiny, no markdown dependency. */
function renderInline(text) {
  const parts = text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code
          key={index}
          className="rounded bg-soft px-1.5 py-0.5 font-mono text-[13px] text-ink"
        >
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={index} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <Fragment key={index}>{part}</Fragment>
  })
}

function CodeBlock({ lang, value }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard?.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="codeblock my-3">
      <div className="codeblock-head flex items-center justify-between px-4 py-1.5">
        <span className="text-[12px] text-[#cfcfcf]">{lang || 'code'}</span>
        <button
          type="button"
          onClick={copy}
          className="text-[11.5px] text-[#cfcfcf] transition hover:text-white"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 font-mono text-[13px] leading-6">{value}</pre>
    </div>
  )
}

function TextBlock({ text }) {
  const lines = text.split('\n')
  const nodes = []
  let bullets = []

  const flushBullets = () => {
    if (!bullets.length) return
    nodes.push(
      <ul key={`ul-${nodes.length}`} className="my-2 list-disc space-y-1 pl-6">
        {bullets.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ul>,
    )
    bullets = []
  }

  lines.forEach((line, index) => {
    if (/^\s*[-*]\s+/.test(line)) {
      bullets.push(line.replace(/^\s*[-*]\s+/, ''))
      return
    }
    flushBullets()

    if (!line.trim()) {
      nodes.push(<div key={`gap-${index}`} className="h-2" />)
    } else if (/^#{1,3}\s+/.test(line)) {
      nodes.push(
        <h3 key={index} className="mt-4 mb-1 text-[16px] font-semibold text-ink">
          {line.replace(/^#{1,3}\s+/, '')}
        </h3>,
      )
    } else {
      nodes.push(
        <p key={index} className="whitespace-pre-wrap">
          {renderInline(line)}
        </p>,
      )
    }
  })
  flushBullets()
  return nodes
}

/** Markdown-lite renderer: paragraphs, bullets, headings, fenced code. */
export function RichText({ text = '' }) {
  const blocks = []
  const fence = /```([a-zA-Z0-9+#-]*)\n?([\s\S]*?)```/g
  let cursor = 0
  let match

  while ((match = fence.exec(text)) !== null) {
    if (match.index > cursor) {
      blocks.push({ type: 'text', value: text.slice(cursor, match.index) })
    }
    blocks.push({ type: 'code', lang: match[1], value: match[2].replace(/\n$/, '') })
    cursor = fence.lastIndex
  }
  if (cursor < text.length) blocks.push({ type: 'text', value: text.slice(cursor) })

  return (
    <>
      {blocks.map((block, index) =>
        block.type === 'code' ? (
          <CodeBlock key={index} lang={block.lang} value={block.value} />
        ) : (
          <TextBlock key={index} text={block.value} />
        ),
      )}
    </>
  )
}

/**
 * ChatGPT-style message layout: user text right-aligned in a grey bubble,
 * assistant text plain and full width.
 */
export default function Message({ role, streaming = false, children }) {
  if (role === 'user') {
    return (
      <div className="rise flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-[22px] bg-bubble px-4 py-2.5 text-[15px] leading-7 text-ink">
          {children}
        </div>
      </div>
    )
  }

  return (
    <div className={`rise text-[15.5px] leading-7 text-ink ${streaming ? 'caret' : ''}`}>
      {children}
    </div>
  )
}
