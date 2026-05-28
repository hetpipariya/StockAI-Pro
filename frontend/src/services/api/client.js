import axios from 'axios'
import { useAuthStore } from '@/store/authStore'
import {
  clearStoredAuthTokens,
  getStoredAccessToken,
  getStoredRefreshToken,
  setStoredAuthTokens,
} from '../../utils/authStorage.js'
import {
  API_TIMEOUT_MS,
  beginSingleFlightRequest,
  isAbortLikeError,
  normalizeTimeoutMs,
} from '../../api/requestGate.js'

const rawApiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')
const API_BASE_URL = rawApiBase.endsWith('/api/v1')
  ? rawApiBase
  : rawApiBase.endsWith('/api')
    ? `${rawApiBase}/v1`
    : `${rawApiBase}/api/v1`

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
})

const stableSerialize = (value) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return JSON.stringify(value ?? null)
  }

  const ordered = Object.keys(value)
    .sort()
    .reduce((acc, key) => {
      acc[key] = value[key]
      return acc
    }, {})

  return JSON.stringify(ordered)
}

const buildSingleFlightKey = (config = {}) => {
  const method = String(config.method || 'GET').toUpperCase()
  const url = String(config.url || '')
  const params = stableSerialize(config.params || null)
  return `${method}:${url}:${params}`
}

// REQUEST INTERCEPTOR - Add Authorization header
apiClient.interceptors.request.use(
  (config) => {
    const gate = beginSingleFlightRequest({
      externalSignal: config.signal,
      key: buildSingleFlightKey(config),
    })
    const timeoutMs = normalizeTimeoutMs(config.timeout, API_TIMEOUT_MS)
    config.signal = gate.signal
    config.timeout = timeoutMs
    config.__requestTimeoutMs = timeoutMs
    config.__requestGateRelease = gate.release

    const authState = useAuthStore.getState()
    const token = authState.accessToken || getStoredAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// RESPONSE INTERCEPTOR - Handle 401 & token refresh
let isRefreshing = false
let failedQueue = []

const processQueue = (error, token = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  
  isRefreshing = false
  failedQueue = []
}

apiClient.interceptors.response.use(
  (response) => {
    response?.config?.__requestGateRelease?.()
    return response
  },
  async (error) => {
    const originalRequest = error.config
    originalRequest?.__requestGateRelease?.()

    if (isAbortLikeError(error)) {
      const timeoutMs = Number(originalRequest?.__requestTimeoutMs || API_TIMEOUT_MS)
      const abortReason = String(originalRequest?.signal?.reason || '')

      if (abortReason === 'request_timeout') {
        const timeoutError = new Error(`Request timed out after ${timeoutMs}ms. Fail-fast triggered.`)
        timeoutError.name = 'TimeoutError'
        timeoutError.code = 'ERR_TIMEOUT'
        timeoutError.status = 0
        timeoutError.isTimeout = true
        return Promise.reject(timeoutError)
      }

      const cancelError = new Error('Request canceled by a newer request.')
      cancelError.name = 'AbortError'
      cancelError.code = 'ERR_CANCELED'
      cancelError.status = 0
      cancelError.isTimeout = false
      return Promise.reject(cancelError)
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then(token => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            return apiClient(originalRequest)
          })
          .catch(err => Promise.reject(err))
      }

      isRefreshing = true
      const authState = useAuthStore.getState()
      const refreshToken = authState.refreshToken || getStoredRefreshToken()

      try {
        const refreshResponse = await axios.post(
          `${API_BASE_URL}/auth/refresh`,
          { refresh_token: refreshToken },
          { timeout: API_TIMEOUT_MS }
        )

        const { access_token, refresh_token } = refreshResponse.data.data

        authState.setTokens(access_token, refresh_token)
  setStoredAuthTokens({ accessToken: access_token, refreshToken: refresh_token })

        originalRequest.headers.Authorization = `Bearer ${access_token}`

        processQueue(null, access_token)

        return apiClient(originalRequest)
      } catch (refreshError) {
        authState.logout()
        clearStoredAuthTokens()
        processQueue(refreshError, null)
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

// AUTH API
export const authAPI = {
  signup: (username, password, email) =>
    apiClient.post('/auth/register', { username, password, email }),

  login: (email, password) =>
    apiClient.post('/auth/login', { email, password }),

  logout: () =>
    apiClient.post('/auth/logout'),

  getCurrentUser: () =>
    apiClient.get('/auth/me'),

  refreshToken: (refresh_token) =>
    apiClient.post('/auth/refresh', { refresh_token }),
}

// MARKET API
export const marketAPI = {
  getSymbols: (limit = 50) =>
    apiClient.get('/market/symbols', { params: { limit } }),
}

// BUNDLE API - single endpoint for dashboard data
export const bundleAPI = {
  getBundle: (symbol, interval = '1m', limit = 100, horizon = '15m') =>
    apiClient.get(`/bundle/${symbol}`, {
      params: { interval, limit, horizon },
    }),
}

// TRADING API
export const tradingAPI = {
  getPositions: () =>
    apiClient.get('/trading/positions'),

  getOrders: () =>
    apiClient.get('/trading/orders'),

  placeOrder: (symbol, quantity, price, side = 'BUY') =>
    apiClient.post('/trading/orders', { symbol, quantity, price, side }),

  cancelOrder: (orderId) =>
    apiClient.delete(`/trading/orders/${orderId}`),
}

export default apiClient
