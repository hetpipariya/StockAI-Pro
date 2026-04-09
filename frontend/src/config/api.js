const IS_PROD = Boolean(import.meta.env.PROD);
const IS_DEV = Boolean(import.meta.env.DEV);

const DEFAULT_API_BASE = IS_DEV ? 'http://localhost:8000' : 'https://api.stockai-pro.in';
const DEFAULT_WS_URL = IS_DEV ? 'ws://localhost:8000/live' : 'wss://api.stockai-pro.in/live';

const normalizeOrigin = (value, fallback) => {
  const raw = String(value || '').trim();
  if (!raw) return fallback;
  return raw.replace(/\/$/, '');
};

export const API_BASE = normalizeOrigin(import.meta.env.VITE_API_BASE_URL, DEFAULT_API_BASE);
export const API_URL = `${API_BASE}/api`;
export const WS_URL = normalizeOrigin(import.meta.env.VITE_WS_URL, DEFAULT_WS_URL);

export const API_FALLBACK_BASE = '';

const ensureLeadingSlash = (value) => {
  const path = String(value || '').trim();
  if (!path) return '';
  return path.startsWith('/') ? path : `/${path}`;
};

export const buildApiUrl = (endpoint = '') => {
  const path = ensureLeadingSlash(endpoint)
    .replace(/^\/api\/v1\/?/i, '/')
    .replace(/^\/api\/?/i, '/');
  return path ? `${API_URL}${path}` : API_URL;
};

export const buildLiveWebSocketUrl = (token = '') => {
  const safeToken = String(token || '').trim();
  if (!safeToken) return WS_URL;
  return `${WS_URL}?token=${encodeURIComponent(safeToken)}`;
};

export const isBackendReservedPath = (path) => {
  const p = String(path || '').toLowerCase();
  return p.startsWith('/api') || p.startsWith('/live') || p.startsWith('/ws');
};

export const getHealthCheckUrl = () => `${API_URL}/health`;

const apiConfig = {
  apiBase: API_BASE,
  apiUrl: API_URL,
  apiFallbackBase: API_FALLBACK_BASE,
  wsUrl: WS_URL,
  isProd: IS_PROD,
  isDev: IS_DEV,
};

export { apiConfig };
export default apiConfig;