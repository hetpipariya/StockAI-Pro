/**
 * @file api.js
 * Centralized API module for StockAI-Pro.
 */
import {
  API_BASE as CONFIG_API_BASE,
  buildApiUrl as buildAbsoluteApiUrl,
  buildLiveWebSocketUrl,
} from '../config/api';
import {
  API_TIMEOUT_MS,
  API_TIMEOUT_MAX_MS,
  MAX_API_RETRIES,
  beginSingleFlightRequest,
  isAbortLikeError as isAbortLikeRequestGateError,
  normalizeTimeoutMs,
} from './requestGate.js';

const ACCESS_TOKEN_KEY = 'stockai_access_token';
const REFRESH_TOKEN_KEY = 'stockai_refresh_token';
const USER_KEY = 'stockai_user';
const DEFAULT_TIMEOUT_MS = API_TIMEOUT_MS;
const AUTH_TIMEOUT_MS = API_TIMEOUT_MS;
const AUTH_LOGIN_ENDPOINT = '/auth/login';
const API_BASE = CONFIG_API_BASE;

const normalizeEndpoint = (endpoint) => {
  const raw = String(endpoint || '');
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return path
    .replace(/^\/api\/v1\/?/i, '/')
    .replace(/^\/api\/?/i, '/');
};

const buildApiUrl = (endpoint) => {
  return buildAbsoluteApiUrl(normalizeEndpoint(endpoint));
};

const logApiFailure = ({ endpoint, method, url, status, message, error }) => {
  const details = {
    endpoint,
    method,
    requestUrl: url,
    status,
    message,
    timestamp: new Date().toISOString(),
  };

  if (typeof window !== 'undefined') {
    window.__stockaiLastApiError = details;
  }

  console.error('[apiFetch] request failed', { ...details, error });
};

const unwrapData = (payload) => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return payload.data;
  }
  return payload;
};

const toFiniteNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const buildIndicatorsFromRows = (rows = []) => {
  if (!Array.isArray(rows) || rows.length === 0) return {};
  const last = rows[rows.length - 1] || {};
  return Object.entries(last).reduce((acc, [key, value]) => {
    if (key === 'time' || key === 'timestamp') return acc;
    const num = toFiniteNumber(value, null);
    if (num != null) acc[key] = num;
    return acc;
  }, {});
};

const isBundleEndpoint = (endpoint) => /^\/bundle\//.test(String(endpoint || ''));

const normalizePredictionPayload = (rawPayload, symbolHint = '') => {
  const payload = unwrapData(rawPayload);
  if (!payload || typeof payload !== 'object') return null;

  const normalizedSymbol = String(payload.symbol || symbolHint || '').trim().toUpperCase();
  const rawSignal = String(payload.signal || 'HOLD').trim().toUpperCase();
  const signal = ['BUY', 'SELL', 'HOLD'].includes(rawSignal) ? rawSignal : 'HOLD';

  const confidenceRaw = toFiniteNumber(payload.confidence, 0);
  const confidence = confidenceRaw <= 1 ? confidenceRaw * 100 : confidenceRaw;
  const currentPrice = toFiniteNumber(
    payload.currentPrice ?? payload.current_price ?? payload.prediction ?? payload.price ?? payload.ltp,
    0
  );
  const target = toFiniteNumber(payload.target ?? payload.target_price, currentPrice);
  const stopLoss = toFiniteNumber(payload.stopLoss ?? payload.stop_loss, currentPrice);

  return {
    symbol: normalizedSymbol,
    signal,
    confidence: Math.max(0, Math.min(100, confidence)),
    currentPrice,
    target,
    stopLoss,
    regime: payload.regime || 'Unknown',
    explanation: payload.explanation || 'Live model signal',
    timestamp: payload.timestamp || new Date().toISOString(),
    modelVersion: toFiniteNumber(payload.model_version, 0),
  };
};

const normalizeHistoryRows = (historyPayload) => {
  const resolved = unwrapData(historyPayload);
  const rows = Array.isArray(resolved?.data)
    ? resolved.data
    : Array.isArray(resolved)
      ? resolved
      : [];

  return rows
    .map((row) => ({
      time: row?.time || row?.timestamp || row?.datetime || null,
      open: toFiniteNumber(row?.open, null),
      high: toFiniteNumber(row?.high, null),
      low: toFiniteNumber(row?.low, null),
      close: toFiniteNumber(row?.close, null),
      volume: toFiniteNumber(row?.volume, 0),
    }))
    .filter((row) => row.time && row.open != null && row.high != null && row.low != null && row.close != null);
};

const extractErrorMessage = (payload, fallback) => {
  if (!payload || typeof payload !== 'object') return fallback;
  return (
    payload.error ||
    payload.message ||
    payload.detail ||
    fallback
  );
};

const isGatewayTimeoutLike = (status) => {
  const code = Number(status || 0);
  return code === 502 || code === 503 || code === 504 || (code >= 520 && code <= 526);
};

export const getStoredAccessToken = () => {
  try {
    return localStorage.getItem(ACCESS_TOKEN_KEY) || '';
  } catch (_) {
    return '';
  }
};

export const getStoredRefreshToken = () => {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY) || '';
  } catch (_) {
    return '';
  }
};

export const getStoredUser = () => {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
};

export const setStoredAuth = ({ accessToken, refreshToken, user }) => {
  try {
    if (accessToken) {
      localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    } else {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
    }

    if (refreshToken) {
      localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    } else {
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    }

    if (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(USER_KEY);
    }
  } catch (_) {
    // No-op when storage is unavailable.
  }
};

export const clearStoredAuth = () => {
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch (_) {
    // No-op when storage is unavailable.
  }
};

export const buildWebSocketUrl = (token) => {
  if (!token) return '';
  return buildLiveWebSocketUrl(token);
};

/**
 * Fetch wrapper with strict 500ms timeout, single-flight cancellation, and bounded retries.
 * @param {string} endpoint - API path (e.g. '/signal/RELIANCE')
 * @param {Object} options - Fetch options
 * @returns {Promise<any>} Response JSON data
 */
async function apiFetch(endpoint, options = {}) {
  const normalizedEndpoint = normalizeEndpoint(endpoint);
  const isAuthEndpoint = /^\/auth\//.test(normalizedEndpoint);
  const {
    timeoutMs: providedTimeoutMs,
    signal: externalSignal,
    ...fetchOptions
  } = options;
  const timeoutMs = Number.isFinite(providedTimeoutMs) && providedTimeoutMs > 0
    ? normalizeTimeoutMs(providedTimeoutMs, isAuthEndpoint ? AUTH_TIMEOUT_MS : DEFAULT_TIMEOUT_MS)
    : normalizeTimeoutMs(isAuthEndpoint ? AUTH_TIMEOUT_MS : DEFAULT_TIMEOUT_MS, API_TIMEOUT_MAX_MS);
  const maxRetries = isAuthEndpoint ? 0 : MAX_API_RETRIES;
  const method = String(fetchOptions.method || 'GET').toUpperCase();

  if (normalizedEndpoint === AUTH_LOGIN_ENDPOINT && method !== 'POST') {
    const message = `Invalid HTTP method for login: ${method}. Expected POST.`;
    console.error('[AUTH LOGIN] blocked non-POST request', {
      endpoint: normalizedEndpoint,
      method,
    });
    throw {
      status: 0,
      message,
      endpoint: normalizedEndpoint,
      method,
    };
  }

  if (normalizedEndpoint === AUTH_LOGIN_ENDPOINT) {
    console.log('LOGIN REQUEST METHOD: POST');
  }

  const url = buildApiUrl(normalizedEndpoint);

  console.log('API CALL:', `${method} ${url}`, {
    endpoint: normalizedEndpoint,
    isAuthEndpoint,
  });

  const attempt = async (retryCount) => {
    const gate = beginSingleFlightRequest({
      externalSignal,
      key: `${method}:${normalizedEndpoint}`,
    });
    const id = setTimeout(() => gate.abort('request_timeout'), timeoutMs);

    try {
      const token = getStoredAccessToken();
      console.log('Calling API:', url);
      const response = await fetch(url, {
        ...fetchOptions,
        method,
        signal: gate.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...fetchOptions.headers,
        },
      });

      clearTimeout(id);

      if (!response.ok) {
        let message = `API Error: ${response.statusText}`;
        try {
          const errorData = await response.json();
          message = extractErrorMessage(errorData, message);
        } catch (_) {
          // Response body may be empty/non-JSON for gateway or proxy failures.
        }

        throw { status: response.status, message, url, method, endpoint: normalizedEndpoint };
      }

      const payload = await response.json();
      if (payload && typeof payload === 'object' && payload.success === false && !(isBundleEndpoint(normalizedEndpoint) && payload.data)) {
        throw {
          status: payload.code || 400,
          message: extractErrorMessage(payload, 'Request failed'),
          url,
          method,
          endpoint: normalizedEndpoint,
        };
      }

      return payload;
    } catch (error) {
      clearTimeout(id);

      const isAbortError = isAbortLikeRequestGateError(error);
      const abortReason = String(gate.signal?.reason || '');
      const isNetworkError = isAbortError || error instanceof TypeError;
      const isGatewayError = isGatewayTimeoutLike(error?.status);

      console.error('[API ERROR]:', {
        endpoint: normalizedEndpoint,
        url,
        errorName: error?.name,
        errorMessage: error?.message,
        isAbortError,
        isTypeError: error instanceof TypeError,
      });

      if ((isNetworkError || isGatewayError) && !isAbortError && retryCount < maxRetries && !isAuthEndpoint) {
        console.warn(`[apiFetch] transient failure fetching ${endpoint}, retry ${retryCount + 1}/${maxRetries}`);
        return attempt(retryCount + 1);
      }

      const normalizedError = error.status
        ? error
        : {
            status: 0,
            code: isAbortError
              ? (abortReason === 'request_timeout' ? 'ERR_TIMEOUT' : 'ERR_CANCELED')
              : undefined,
            message: isAbortError
              ? (abortReason === 'request_timeout'
                ? `Request timed out after ${timeoutMs}ms. Fail-fast triggered.`
                : 'Request canceled by a newer request.')
              : (error instanceof TypeError
                ? 'Network error: Unable to reach StockAI API. Please check your internet connection.'
                : (error?.message || 'Network/API error occurred. Please try again.')),
            url,
            method,
            endpoint: normalizedEndpoint,
          };

      logApiFailure({
        endpoint: normalizedEndpoint,
        method,
        url,
        status: normalizedError.status,
        message: normalizedError.message,
        error,
      });

      throw normalizedError;
    } finally {
      clearTimeout(id);
      gate.release();
    }
  };

  return attempt(0);
}

export const api = {
  getBundleRaw: async (symbol, interval = '1m', limit = 200, horizon = '15m') => {
    const qs = new URLSearchParams({
      interval,
      limit: String(limit),
      horizon,
    }).toString();
    return apiFetch(`/bundle/${encodeURIComponent(symbol)}?${qs}`, {
      timeoutMs: 8000,
    });
  },

  getBundle: async (symbol, interval = '1m', limit = 200, horizon = '15m') => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    const normalizedInterval = String(interval || '1m').trim();

    const payload = await api.getBundleRaw(normalizedSymbol, normalizedInterval, limit, horizon);
    const resolved = unwrapData(payload);
    if (resolved && (resolved.snapshot || resolved.history || resolved.prediction)) {
      return resolved;
    }

    return {
      symbol: normalizedSymbol,
      partial: true,
      warnings: ['Bundle payload incomplete'],
      history: { candles: [], count: 0, source: 'UNAVAILABLE', data_source: 'UNAVAILABLE' },
      snapshot: {
        symbol: normalizedSymbol,
        price: 0,
        ltp: 0,
        open: 0,
        high: 0,
        low: 0,
        close: 0,
        change: 0,
        volume: 0,
        source: 'UNAVAILABLE',
        data_source: 'UNAVAILABLE',
        market_status: 'CLOSED',
      },
      prediction: {
        symbol: normalizedSymbol,
        signal: 'HOLD',
        confidence: 0,
        confidence_pct: 0,
        prediction: 0,
        target: 0,
        stop_loss: 0,
        reasoning: 'Prediction unavailable',
      },
      indicators: {},
    };
  },

  getPrediction: async (symbol, interval = '1m', horizon = '15m') => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    if (!normalizedSymbol) {
      throw { status: 400, message: 'Symbol is required for prediction', url: `${API_BASE}/predict/{symbol}` };
    }

    const bundle = await api.getBundle(normalizedSymbol, interval, 100, horizon);
    const normalized = normalizePredictionPayload(bundle?.prediction, normalizedSymbol);

    if (!normalized) {
      throw {
        status: 0,
        message: 'Invalid prediction payload',
        url: `${API_BASE}/bundle/${normalizedSymbol}`,
      };
    }

    return normalized;
  },

  signup: async ({ username, email, password }) => {
    const payload = await apiFetch('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
    });
    return payload?.data || payload;
  },

  login: async ({ email, password }) => {
    const normalizedEmail = String(email || '').trim().toLowerCase();
    try {
      const payload = await apiFetch(AUTH_LOGIN_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ email: normalizedEmail, password }),
        timeoutMs: AUTH_TIMEOUT_MS,
      });
      return payload?.data || payload;
    } catch (error) {
      throw {
        ...(error && typeof error === 'object' ? error : {}),
        status: Number.isFinite(error?.status) ? error.status : 0,
        message:
          error?.message ||
          'Login failed. Please verify your credentials and try again.',
      };
    }
  },

  refresh: async (refreshToken) => {
    const payload = await apiFetch('/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
      headers: { Authorization: '' },
    });
    return payload?.data || payload;
  },

  me: async () => {
    const payload = await apiFetch('/auth/me');
    return payload?.data || payload;
  },

  logout: async () => {
    const payload = await apiFetch('/auth/logout', { method: 'POST' });
    return payload?.data || payload;
  },

  executeTrade: async (symbol) => {
    const payload = await apiFetch(`/trading/execute?symbol=${encodeURIComponent(symbol)}`, {
      method: 'POST',
    });
    return payload?.data || payload;
  },

  tradingStatus: async () => {
    const payload = await apiFetch('/trading/status');
    return payload?.data || payload;
  },
};

/**
 * Fetches signal, price, and candles in parallel for a fully populated view.
 * @param {string} symbol - Stock symbol
 * @param {string} tf - Timeframe
 * @returns {Promise<Object>} { signal, price, candles, errors: {} }
 */
export const getBundle = async (symbol, tf) => {
  return api.getBundle(symbol, tf);
};

let keepAliveTimer = null;

export const startApiKeepAlive = (intervalMs = 30000) => {
  if (typeof window === 'undefined') return;
  if (keepAliveTimer) return;

  const run = async () => {
    try {
      await apiFetch('/health', { method: 'GET', timeoutMs: 6000 });
    } catch (_) {
      // Keep-alive should be silent; failures are handled by normal request paths.
    }
  };

  keepAliveTimer = window.setInterval(run, Math.max(30000, Number(intervalMs) || 30000));
  void run();
};

export const stopApiKeepAlive = () => {
  if (!keepAliveTimer || typeof window === 'undefined') return;
  window.clearInterval(keepAliveTimer);
  keepAliveTimer = null;
};

export { API_BASE };
