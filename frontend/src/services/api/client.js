import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// REQUEST INTERCEPTOR - Add Authorization header
apiClient.interceptors.request.use(
  (config) => {
    const authState = useAuthStore.getState()
    if (authState.accessToken) {
      config.headers.Authorization = `Bearer ${authState.accessToken}`
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
  (response) => response,
  async (error) => {
    const originalRequest = error.config

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

      try {
        const refreshResponse = await axios.post(
          `${API_BASE_URL}/api/auth/refresh`,
          { refresh_token: authState.refreshToken },
          { timeout: 30000 }
        )

        const { access_token, refresh_token } = refreshResponse.data.data

        authState.setTokens(access_token, refresh_token)

        originalRequest.headers.Authorization = `Bearer ${access_token}`

        processQueue(null, access_token)

        return apiClient(originalRequest)
      } catch (refreshError) {
        authState.logout()
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
    apiClient.post('/api/auth/signup', { username, password, email }),

  login: (username, password) =>
    apiClient.post('/api/auth/login', { username, password }),

  logout: () =>
    apiClient.post('/api/auth/logout'),

  getCurrentUser: () =>
    apiClient.get('/api/auth/me'),

  refreshToken: (refresh_token) =>
    apiClient.post('/api/auth/refresh', { refresh_token }),
}

// MARKET API
export const marketAPI = {
  getSymbols: (limit = 50) =>
    apiClient.get('/api/market/symbols', { params: { limit } }),
}

// BUNDLE API - single endpoint for dashboard data
export const bundleAPI = {
  getBundle: (symbol, interval = '1m', limit = 100, horizon = '15m') =>
    apiClient.get(`/api/bundle/${symbol}`, {
      params: { interval, limit, horizon },
    }),
}

// TRADING API
export const tradingAPI = {
  getPositions: () =>
    apiClient.get('/api/trading/positions'),

  getOrders: () =>
    apiClient.get('/api/trading/orders'),

  placeOrder: (symbol, quantity, price, side = 'BUY') =>
    apiClient.post('/api/trading/orders', { symbol, quantity, price, side }),

  cancelOrder: (orderId) =>
    apiClient.delete(`/api/trading/orders/${orderId}`),
}

export default apiClient
