const trimTrailingSlash = (value) => String(value || '').replace(/\/+$/, '')

const DEFAULT_API_ORIGIN = 'https://api.stockai-pro.in'
const DEFAULT_API_BASE = `${DEFAULT_API_ORIGIN}/api/v1`

const resolveApiBase = () => {
  // Keep API integration stable in production by always targeting the live API base.
  return DEFAULT_API_BASE
}

export const API_BASE = resolveApiBase()
export const API_ORIGIN = DEFAULT_API_ORIGIN

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
