/**
 * @file api.js
 * Centralized API module for StockAI-Pro.
 */

const getEnvVar = (reactName, viteName, fallback) => {
  try {
    if (import.meta && import.meta.env && import.meta.env[viteName]) {
      return import.meta.env[viteName];
    }
    if (typeof process !== 'undefined' && process.env && process.env[reactName]) {
      return process.env[reactName];
    }
  } catch (e) {
    // Ignore ReferenceErrors
  }
  return fallback;
};

const ACCESS_TOKEN_KEY = 'stockai_access_token';
const REFRESH_TOKEN_KEY = 'stockai_refresh_token';
const USER_KEY = 'stockai_user';
const PROD_API_ORIGIN = 'https://api.stockai-pro.in';
const PROD_API_BASE = `${PROD_API_ORIGIN}/api/v1`;
const DEFAULT_TIMEOUT_MS = 12000;
const AUTH_TIMEOUT_MS = 20000;
const AUTH_LOGIN_ENDPOINT = '/auth/login';

const normalizeBaseUrl = (value) => String(value || '').replace(/\/+$/, '');

// Pin all requests to the production API domain to prevent bad env overrides.
const RAW_BASE_URL = PROD_API_ORIGIN;
const API_BASE = PROD_API_BASE;

const normalizeEndpoint = (endpoint) => {
  const raw = String(endpoint || '');
  const path = raw.startsWith('/') ? raw : `/${raw}`;

  if (path === '/api/v1') return '/';
  if (path.startsWith('/api/v1/')) return path.slice('/api/v1'.length);
  if (path.startsWith('/api/')) return path.slice('/api'.length);

  return path;
};

const buildApiUrl = (endpoint) => {
  if (endpoint === '/') return API_BASE;
  return `${API_BASE}${endpoint}`;
};

const RAW_WS_URL = normalizeBaseUrl(getEnvVar('REACT_APP_WS_URL', 'VITE_WS_URL', ''));

const resolveWsBase = () => {
  if (RAW_WS_URL) {
    return RAW_WS_URL;
  }

  const source = RAW_BASE_URL || PROD_API_ORIGIN;
  return source.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
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

const isAbortLikeError = (error) => {
  const message = String(error?.message || '');
  return (
    error?.name === 'AbortError' ||
    /signal aborted without reason/i.test(message) ||
    /operation was aborted/i.test(message)
  );
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
  const wsBase = resolveWsBase();
  if (!token || !wsBase) return '';

  let normalizedBase = wsBase;
  if (!/^wss?:\/\//i.test(normalizedBase) && /^https?:\/\//i.test(normalizedBase)) {
    normalizedBase = normalizedBase.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
  }

  if (!/^wss?:\/\//i.test(normalizedBase) && normalizedBase.startsWith('/')) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    normalizedBase = `${protocol}//${window.location.host}${normalizedBase}`;
  }

  const withWsPath = /(\/ws|\/live)$/i.test(normalizedBase)
    ? normalizedBase.replace(/\/live$/i, '/ws')
    : `${normalizedBase}/ws`;

  const sep = withWsPath.includes('?') ? '&' : '?';
  return `${withWsPath}${sep}token=${encodeURIComponent(token)}`;
};

/**
 * Fetch wrapper with timeout, auto-JSON, error normalization and retry on network failure.
 * @param {string} endpoint - API path (e.g. '/api/signal/RELIANCE')
 * @param {Object} options - Fetch options
 * @returns {Promise<any>} Response JSON data
 */
async function apiFetch(endpoint, options = {}) {
  const isDev = getEnvVar('NODE_ENV', 'MODE', '') !== 'production';
  const normalizedEndpoint = normalizeEndpoint(endpoint);
  const isAuthEndpoint = /^\/auth\//.test(normalizedEndpoint);
  const {
    timeoutMs: providedTimeoutMs,
    signal: externalSignal,
    ...fetchOptions
  } = options;
  const timeoutMs = Number.isFinite(providedTimeoutMs) && providedTimeoutMs > 0
    ? providedTimeoutMs
    : (isAuthEndpoint ? AUTH_TIMEOUT_MS : DEFAULT_TIMEOUT_MS);
  const method = fetchOptions.method || 'GET';
  const url = buildApiUrl(normalizedEndpoint);
  
  const attempt = async (retryCount) => {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeoutMs);

    if (externalSignal) {
      if (externalSignal.aborted) {
        controller.abort();
      } else {
        externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
      }
    }

    try {
      const token = getStoredAccessToken();
      console.log('Calling API:', url);
      const response = await fetch(url, {
        ...fetchOptions,
        signal: controller.signal,
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
        } catch (_) {}
        
        throw { status: response.status, message, url, method, endpoint: normalizedEndpoint };
      }

      const payload = await response.json();
      if (payload && typeof payload === 'object' && payload.success === false) {
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

      const isAbortError = isAbortLikeError(error);
      
      // Retry once on network failure (TypeError usually means network/CORS) or timeout (AbortError)
      // Do not retry on 4xx/5xx (which are thrown as objects above {status, message})
      const isNetworkError = isAbortError || error instanceof TypeError;
      if (isNetworkError && retryCount < 1 && !isAuthEndpoint) {
        if (isDev) console.warn(`[apiFetch] Network failure fetching ${endpoint}, retrying...`);
        return attempt(retryCount + 1);
      }
      
      if (isDev) console.error(`[apiFetch] Error fetching ${endpoint}:`, error);
      
      // Normalize error output
      const normalizedError = error.status
        ? error
        : {
            status: 0,
            message: isAbortError
              ? `Request timed out after ${Math.round(timeoutMs / 1000)}s. Please try again.`
              : (error instanceof TypeError
                ? 'Network error: Unable to reach StockAI API. Please check your internet connection.'
                : (error.message || 'Network error: Request failed.')),
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
    return apiFetch(`/bundle/${encodeURIComponent(symbol)}?${qs}`);
  },

  getBundle: async (symbol, interval = '1m', limit = 200, horizon = '15m') => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    const normalizedInterval = String(interval || '1m').trim();

    try {
      const payload = await api.getBundleRaw(normalizedSymbol, normalizedInterval, limit, horizon);
      const resolved = unwrapData(payload);
      if (resolved && (resolved.snapshot || resolved.history || resolved.prediction)) {
        return resolved;
      }
    } catch (error) {
      // If direct bundle route fails for any reason, fall back to composing
      // from individual market/predict/indicator endpoints.
    }

    const calls = await Promise.allSettled([
      apiFetch(`/market/snapshot?symbol=${encodeURIComponent(normalizedSymbol)}`),
      apiFetch(
        `/market/history?symbol=${encodeURIComponent(normalizedSymbol)}&interval=${encodeURIComponent(normalizedInterval)}&limit=${encodeURIComponent(String(limit))}`
      ),
      apiFetch(
        `/signal?symbol=${encodeURIComponent(normalizedSymbol)}&timeframe=${encodeURIComponent(normalizedInterval)}&horizon=${encodeURIComponent(horizon)}`
      ),
      apiFetch(
        `/predict?symbol=${encodeURIComponent(normalizedSymbol)}&timeframe=${encodeURIComponent(normalizedInterval)}&horizon=${encodeURIComponent(horizon)}`
      ),
      apiFetch(
        `/indicators?symbol=${encodeURIComponent(normalizedSymbol)}&timeframe=${encodeURIComponent(normalizedInterval)}`
      ),
    ]);

    const [snapshotResult, historyResult, signalResult, predictResult, indicatorsResult] = calls;

    const snapshot = snapshotResult.status === 'fulfilled' ? unwrapData(snapshotResult.value) : null;
    const historyRows = historyResult.status === 'fulfilled' ? normalizeHistoryRows(historyResult.value) : [];
    const signalData = signalResult.status === 'fulfilled' ? unwrapData(signalResult.value) : null;
    const predictData = predictResult.status === 'fulfilled' ? unwrapData(predictResult.value) : null;
    const indicatorsData = indicatorsResult.status === 'fulfilled' ? unwrapData(indicatorsResult.value) : null;

    const prediction = signalData || predictData || null;
    const predictionIndicators = prediction && typeof prediction.indicators === 'object' ? prediction.indicators : {};
    const normalizedPredictionIndicators = Object.entries(predictionIndicators || {}).reduce((acc, [key, value]) => {
      const num = toFiniteNumber(value, null);
      if (num != null) acc[key] = num;
      return acc;
    }, {});

    const indicatorsFromEndpoint = buildIndicatorsFromRows(
      Array.isArray(indicatorsData?.data)
        ? indicatorsData.data
        : Array.isArray(indicatorsData)
          ? indicatorsData
          : []
    );

    if (!snapshot && historyRows.length === 0 && !prediction) {
      const firstError = calls.find((entry) => entry.status === 'rejected');
      if (firstError && firstError.reason) throw firstError.reason;
      throw { status: 0, message: 'Failed to load market bundle', url: `${API_BASE}/market/*` };
    }

    return {
      symbol: normalizedSymbol,
      snapshot: snapshot || { symbol: normalizedSymbol },
      history: {
        interval: normalizedInterval,
        candles: historyRows,
      },
      prediction,
      indicators:
        Object.keys(normalizedPredictionIndicators).length > 0
          ? normalizedPredictionIndicators
          : indicatorsFromEndpoint,
      source: 'composed-fallback',
    };
  },

  getPrediction: async (symbol) => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    if (!normalizedSymbol) {
      throw { status: 400, message: 'Symbol is required for prediction', url: `${API_BASE}/predict/{symbol}` };
    }

    try {
      const payload = await apiFetch(`/predict/${encodeURIComponent(normalizedSymbol)}`);
      const normalized = normalizePredictionPayload(payload, normalizedSymbol);
      if (!normalized) {
        throw { status: 0, message: 'Invalid prediction payload', url: `${API_BASE}/predict/${normalizedSymbol}` };
      }
      return normalized;
    } catch (pathError) {
      const fallbackPayload = await apiFetch(
        `/predict?symbol=${encodeURIComponent(normalizedSymbol)}&horizon=${encodeURIComponent('15m')}`
      );
      const normalized = normalizePredictionPayload(fallbackPayload, normalizedSymbol);
      if (!normalized) throw pathError;
      return normalized;
    }
  },

  signup: async ({ username, email, password }) => {
    const payload = await apiFetch('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
    });
    return payload?.data || payload;
  },

  login: async ({ username, password }) => {
    const normalizedUsername = String(username || '').trim();
    try {
      const payload = await apiFetch(AUTH_LOGIN_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ username: normalizedUsername, password }),
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

export { getEnvVar, API_BASE };
