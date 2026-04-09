import { create } from 'zustand';
import axios from 'axios';

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const apiBaseUrl = rawBaseUrl.endsWith('/api') ? rawBaseUrl : `${rawBaseUrl}/api`;

const api = axios.create({
  baseURL: apiBaseUrl
});

export const useAuthStore = create((set) => ({
  isAuthenticated: false,
  error: null,
  login: async (credentials) => {
    const normalizedPayload = (() => {
      if (typeof credentials === 'string') {
        return { username: '', password: credentials };
      }
      if (credentials && typeof credentials === 'object') {
        return credentials;
      }
      return { username: '', password: '' };
    })();

    const username = String(normalizedPayload.username || '').trim();
    const password = String(normalizedPayload.password || '').trim();

    if (!username || !password) {
      set({ error: 'Username and password are required.' });
      return false;
    }

    try {
      const response = await api.post('/v1/auth/login', { username, password });
      const accessToken = response.data?.access_token || response.data?.data?.access_token;
      if (accessToken) {
        set({ isAuthenticated: true, error: null });
        localStorage.setItem('stockai_auth', 'true');
        localStorage.setItem('stockai_token', accessToken);
        localStorage.setItem('stockai_username', username);
        return true;
      }

      set({ error: 'Login failed. Token missing in response.' });
      return false;
    } catch (err) {
      const statusCode = err?.response?.status;
      const backendMessage = err?.response?.data?.message || err?.response?.data?.detail;

      if (statusCode === 422) {
        set({ error: 'Login request is invalid. Enter both username and password.' });
      } else if (statusCode === 401) {
        set({ error: 'Auth Denied. Invalid username or password.' });
      } else {
        set({ error: backendMessage || 'Unable to login right now. Please try again.' });
      }
      return false;
    }
  },
  logout: () => {
    localStorage.removeItem('stockai_auth');
    localStorage.removeItem('stockai_token');
    set({ isAuthenticated: false, error: null });
  },
  checkAuth: () => {
    const isAuth = localStorage.getItem('stockai_auth') === 'true';
    if (isAuth) set({ isAuthenticated: true });
  }
}));
