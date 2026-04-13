import axios from 'axios';
import { handleTokenRefresh } from './authLogic.js';

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

const envApiBase = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL);
const browserOrigin = typeof window !== 'undefined' ? trimTrailingSlash(window.location.origin) : '';

const shouldUseBrowserOrigin =
  Boolean(browserOrigin) &&
  !isLoopbackOrigin(browserOrigin) &&
  (!envApiBase || isLoopbackOrigin(envApiBase));

const rawApiBase = shouldUseBrowserOrigin
  ? browserOrigin
  : (envApiBase || browserOrigin || 'http://localhost:8000');

const resolvedApiBase = rawApiBase.endsWith('/api/v1')
  ? rawApiBase
  : rawApiBase.endsWith('/api')
    ? `${rawApiBase}/v1`
    : `${rawApiBase}/api/v1`;

export const apiClient = axios.create({
  baseURL: resolvedApiBase,
  timeout: 10000,
  headers: { 'Content-Type': 'application/json', 'X-Client-Version': '2.0.0' }
});

let errorCount = 0;
export let circuitBreakerOpen = false;

// 1. Token and UI Key Injection
apiClient.interceptors.request.use((config) => {
  if (circuitBreakerOpen) return Promise.reject(new Error('System offline (Circuit Breaker Open)'));
  const token = localStorage.getItem('access_token');
  const uiApiKey = String(import.meta.env.VITE_PUBLIC_UI_API_KEY || '').trim();
  if (uiApiKey) {
    config.headers['x-api-key'] = uiApiKey;
  } else {
    delete config.headers['x-api-key'];
  }
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
}, (error) => Promise.reject(error));

// 2. Retry Logic & Circuit Breaker Pattern
apiClient.interceptors.response.use((response) => {
  errorCount = 0;
  if (circuitBreakerOpen) circuitBreakerOpen = false;
  return response.data;
}, async (error) => {
  const originalRequest = error.config;
  
  if (error.response && error.response.status >= 500) {
    errorCount++;
    if (errorCount >= 3) {
      circuitBreakerOpen = true;
      window.dispatchEvent(new CustomEvent('api:system_offline'));
    }
  }
  
  if (!error.response) {
    if (!originalRequest._retryCount) originalRequest._retryCount = 0;
    if (originalRequest._retryCount < 3) {
      originalRequest._retryCount += 1;
      await new Promise(r => setTimeout(r, 1000 * originalRequest._retryCount));
      return apiClient(originalRequest);
    }
    return Promise.reject(new Error('Network offline or server unreachable.'));
  }
  
  if (error.response.status === 401 && !originalRequest._retry) {
    return handleTokenRefresh(originalRequest);
  }
  
  const customError = new Error(error.response?.data?.message || 'An unexpected error occurred');
  customError.status = error.response.status;
  customError.code = error.response?.data?.code;
  return Promise.reject(customError);
});