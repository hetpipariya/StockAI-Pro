import { API_BASE, API_ORIGIN, API_ORIGIN_CANDIDATES } from './env'

const DEFAULT_CACHE_TTL_MS = 3000
const responseCache = new Map()
const FALLBACK_API_ORIGIN = 'https://stockai-pro.onrender.com'
const API_ORIGIN_STORAGE_KEY = 'stockai_api_origin'
const CLOUDFLARE_ORIGIN_FAILURE_CODES = new Set([520, 521, 522, 523, 524, 525, 526])

const trimTrailingSlash = (value) => String(value || '').replace(/\/+$/, '')
const toApiBase = (origin) => `${trimTrailingSlash(origin)}/api/v1`
const extractOriginFromApiBase = (apiBase) => trimTrailingSlash(apiBase).replace(/\/api\/v1$/i, '')

const isHttpOrigin = (value) => /^https?:\/\/[^/]+$/i.test(trimTrailingSlash(value))

const readStoredApiOrigin = () => {
  if (typeof window === 'undefined') return ''
  try {
    const stored = trimTrailingSlash(localStorage.getItem(API_ORIGIN_STORAGE_KEY) || '')
    return isHttpOrigin(stored) ? stored : ''
  } catch (_) {
    return ''
  }
}

const persistHealthyApiOrigin = (origin) => {
  const normalized = trimTrailingSlash(origin)
  if (!isHttpOrigin(normalized) || typeof window === 'undefined') return
  try {
    localStorage.setItem(API_ORIGIN_STORAGE_KEY, normalized)
  } catch (_) {
    // ignore storage failures
  }
}

const getApiBaseCandidates = () => {
  const storedOrigin = readStoredApiOrigin()
  return [
    API_BASE,
    ...API_ORIGIN_CANDIDATES.map(toApiBase),
    toApiBase(storedOrigin),
    toApiBase(API_ORIGIN),
    toApiBase(FALLBACK_API_ORIGIN),
  ].filter((value, index, arr) => Boolean(value) && arr.indexOf(value) === index)
}

const isFailoverSafeMethod = (method) => ['GET', 'HEAD', 'OPTIONS'].includes(String(method || 'GET').toUpperCase())
const isFailoverEligibleError = (error) => {
  const status = Number(error?.status)
  return status === 0 || CLOUDFLARE_ORIGIN_FAILURE_CODES.has(status)
}

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
  const normalizedPath = String(path || '').startsWith('/') ? path : `/${path}`
  const query = toQueryString(params)
  return query ? `${apiBase}${normalizedPath}?${query}` : `${apiBase}${normalizedPath}`
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
  const normalizedMethod = String(method || 'GET').toUpperCase()
  const apiBaseCandidates = isFailoverSafeMethod(normalizedMethod)
    ? getApiBaseCandidates()
    : [getApiBaseCandidates()[0]]

  let lastError = null

  for (let baseIndex = 0; baseIndex < apiBaseCandidates.length; baseIndex += 1) {
    const apiBase = apiBaseCandidates[baseIndex]
    const url = buildApiUrl(path, params, apiBase)
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
        method: normalizedMethod,
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

      persistHealthyApiOrigin(extractOriginFromApiBase(apiBase))
      return payload
    } catch (error) {
      const isAbortError =
        error?.name === 'AbortError' ||
        /signal aborted without reason/i.test(String(error?.message || '')) ||
        /operation was aborted/i.test(String(error?.message || ''))

      let normalizedError = error

      if (isAbortError) {
        console.error('[API] Request aborted:', error?.message || 'Unknown abort reason')
        normalizedError = new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s. Please check your connection and try again.`)
        normalizedError.status = 0
      } else if (error instanceof TypeError) {
        console.error('[API] Network error:', error?.message || 'TypeError')
        normalizedError = new Error('Network error: Unable to reach StockAI API. Please check your internet connection.')
        normalizedError.status = 0
      } else if (!error?.message) {
        normalizedError = new Error('Network/API error occurred. Please try again.')
        normalizedError.status = Number(error?.status) || 0
      }

      lastError = normalizedError

      const hasNextBase = baseIndex < apiBaseCandidates.length - 1
      if (hasNextBase && isFailoverEligibleError(normalizedError)) {
        const nextApiBase = apiBaseCandidates[baseIndex + 1]
        console.warn(`[API] Failing over request ${path} from ${apiBase} to ${nextApiBase}`)
        continue
      }

      throw normalizedError
    } finally {
      clearTimeout(timeoutId)
    }
  }

  throw lastError || new Error('Network/API error occurred. Please try again.')
}

export const apiGet = (path, options = {}) => apiRequest(path, { ...options, method: 'GET' })
export const apiPost = (path, body, options = {}) => apiRequest(path, { ...options, method: 'POST', body })

export const apiGetWithRetry = async (
  path,
  { params, signal, retries = 1, retryDelayMs = 500, cacheTtlMs = DEFAULT_CACHE_TTL_MS, bypassCache = false } = {}
) => {
  const cacheKey = `${String(path || '')}?${toQueryString(params)}`
  const now = Date.now()

  if (!bypassCache) {
    const cached = responseCache.get(cacheKey)
    if (cached && cached.expiresAt > now) {
      return cached.data
    }
  }

  for (let i = 0; i <= retries; i++) {
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
