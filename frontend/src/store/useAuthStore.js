import { create } from 'zustand';
import { AuthService } from '../api/services/auth.service.js';

const pickAuthData = (payload) => {
  if (!payload || typeof payload !== 'object') return null;
  if (payload.data && typeof payload.data === 'object') return payload.data;
  return payload;
};

const pickUser = (payload) => {
  if (!payload || typeof payload !== 'object') return null;
  if (payload.user && typeof payload.user === 'object') return payload.user;
  if (payload.data && typeof payload.data === 'object') {
    if (payload.data.user && typeof payload.data.user === 'object') return payload.data.user;
    return payload.data;
  }
  return payload;
};

export const useAuthStore = create((set) => ({
  user: null,
  error: null,
  isAuthenticated: false,
  isLoading: false,

  clearError: () => set({ error: null }),

  login: async (credentials, passwordArg) => {
    const username = typeof credentials === 'object'
      ? credentials?.username || credentials?.email || ''
      : credentials;
    const password = typeof credentials === 'object'
      ? credentials?.password || ''
      : passwordArg;

    const normalizedUsername = String(username || '').trim().toLowerCase();

    if (!normalizedUsername || !password) {
      set({ error: 'Username and password are required', isAuthenticated: false });
      return false;
    }

    set({ isLoading: true });
    try {
      const payload = await AuthService.login(normalizedUsername, password);
      const authData = pickAuthData(payload) || {};

      const accessToken = authData.access_token || authData.accessToken || authData.token;
      const refreshToken = authData.refresh_token || authData.refreshToken || null;
      const user = pickUser(authData);

      if (!accessToken) {
        throw new Error('Invalid login response from server');
      }

      localStorage.setItem('access_token', accessToken);
      if (refreshToken) {
        localStorage.setItem('refresh_token', refreshToken);
      } else {
        localStorage.removeItem('refresh_token');
      }

      set({ user, isAuthenticated: true, isLoading: false, error: null });
      return true;
    } catch (error) {
      const rawMessage = String(error?.message || 'Login failed');
      let message = rawMessage;

      if (/not found/i.test(rawMessage)) {
        message = 'Login API not found. Please check backend URL or restart backend server.';
      } else if (/network|unreachable|refused|failed to fetch|timeout/i.test(rawMessage)) {
        message = 'Cannot connect to authentication service. Please check backend availability and API URL configuration.';
      }

      set({ isLoading: false, isAuthenticated: false, error: message });
      return false;
    }
  },

  logout: async () => {
    try { await AuthService.logout(); } finally {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      set({ user: null, isAuthenticated: false, error: null });
    }
  },

  checkAuth: async () => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      set({ isAuthenticated: false, user: null, error: null });
      return;
    }

    try {
      set({ isLoading: true });
      const payload = await AuthService.me();
      const user = pickUser(payload);
      set({ user, isAuthenticated: true, isLoading: false, error: null });
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      set({ user: null, isAuthenticated: false, isLoading: false, error: null });
    }
  },
}));
