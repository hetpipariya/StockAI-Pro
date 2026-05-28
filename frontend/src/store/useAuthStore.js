import { create } from 'zustand';
import { AuthService } from '../api/services/auth.service.js';
import {
  clearStoredAuthTokens,
  getStoredAccessToken,
  getStoredAuthUser,
  getStoredRefreshToken,
  setStoredAuthTokens,
} from '../utils/authStorage.js';

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

export const useAuthStore = create((set, get) => ({
  user: null,
  error: null,
  isAuthenticated: false,
  isLoading: false,
  loginCooldownUntil: 0,

  clearError: () => set({ error: null }),

  login: async (credentials, passwordArg) => {
    const email = typeof credentials === 'object'
      ? credentials?.email || credentials?.username || ''
      : credentials;
    const password = typeof credentials === 'object'
      ? credentials?.password || ''
      : passwordArg;

    const normalizedEmail = String(email || '').trim().toLowerCase();

    const cooldownUntil = get().loginCooldownUntil || 0;
    if (cooldownUntil && Date.now() < cooldownUntil) {
      const remainingMs = Math.max(0, cooldownUntil - Date.now());
      const remainingSeconds = Math.max(1, Math.ceil(remainingMs / 1000));
      const minutes = Math.ceil(remainingSeconds / 60);
      set({
        error: `Too many login attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`,
        isAuthenticated: false,
      });
      return false;
    }

    if (!normalizedEmail || !password) {
      set({ error: 'Email and password are required', isAuthenticated: false });
      return false;
    }

    set({ isLoading: true });
    try {
      const payload = await AuthService.login(normalizedEmail, password);
      const authData = pickAuthData(payload) || {};

      const accessToken = authData.access_token || authData.accessToken || authData.token;
      const refreshToken = authData.refresh_token || authData.refreshToken || null;
      const user = pickUser(authData);

      if (!accessToken) {
        throw new Error('Invalid login response from server');
      }

      setStoredAuthTokens({ accessToken, refreshToken, user });

      set({ user, isAuthenticated: true, isLoading: false, error: null, loginCooldownUntil: 0 });
      return true;
    } catch (error) {
      const status = error?.status ?? error?.response?.status;
      if (status === 429) {
        const retryAfter = Number(error?.response?.headers?.['retry-after']);
        const cooldownSeconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 300;
        const retryAt = Date.now() + cooldownSeconds * 1000;
        const minutes = Math.max(1, Math.ceil(cooldownSeconds / 60));
        set({
          isLoading: false,
          isAuthenticated: false,
          loginCooldownUntil: retryAt,
          error: `Too many login attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`,
        });
        return false;
      }

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
      clearStoredAuthTokens();
      set({ user: null, isAuthenticated: false, error: null });
    }
  },

  signup: async ({ email, password }) => {
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail || !password || password.length < 8) {
      const msg = 'Valid email and password (at least 8 characters) are required';
      set({ error: msg, isAuthenticated: false });
      throw new Error(msg);
    }

    set({ isLoading: true, error: null });
    try {
      const payload = await AuthService.register(normalizedEmail, password);
      const authData = pickAuthData(payload) || {};

      const accessToken = authData.access_token || authData.accessToken || authData.token;
      const refreshToken = authData.refresh_token || authData.refreshToken || null;
      let user = pickUser(authData);

      if (!accessToken) {
        const loginPayload = await AuthService.login(normalizedEmail, password);
        const loginData = pickAuthData(loginPayload) || {};
        const lt = loginData.access_token || loginData.accessToken;
        if (!lt) {
          throw new Error('Invalid signup response from server');
        }
        user = pickUser(loginData) || user;
        setStoredAuthTokens({
          accessToken: lt,
          refreshToken: loginData.refresh_token || loginData.refreshToken || refreshToken,
          user,
        });
        set({ user, isAuthenticated: true, isLoading: false, error: null });
        return user;
      }

      setStoredAuthTokens({ accessToken, refreshToken, user });
      set({ user, isAuthenticated: true, isLoading: false, error: null });
      return user;
    } catch (error) {
      const rawMessage =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        'Signup failed';
      const message = typeof rawMessage === 'string' ? rawMessage : JSON.stringify(rawMessage);
      set({ isLoading: false, isAuthenticated: false, error: message });
      throw new Error(message);
    }
  },

  checkAuth: async () => {
    const token = getStoredAccessToken();
    const storedUser = getStoredAuthUser();
    const storedRefreshToken = getStoredRefreshToken();
    if (!token) {
      set({ isAuthenticated: false, user: null, error: null });
      return;
    }

    if (storedUser) {
      set({ user: storedUser, isAuthenticated: true, error: null });
    }

    try {
      set({ isLoading: true });
      const payload = await AuthService.me();
      const user = pickUser(payload);
      setStoredAuthTokens({ accessToken: token, refreshToken: storedRefreshToken, user });
      set({ user, isAuthenticated: true, isLoading: false, error: null });
    } catch {
      clearStoredAuthTokens();
      set({ user: null, isAuthenticated: false, isLoading: false, error: null });
    }
  },
}));
