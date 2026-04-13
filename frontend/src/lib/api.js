import axios from 'axios';

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const apiBaseUrl = !rawBaseUrl
  ? '/api/v1'
  : rawBaseUrl.endsWith('/api/v1')
    ? rawBaseUrl
    : rawBaseUrl.endsWith('/api')
      ? `${rawBaseUrl}/v1`
      : `${rawBaseUrl}/api/v1`;

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000,
});

api.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  if (token) {
    config.headers = {
      ...config.headers,
      Authorization: config.headers?.Authorization || `Bearer ${token}`,
    };
  }
  return config;
});

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const unwrapPayload = (payload) => {
  if (!payload || typeof payload !== 'object') return payload;
  if (payload.success === true && payload.data !== undefined) return payload.data;
  if (payload.status === 'success' && payload.data !== undefined) return payload.data;
  if (payload.status === 'ok' && payload.data !== undefined) return payload.data;
  if (payload.result !== undefined) return payload.result;
  if (payload.bundle !== undefined) return payload.bundle;
  if (payload.data !== undefined) return payload.data;
  return payload;
};

const extractSymbolRows = (payload) => {
  const unwrapped = unwrapPayload(payload);
  if (Array.isArray(unwrapped)) return unwrapped;
  if (Array.isArray(unwrapped?.symbols)) return unwrapped.symbols;
  if (Array.isArray(payload?.symbols)) return payload.symbols;
  if (Array.isArray(payload?.data?.symbols)) return payload.data.symbols;
  return [];
};

const normalizeSymbolList = (payload) => {
  const rows = extractSymbolRows(payload);
  return rows
    .map((item) => {
      if (!item) return null;
      if (typeof item === 'string') {
        const symbol = item.trim().toUpperCase();
        return symbol
          ? {
              symbol,
              name: symbol,
              aliases: [],
              type: 'stock',
              sector: 'Unknown',
            }
          : null;
      }

      const symbol = String(item.symbol || '').trim().toUpperCase();
      if (!symbol) return null;

      return {
        symbol,
        name: String(item.name || symbol),
        aliases: Array.isArray(item.aliases)
          ? item.aliases.filter((value) => typeof value === 'string')
          : [],
        type: String(item.type || 'stock'),
        sector: String(item.sector || 'Unknown'),
      };
    })
    .filter(Boolean);
};

const createEmptyBundle = (symbol) => ({
  symbol,
  history: {
    candles: [],
    count: 0,
    source: 'UNAVAILABLE',
    data_source: 'UNAVAILABLE',
  },
  snapshot: {
    symbol,
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
    symbol,
    signal: 'HOLD',
    confidence: 0,
    confidence_pct: 0,
    prediction: 0,
    target: 0,
    stop_loss: 0,
    reasoning: 'Prediction unavailable',
  },
  indicators: {
    symbol,
    ema_20: 0,
    ema_50: 0,
    rsi: 0,
    macd: {
      value: 0,
      signal: 0,
      histogram: 0,
    },
    bollinger: {
      upper: 0,
      middle: 0,
      lower: 0,
    },
  },
});

const normalizePrediction = (symbol, payload = {}, fallbackPrice = 0) => {
  if (!payload || typeof payload !== 'object') {
    return {
      symbol,
      signal: 'HOLD',
      confidence: 0,
      confidence_pct: 0,
      prediction: fallbackPrice,
      target: fallbackPrice,
      stop_loss: fallbackPrice,
      reasoning: 'Prediction unavailable',
    };
  }

  const confidenceRaw = toNumber(payload.confidence ?? payload.confidence_pct, 0);
  const confidence = confidenceRaw > 1 ? confidenceRaw / 100 : confidenceRaw;

  return {
    symbol,
    signal: String(payload.signal || payload.type || 'HOLD').toUpperCase(),
    confidence,
    confidence_pct: Math.round(confidence * 100),
    prediction: toNumber(payload.prediction ?? payload.price, fallbackPrice),
    target: toNumber(payload.target ?? payload.target_price, fallbackPrice),
    stop_loss: toNumber(payload.stop_loss ?? payload.stopLoss, fallbackPrice),
    reasoning: String(payload.reasoning || payload.reason || payload.explanation || 'Prediction unavailable'),
    timestamp: payload.timestamp,
  };
};

const normalizeBundlePayload = (symbol, payload) => {
  const defaults = createEmptyBundle(symbol);
  if (!payload || typeof payload !== 'object') return defaults;

  const flatCandles = Array.isArray(payload?.candles) ? payload.candles : [];
  const historyPayload = payload?.history && typeof payload.history === 'object' ? payload.history : {};
  const historyCandles = Array.isArray(historyPayload?.candles)
    ? historyPayload.candles
    : (Array.isArray(historyPayload?.data) ? historyPayload.data : flatCandles);

  const topLevelPrice = toNumber(payload?.latest_price ?? payload?.price, NaN);
  const snapshotPayload = payload?.snapshot && typeof payload.snapshot === 'object' ? payload.snapshot : {};
  const snapshotPrice = toNumber(snapshotPayload?.ltp ?? snapshotPayload?.price, NaN);
  const resolvedPrice = Number.isFinite(snapshotPrice)
    ? snapshotPrice
    : (Number.isFinite(topLevelPrice) ? topLevelPrice : 0);

  const predictionPayload = payload?.prediction && typeof payload.prediction === 'object'
    ? payload.prediction
    : (payload?.signal && typeof payload.signal === 'object' ? payload.signal : {});
  const normalizedPrediction = normalizePrediction(symbol, predictionPayload, resolvedPrice);

  return {
    ...defaults,
    ...payload,
    history: {
      ...defaults.history,
      ...historyPayload,
      candles: historyCandles,
      count: Array.isArray(historyCandles)
        ? historyCandles.length
        : toNumber(historyPayload?.count, 0),
    },
    snapshot: {
      ...defaults.snapshot,
      ...snapshotPayload,
      ltp: resolvedPrice,
      price: resolvedPrice,
    },
    prediction: {
      ...defaults.prediction,
      ...normalizedPrediction,
    },
    indicators: {
      ...defaults.indicators,
      ...(payload.indicators && typeof payload.indicators === 'object' ? payload.indicators : {}),
    },
  };
};

export const getBundle = async (symbol, options = {}) => {
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();
  if (!normalizedSymbol) throw new Error('Symbol is required');

  try {
    const response = await api.get(`/bundle/${encodeURIComponent(normalizedSymbol)}`, {
      params: {
        interval: options.interval || '1m',
        limit: options.limit || 100,
        horizon: options.horizon || '15m',
      },
    });

    const raw = unwrapPayload(response.data);
    const normalized = normalizeBundlePayload(normalizedSymbol, raw);

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('Bundle response:', {
        symbol: normalizedSymbol,
        raw: response.data,
        normalized,
      });
    }

    return normalized;
  } catch (error) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('Bundle request failed:', {
        symbol: normalizedSymbol,
        error: error?.message,
        status: error?.response?.status,
        data: error?.response?.data,
      });
    }
    throw error;
  }
};

export const fetchStockBundle = async (symbol, options = {}) => {
  return getBundle(symbol, options);
};

export const fetchMarketSymbols = async (limit = 500) => {
  const response = await api.get('/market/symbols', {
    params: { limit: Math.max(1, Math.min(Number(limit) || 100, 500)) },
  });

  return normalizeSymbolList(response.data);
};

export const searchMarketSymbols = async (query, limit = 100) => {
  const q = String(query || '').trim();
  if (!q) return [];

  const response = await api.get('/symbols/search', {
    params: {
      q,
      limit: Math.max(1, Math.min(Number(limit) || 100, 100)),
    },
  });

  return normalizeSymbolList(response.data);
};

// Search is smart on frontend but basic proxy here if necessary 
// We will define local fuzzy search for symbols
export const searchStocks = async (query) => {
  return await api.get(`/search?q=${query}`);
};
