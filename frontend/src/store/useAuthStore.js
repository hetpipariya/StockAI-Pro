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
  login: async (password) => {
    try {
      const response = await api.post('/v1/auth/login', { password: password.trim() });
      const accessToken = response.data?.access_token || response.data?.data?.access_token;
      if (accessToken) {
        set({ isAuthenticated: true, error: null });
        localStorage.setItem('stockai_auth', 'true');
        localStorage.setItem('stockai_token', accessToken);
        return true;
      }
      return false;
    } catch (err) {
      set({ error: 'Auth Denied. Invalid Master Password.' });
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
