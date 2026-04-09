import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { authAPI } from '@/services/api/client'

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

          return { success: true, user }
        } catch (error) {
          const errorMsg = error.response?.data?.detail || error.message || 'Signup failed'
          set({ error: errorMsg, isAuthenticated: false })
          return { success: false, error: errorMsg }
        } finally {
          set({ isLoading: false })
        }
      },

      login: async (username, password) => {
        set({ isLoading: true, error: null })
        try {
          const response = await authAPI.login(username, password)
          const { access_token, refresh_token, user } = response.data.data

          set({
            user,
            accessToken: access_token,
            refreshToken: refresh_token,
            isAuthenticated: true,
            error: null,
          })

          return { success: true, user }
        } catch (error) {
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
