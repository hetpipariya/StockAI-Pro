import axios from 'axios';
import { handleTokenRefresh } from './authLogic.js';
import { getStoredAccessToken } from '../utils/authStorage.js';
import {
  API_TIMEOUT_MS,
  beginSingleFlightRequest,
  isAbortLikeError,
  normalizeTimeoutMs,
} from './requestGate.js';

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
  timeout: API_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json', 'X-Client-Version': '2.0.0' }
});

let errorCount = 0;
export let circuitBreakerOpen = false;

const stableSerialize = (value) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return JSON.stringify(value ?? null);
  }

  const ordered = Object.keys(value)
    .sort()
    .reduce((acc, key) => {
      acc[key] = value[key];
      return acc;
    }, {});

  return JSON.stringify(ordered);
};

const buildSingleFlightKey = (config = {}) => {
  const method = String(config.method || 'GET').toUpperCase();
  const url = String(config.url || '');
  const params = stableSerialize(config.params || null);
  return `${method}:${url}:${params}`;
};

// 1. Token and UI Key Injection
apiClient.interceptors.request.use((config) => {
  if (circuitBreakerOpen) return Promise.reject(new Error('System offline (Circuit Breaker Open)'));

  const gate = beginSingleFlightRequest({
    externalSignal: config.signal,
    key: buildSingleFlightKey(config),
  });
  const timeoutMs = normalizeTimeoutMs(config.timeout, API_TIMEOUT_MS);
  config.signal = gate.signal;
  config.timeout = timeoutMs;
  config.__requestTimeoutMs = timeoutMs;
  config.__requestGateRelease = gate.release;

  const token = getStoredAccessToken();
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
  response?.config?.__requestGateRelease?.();
  errorCount = 0;
  if (circuitBreakerOpen) circuitBreakerOpen = false;
  return response.data;
}, async (error) => {
  const originalRequest = error.config;
  originalRequest?.__requestGateRelease?.();
  
  if (error.response && error.response.status >= 500) {
    errorCount++;
    if (errorCount >= 3) {
      circuitBreakerOpen = true;
      window.dispatchEvent(new CustomEvent('api:system_offline'));
    }
  }

  if (isAbortLikeError(error)) {
    const timeoutMs = Number(originalRequest?.__requestTimeoutMs || API_TIMEOUT_MS);
    const abortReason = String(originalRequest?.signal?.reason || '');

    if (abortReason === 'request_timeout') {
      const timeoutError = new Error(`Request timed out after ${timeoutMs}ms. Fail-fast triggered.`);
      timeoutError.name = 'TimeoutError';
      timeoutError.code = 'ERR_TIMEOUT';
      timeoutError.status = 0;
      timeoutError.isTimeout = true;
      return Promise.reject(timeoutError);
    }

    const cancelError = new Error('Request canceled by a newer request.');
    cancelError.name = 'AbortError';
    cancelError.code = 'ERR_CANCELED';
    cancelError.status = 0;
    cancelError.isTimeout = false;
    return Promise.reject(cancelError);
  }
  
  if (!error.response) {
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