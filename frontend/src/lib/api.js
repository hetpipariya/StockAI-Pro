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

export const fetchStockBundle = async (symbol, options = {}) => {
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();
  if (!normalizedSymbol) throw new Error('Symbol is required');

  const response = await api.get(`/bundle/${encodeURIComponent(normalizedSymbol)}`, {
    params: {
      interval: options.interval || '1m',
      limit: options.limit || 150,
      horizon: options.horizon || '15m',
    },
  });

  // Backend contract is wrapped as { success, data, error, timestamp }.
  // Return normalized payload data for UI components.
  return unwrapPayload(response.data);
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

export const fetchMarketSnapshot = async (symbol) => {
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();
  if (!normalizedSymbol) throw new Error('Symbol is required');

  const response = await api.get(`/market/snapshot/${encodeURIComponent(normalizedSymbol)}`);
  const data = unwrapPayload(response.data);
  return data && typeof data === 'object' ? data : {};
};

// Search is smart on frontend but basic proxy here if necessary 
// We will define local fuzzy search for symbols
export const searchStocks = async (query) => {
  return await api.get(`/search?q=${query}`);
};
