const trimTrailingSlash = (value) => String(value || '').replace(/\/+$/, '')

const DEFAULT_API_ORIGIN = 'https://api.stockai-pro.in'
const FALLBACK_API_ORIGIN = 'https://stockai-pro.onrender.com'
const API_ORIGIN_STORAGE_KEY = 'stockai_api_origin'
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

const resolveApiOrigin = () => {
  const storedOrigin = readStoredApiOrigin()
  return storedOrigin || DEFAULT_API_ORIGIN
}

const resolveApiBase = () => {
  return `${resolveApiOrigin()}/api/v1`
}

export const API_BASE = resolveApiBase()
export const API_ORIGIN = resolveApiOrigin()
export const API_ORIGIN_CANDIDATES = [API_ORIGIN, DEFAULT_API_ORIGIN, FALLBACK_API_ORIGIN]
  .map(trimTrailingSlash)
  .filter((value, index, arr) => Boolean(value) && arr.indexOf(value) === index)

const wsFromHttp = (origin) => {
  if (!origin) return ''
  return origin.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:')
}

const RAW_WS_URL = trimTrailingSlash(import.meta.env.VITE_WS_URL || '')
const resolveWsUrl = () => {
  if (RAW_WS_URL) {
    return /(\/ws|\/live)$/i.test(RAW_WS_URL)
      ? RAW_WS_URL.replace(/\/live$/i, '/ws')
      : `${RAW_WS_URL}/ws`
  }

  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws`
  }

  return `${wsFromHttp(API_ORIGIN)}/ws`
}

export const WS_URL = resolveWsUrl()
