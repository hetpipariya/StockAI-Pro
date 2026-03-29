const IS_PROD = Boolean(import.meta.env.PROD);
const IS_DEV = Boolean(import.meta.env.DEV);

export const API_BASE = 'https://api.stockai-pro.in';
export const API_URL = 'https://api.stockai-pro.in/api';
export const WS_URL = 'wss://api.stockai-pro.in/live';

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