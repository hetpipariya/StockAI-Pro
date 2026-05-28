import axios from 'axios';
import { apiClient } from './client.js';
import { API_TIMEOUT_MS } from './requestGate.js';
import {
  clearStoredAuthTokens,
  getStoredRefreshToken,
  setStoredAuthTokens,
} from '../utils/authStorage.js';

let isRefreshing = false; let failedQueue = [];
const processQueue = (error, token = null) => {
  failedQueue.forEach(p => error ? p.reject(error) : p.resolve(token)); failedQueue = [];
};

const trimTrailingSlash = (value) => String(value || '').trim().replace(/\/$/, '');

const isLoopbackOrigin = (value) => {
  const normalized = trimTrailingSlash(value);
  if (!normalized) return false;

  try {
    const hostname = new URL(normalized).hostname;
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0';
  } catch {
    return false;
  }
};

const resolveApiBaseV1 = () => {
  const envApiBase = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL);
  const browserOrigin = typeof window !== 'undefined' ? trimTrailingSlash(window.location.origin) : '';

  const shouldUseBrowserOrigin =
    Boolean(browserOrigin) &&
    !isLoopbackOrigin(browserOrigin) &&
    (!envApiBase || isLoopbackOrigin(envApiBase));

  const rawBaseUrl = shouldUseBrowserOrigin
    ? browserOrigin
    : (envApiBase || browserOrigin || 'http://localhost:8000');

  if (rawBaseUrl.endsWith('/api/v1')) return rawBaseUrl;
  if (rawBaseUrl.endsWith('/api')) return `${rawBaseUrl}/v1`;
  return `${rawBaseUrl}/api/v1`;
};

export const handleTokenRefresh = async (originalRequest) => {
  originalRequest._retry = true;
  if (isRefreshing) {
    return new Promise((resolve, reject) => failedQueue.push({ resolve, reject }))
      .then(token => { originalRequest.headers['Authorization'] = 'Bearer ' + token; return apiClient(originalRequest); })
      .catch(err => Promise.reject(err));
  }
  isRefreshing = true;
  try {
    const refreshToken = getStoredRefreshToken();
    if (!refreshToken) throw new Error('No refresh token available');

    const baseUrl = resolveApiBaseV1();
    const response = await axios.post(`${baseUrl}/auth/refresh`, {
      refresh_token: refreshToken,
    }, {
      timeout: API_TIMEOUT_MS,
    });

    const payload = response?.data?.data || response?.data || {};
    const accessToken = payload.access_token || payload.accessToken || payload.token;
    const nextRefreshToken = payload.refresh_token || payload.refreshToken || refreshToken;

    if (!accessToken) {
      throw new Error('Token refresh failed');
    }

    setStoredAuthTokens({ accessToken, refreshToken: nextRefreshToken });

    processQueue(null, accessToken);
    originalRequest.headers['Authorization'] = 'Bearer ' + accessToken;
    return apiClient(originalRequest);
  } catch (err) {
    processQueue(err, null);
    clearStoredAuthTokens();
    window.location.href = '/login';
    return Promise.reject(err);
  } finally { isRefreshing = false; }
};