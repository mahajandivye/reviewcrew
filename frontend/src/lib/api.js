/**
 * Thin API client around the FastAPI backend.
 *
 * In development every call goes to `/api/...` on the Vite dev server, which
 * proxies it to http://127.0.0.1:8000 (see vite.config.js). That means the
 * browser never makes a cross-origin request, so CORS cannot bite during a
 * demo. For a production build, set VITE_API_BASE_URL to the deployed API.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function messageFromPayload(payload, status) {
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors are a list of {loc, msg, type}
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join(', ')
  }
  return `Request failed (HTTP ${status})`
}

async function request(path, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(
      'Cannot reach the API. Is the backend running on http://127.0.0.1:8000?',
      0,
    )
  }

  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    throw new ApiError(messageFromPayload(payload, response.status), response.status, payload)
  }
  return payload
}

export const api = {
  health: () => request('/health'),

  stats: () => request('/api/stats'),

  reviews: ({ page = 1, pageSize = 20, status = '', repo = '' } = {}) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (status) params.set('status', status)
    if (repo) params.set('repo', repo)
    return request(`/api/reviews?${params.toString()}`)
  },

  review: (id) => request(`/api/reviews/${id}`),

  reviewDiff: (id) => request(`/api/reviews/${id}/diff`),

  /**
   * Create a review from the app instead of waiting for a webhook.
   *   { source: 'code', code, file_path, title }
   *   { source: 'diff', diff, file_path, title }
   *   { source: 'pr',   pr_url }
   */
  createReview: (payload) => request('/api/reviews', { method: 'POST', body: payload }),

  retryReview: (id) => request(`/api/reviews/${id}/retry`, { method: 'POST' }),
  reviewMetrics: (id) => request(`/api/reviews/${id}/metrics`),
  generateTests: (id) => request(`/api/reviews/${id}/tests`, { method: 'POST' }),

  // --- custom rules -------------------------------------------------------
  rules: () => request('/api/rules'),
  saveRules: (rules) => request('/api/rules', { method: 'PUT', body: { rules } }),

  // --- saved conversations ------------------------------------------------
  conversations: (limit = 50) => request(`/api/conversations?limit=${limit}`),
  conversation: (id) => request(`/api/conversations/${id}`),
  createConversation: (title) =>
    request('/api/conversations', { method: 'POST', body: { title: title ?? null } }),
  renameConversation: (id, title) =>
    request(`/api/conversations/${id}`, { method: 'PATCH', body: { title } }),
  deleteConversation: (id) => request(`/api/conversations/${id}`, { method: 'DELETE' }),
  appendMessage: (id, message) =>
    request(`/api/conversations/${id}/messages`, { method: 'POST', body: message }),

  settings: () => request('/api/settings'),

  updateSettings: (patch) => request('/api/settings', { method: 'PATCH', body: patch }),
}
