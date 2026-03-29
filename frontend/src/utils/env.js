const trimTrailingSlash = (value) => String(value || '').replace(/\/+$/, '')
const isAbsoluteHttpUrl = (value) => /^https?:\/\//i.test(String(value || ''))

const RAW_API_URL = trimTrailingSlash(import.meta.env.VITE_API_URL || '')
const DEFAULT_API_ORIGIN = 'https://api.stockai-pro.in'
const DEV_API_BASE = '/api/v1'

const resolveApiBase = () => {
  if (RAW_API_URL) {
    if (isAbsoluteHttpUrl(RAW_API_URL)) {
      return `${RAW_API_URL}/api/v1`
    }

    const normalized = RAW_API_URL.startsWith('/') ? RAW_API_URL : `/${RAW_API_URL}`
    return normalized.endsWith('/api/v1') ? normalized : `${normalized}/api/v1`
  }

  if (import.meta.env.DEV) {
    return DEV_API_BASE
  }

  return `${DEFAULT_API_ORIGIN}/api/v1`
}

export const API_BASE = resolveApiBase()
export const API_ORIGIN = isAbsoluteHttpUrl(RAW_API_URL)
  ? RAW_API_URL
  : DEFAULT_API_ORIGIN

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
