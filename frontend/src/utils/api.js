import { API_BASE } from './env'

const DEFAULT_CACHE_TTL_MS = 3000
const responseCache = new Map()

const parseApiError = (data, status, statusText) => {
  if (Array.isArray(data?.detail)) {
    const message = data.detail
      .map((item) => `${item?.loc?.join('.') || 'body'}: ${item?.msg || 'Invalid value'}`)
      .join('; ')
    if (message) return message
  }

  return data?.message || data?.detail || statusText || `Request failed (HTTP ${status})`
}

const toQueryString = (params = {}) => {
  const usp = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    usp.set(key, String(value))
  })
  return usp.toString()
}

export const buildApiUrl = (path, params) => {
  const normalizedPath = String(path || '').startsWith('/') ? path : `/${path}`
  const query = toQueryString(params)
  return query ? `${API_BASE}${normalizedPath}?${query}` : `${API_BASE}${normalizedPath}`
}

export const apiRequest = async (
  path,
  {
    method = 'GET',
    params,
    body,
    headers = {},
    signal,
    timeoutMs = 12000,
  } = {}
) => {
  const url = buildApiUrl(path, params)
  const controller = signal ? null : new AbortController()
  const timeoutId = setTimeout(() => {
    controller?.abort()
  }, timeoutMs)

  try {
    console.log('Calling API:', url)

    const mergedHeaders = {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    }

    const response = await fetch(url, {
      method,
      headers: mergedHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: signal || controller?.signal,
    })

    let payload = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }

    if (!response.ok) {
      const message = parseApiError(payload, response.status, response.statusText)
      const error = new Error(message)
      error.status = response.status
      error.data = payload
      throw error
    }

    return payload
  } catch (error) {
    const isAbortError =
      error?.name === 'AbortError' ||
      /signal aborted without reason/i.test(String(error?.message || '')) ||
      /operation was aborted/i.test(String(error?.message || ''))

    if (isAbortError) {
      console.error('[API] Request aborted:', error?.message || 'Unknown abort reason')
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s. Please check your connection and try again.`)
    }

    if (error instanceof TypeError) {
      console.error('[API] Network error:', error?.message || 'TypeError')
      throw new Error('Network error: Unable to reach StockAI API. Please check your internet connection.')
    }

    // Re-throw with better error message if available
    if (error?.message) {
      throw error
    }
    throw new Error(error?.message || 'Network/API error occurred. Please try again.')
  } finally {
    clearTimeout(timeoutId)
  }
}

export const apiGet = (path, options = {}) => apiRequest(path, { ...options, method: 'GET' })
export const apiPost = (path, body, options = {}) => apiRequest(path, { ...options, method: 'POST', body })

export const apiGetWithRetry = async (
  path,
  { params, signal, retries = 1, retryDelayMs = 500, cacheTtlMs = DEFAULT_CACHE_TTL_MS, bypassCache = false } = {}
) => {
  const url = buildApiUrl(path, params)
  const now = Date.now()

  if (!bypassCache) {
    const cached = responseCache.get(url)
    if (cached && cached.expiresAt > now) {
      return cached.data
    }
  }

  for (let i = 0; i <= retries; i++) {
    try {
      const data = await apiGet(path, { params, signal })
      if (!bypassCache && cacheTtlMs > 0) {
        responseCache.set(url, {
          data,
          expiresAt: Date.now() + cacheTtlMs,
        })
      }
      return data
    } catch (error) {
      if (signal?.aborted || error?.name === 'AbortError') {
        throw error
      }
      if (i === retries) return null
    }

    await new Promise((resolve) => setTimeout(resolve, retryDelayMs * (i + 1)))
  }

  return null
}

export const clearApiCache = () => {
  responseCache.clear()
}
