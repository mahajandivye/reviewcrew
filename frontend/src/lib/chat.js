/**
 * Streaming client for POST /api/chat.
 *
 * The backend forwards OpenRouter's SSE stream, one JSON object per event:
 *   {"delta": "text"}  |  {"error": "..."}  |  [DONE]
 *
 * We read the response body incrementally so the UI can paint tokens as they
 * arrive, which is what makes the composer feel alive rather than frozen.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

export async function streamChat({ messages, reviewId, model, onDelta, signal }) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, review_id: reviewId ?? null, model: model || null }),
    signal,
  })

  if (!response.ok) {
    let detail = `Request failed (HTTP ${response.status})`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') detail = payload.detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }

  if (!response.body) {
    throw new Error('This browser cannot stream responses.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const event of events) {
      const line = event.trim()
      if (!line.startsWith('data:')) continue
      const data = line.slice(5).trim()
      if (data === '[DONE]') return
      if (!data) continue

      let parsed
      try {
        parsed = JSON.parse(data)
      } catch {
        continue
      }
      if (parsed.error) throw new Error(parsed.error)
      if (parsed.delta) onDelta(parsed.delta)
    }
  }
}
