import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { authAPI } from '@/services/api/client'
import {
  clearStoredAuthTokens,
  getStoredAccessToken,
  getStoredAuthUser,
  getStoredRefreshToken,
  setStoredAuthTokens,
} from '../utils/authStorage.js'

const STORAGE_KEY = 'stockai-auth'

export const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      loginCooldownUntil: 0,

      signup: async (username, password, email) => {
        set({ isLoading: true, error: null })
        try {
          const response = await authAPI.signup(username, password, email)
          const { access_token, refresh_token, user } = response.data.data

          set({
            user,
            accessToken: access_token,
            refreshToken: refresh_token,
            isAuthenticated: true,
            error: null,
          })
          setStoredAuthTokens({ accessToken: access_token, refreshToken: refresh_token, user })

          return { success: true, user }
        } catch (error) {
          const errorMsg = error.response?.data?.detail || error.message || 'Signup failed'
          set({ error: errorMsg, isAuthenticated: false })
          return { success: false, error: errorMsg }
        } finally {
          set({ isLoading: false })
        }
      },

      login: async (email, password) => {
        const cooldownUntil = get().loginCooldownUntil || 0
        if (cooldownUntil && Date.now() < cooldownUntil) {
          const remainingMs = Math.max(0, cooldownUntil - Date.now())
          const minutes = Math.max(1, Math.ceil(remainingMs / 60000))
          const errorMsg = `Too many login attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`
          set({ error: errorMsg, isAuthenticated: false })
          return { success: false, error: errorMsg }
        }

        set({ isLoading: true, error: null })
        try {
          const response = await authAPI.login(email, password)
          const { access_token, refresh_token, user } = response.data.data

          set({
            user,
            accessToken: access_token,
            refreshToken: refresh_token,
            isAuthenticated: true,
            error: null,
            loginCooldownUntil: 0,
          })

          return { success: true, user }
        } catch (error) {
          const status = error?.response?.status
          if (status === 429) {
            const retryAfter = Number(error?.response?.headers?.['retry-after'])
            const cooldownSeconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 300
            const retryAt = Date.now() + cooldownSeconds * 1000
            const minutes = Math.max(1, Math.ceil(cooldownSeconds / 60))
            const errorMsg = `Too many login attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`
            set({ error: errorMsg, isAuthenticated: false, loginCooldownUntil: retryAt })
            return { success: false, error: errorMsg }
          }

          const errorMsg = error.response?.data?.detail || error.message || 'Login failed'
          set({ error: errorMsg, isAuthenticated: false })
          return { success: false, error: errorMsg }
        } finally {
          set({ isLoading: false })
        }
      },

      logout: async () => {
        try {
          await authAPI.logout()
        } catch (error) {
          console.error('Logout error:', error)
        }
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          error: null,
        })
        clearStoredAuthTokens()
      },

      setTokens: (accessToken, refreshToken) => {
        set({
          accessToken,
          refreshToken,
        })
      },

      getCurrentUser: async () => {
        set({ isLoading: true })
        try {
          const response = await authAPI.getCurrentUser()
          set({ user: response.data.data, isAuthenticated: true })
          return response.data.data
        } catch (error) {
          set({ isAuthenticated: false, user: null })
          return null
        } finally {
          set({ isLoading: false })
        }
      },

      clearError: () => set({ error: null }),

      checkAuth: async () => {
        const token = getStoredAccessToken()
        if (!token) {
          set({ isAuthenticated: false, user: null })
          clearStoredAuthTokens()
          return false
        }

        const user = getStoredAuthUser()
        const refreshToken = getStoredRefreshToken()
        if (user) {
          set({ user, accessToken: token, refreshToken, isAuthenticated: true })
        }

        return true
      },
    }),
    {
      name: STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    }
  )
)

export default useAuthStore
