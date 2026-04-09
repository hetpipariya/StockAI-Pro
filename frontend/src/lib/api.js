import axios from 'axios';

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const apiBaseUrl = rawBaseUrl.endsWith('/api') ? rawBaseUrl : `${rawBaseUrl}/api`;

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000,
});

const unwrapPayload = (payload) => {
  if (!payload || typeof payload !== 'object') return payload;
  if (payload.success === true && payload.data !== undefined) return payload.data;
  if (payload.status === 'success' && payload.data !== undefined) return payload.data;
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

const normalizeBundlePayload = (symbol, payload) => {
  const defaults = createEmptyBundle(symbol);
  if (!payload || typeof payload !== 'object') return defaults;

  return {
    ...defaults,
    ...payload,
    history: {
      ...defaults.history,
      ...(payload.history && typeof payload.history === 'object' ? payload.history : {}),
      candles: Array.isArray(payload?.history?.candles) ? payload.history.candles : [],
    },
    snapshot: {
      ...defaults.snapshot,
      ...(payload.snapshot && typeof payload.snapshot === 'object' ? payload.snapshot : {}),
    },
    prediction: {
      ...defaults.prediction,
      ...(payload.prediction && typeof payload.prediction === 'object' ? payload.prediction : {}),
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

  const response = await api.get(`/bundle/${encodeURIComponent(normalizedSymbol)}`, {
    params: {
      interval: options.interval || '1m',
      limit: options.limit || 150,
      horizon: options.horizon || '15m',
    },
  });

  const raw = unwrapPayload(response.data);
  return normalizeBundlePayload(normalizedSymbol, raw);
};

export const fetchStockBundle = async (symbol, options = {}) => {
  return getBundle(symbol, options);
};

export const fetchMarketSymbols = async (limit = 100) => {
  const response = await api.get('/market/symbols', {
    params: { limit: Math.max(1, Math.min(Number(limit) || 100, 500)) },
  });

  return normalizeSymbolList(response.data);
};

export const searchMarketSymbols = async (query, limit = 25) => {
  const q = String(query || '').trim();
  if (!q) return [];

  const response = await api.get('/symbols/search', {
    params: {
      q,
      limit: Math.max(1, Math.min(Number(limit) || 25, 100)),
    },
  });

  return normalizeSymbolList(response.data);
};

// Search is smart on frontend but basic proxy here if necessary 
// We will define local fuzzy search for symbols
export const searchStocks = async (query) => {
  return await api.get(`/search?q=${query}`);
};
