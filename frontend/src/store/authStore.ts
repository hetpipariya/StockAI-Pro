import { create } from 'zustand';
import { User, Settings, AuthResponse } from './types';

interface AuthStoreState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isLoading: boolean;
  error: string | null;
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string | null, user: User) => void;
  logout: () => void;
  setUser: (user: User) => void;
  setError: (error: string | null) => void;
  setLoading: (loading: boolean) => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  user: null,
  accessToken: null,
  refreshToken: null,
  isLoading: false,
  error: null,
  isAuthenticated: false,

  login: (accessToken, refreshToken, user) => {
    localStorage.setItem('auth_access_token', accessToken);
    if (refreshToken) {
      localStorage.setItem('auth_refresh_token', refreshToken);
    }
    localStorage.setItem('auth_user', JSON.stringify(user));
    set({
      user,
      accessToken,
      refreshToken,
      isAuthenticated: true,
      error: null,
      isLoading: false,
    });
  },

  logout: () => {
    localStorage.removeItem('auth_access_token');
    localStorage.removeItem('auth_refresh_token');
    localStorage.removeItem('auth_user');
    set({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      error: null,
    });
  },

  setUser: (user) => set({ user }),

  setError: (error) => set({ error }),

  setLoading: (loading) => set({ isLoading: loading }),

  clearError: () => set({ error: null }),
}));
