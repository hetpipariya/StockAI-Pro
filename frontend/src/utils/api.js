import { API_URL, buildApiUrl as buildAbsoluteApiUrl } from '../config/api'
import {
  API_TIMEOUT_MS,
  MAX_API_RETRIES,
  beginSingleFlightRequest,
  isAbortLikeError,
  normalizeTimeoutMs,
} from '../api/requestGate.js'

const DEFAULT_CACHE_TTL_MS = 3000
const responseCache = new Map()
const API_BASE = API_URL

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

export const buildApiUrl = (path, params, apiBase = API_BASE) => {
  const resolvedBaseUrl = apiBase === API_BASE
    ? buildAbsoluteApiUrl(path)
    : `${apiBase}${String(path || '').startsWith('/') ? path : `/${path}`}`
  const query = toQueryString(params)
  return query ? `${resolvedBaseUrl}?${query}` : resolvedBaseUrl
}

export const apiRequest = async (
  path,
  {
    method = 'GET',
    params,
    body,
    headers = {},
    signal,
    timeoutMs = API_TIMEOUT_MS,
  } = {}
) => {
  const normalizedMethod = String(method || 'GET').toUpperCase()
  const url = buildApiUrl(path, params)
  const gate = beginSingleFlightRequest({
    externalSignal: signal,
    key: `${normalizedMethod}:${url}`,
  })
  const effectiveTimeoutMs = normalizeTimeoutMs(timeoutMs, API_TIMEOUT_MS)
  const timeoutId = setTimeout(() => {
    gate.abort('request_timeout')
  }, effectiveTimeoutMs)

  try {
    console.log('Calling API:', url)

    const mergedHeaders = {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    }

    const response = await fetch(url, {
      method: normalizedMethod,
      headers: mergedHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: gate.signal,
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
    const isAbortError = isAbortLikeError(error)

    if (isAbortError) {
      const abortReason = String(gate.signal?.reason || '')
      console.error('[API] Request aborted:', abortReason || error?.message || 'Unknown abort reason')

      if (abortReason === 'request_timeout') {
        const timeoutError = new Error(`Request timed out after ${effectiveTimeoutMs}ms. Fail-fast triggered.`)
        timeoutError.name = 'TimeoutError'
        timeoutError.code = 'ERR_TIMEOUT'
        timeoutError.status = 0
        timeoutError.isTimeout = true
        throw timeoutError
      }

      const cancelError = new Error('Request canceled by a newer request.')
      cancelError.name = 'AbortError'
      cancelError.code = 'ERR_CANCELED'
      cancelError.status = 0
      cancelError.isTimeout = false
      throw cancelError
    }

    if (error instanceof TypeError) {
      console.error('[API] Network error:', error?.message || 'TypeError')
      const networkError = new Error('Network error: Unable to reach StockAI API. Please check your internet connection.')
      networkError.status = 0
      throw networkError
    }

    if (!error?.message) {
      const unknownError = new Error('Network/API error occurred. Please try again.')
      unknownError.status = Number(error?.status) || 0
      throw unknownError
    }

    throw error
  } finally {
    clearTimeout(timeoutId)
    gate.release()
  }
}

export const apiGet = (path, options = {}) => apiRequest(path, { ...options, method: 'GET' })
export const apiPost = (path, body, options = {}) => apiRequest(path, { ...options, method: 'POST', body })

export const apiGetWithRetry = async (
  path,
  { params, signal, retries = 0, retryDelayMs = 100, cacheTtlMs = DEFAULT_CACHE_TTL_MS, bypassCache = false } = {}
) => {
  const maxRetries = Math.max(0, Math.min(Number(retries) || 0, MAX_API_RETRIES))
  const cacheKey = `${String(path || '')}?${toQueryString(params)}`
  const now = Date.now()

  if (!bypassCache) {
    const cached = responseCache.get(cacheKey)
    if (cached && cached.expiresAt > now) {
      return cached.data
    }
  }

  for (let i = 0; i <= maxRetries; i++) {
    try {
      const data = await apiGet(path, { params, signal })
      if (!bypassCache && cacheTtlMs > 0) {
        responseCache.set(cacheKey, {
          data,
          expiresAt: Date.now() + cacheTtlMs,
        })
      }
      return data
    } catch (error) {
      if (signal?.aborted || isAbortLikeError(error)) {
        throw error
      }
      if (i === maxRetries) return null
    }

    await new Promise((resolve) => setTimeout(resolve, retryDelayMs * (i + 1)))
  }

  return null
}

export const clearApiCache = () => {
  responseCache.clear()
}
