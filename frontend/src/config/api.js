/**
 * @file api.js
 * Centralized API configuration for StockAI-Pro.
 * 
 * This file handles:
 * - Environment-based API base URL configuration
 * - WebSocket URL configuration with absolute URL enforcement
 * - URL building utilities
 * 
 * Environment Variables:
 * - VITE_API_BASE_URL: Base URL for API (e.g., https://api.stockai-pro.in)
 * - VITE_WS_URL: WebSocket URL (e.g., wss://api.stockai-pro.in/live)
 */

const IS_PROD = Boolean(import.meta.env.PROD);
const IS_DEV = Boolean(import.meta.env.DEV);

// Production backend URLs
const PROD_API_BASE = 'https://api.stockai-pro.in';
const PROD_API_FALLBACK_BASE = 'https://stockai-pro.onrender.com';
const PROD_WS_URL = 'wss://api.stockai-pro.in/live';

// Development backend URLs
const DEV_API_BASE = 'http://localhost:8000';
const DEV_WS_URL = 'ws://localhost:8000/live';

/**
 * Resolve API base URL from environment variables.
 * Supports both VITE_API_BASE_URL and legacy VITE_API_URL.
 * Strips any /api/v1 suffix to normalize the base URL.
 */
const resolveApiBase = () => {
  const envApiBase = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL;
  
  if (envApiBase) {
    // Strip /api/v1 or /api suffix if present (normalize to base URL)
    return envApiBase
      .replace(/\/api\/v1\/?$/, '')
      .replace(/\/api\/?$/, '')
      .replace(/\/$/, ''); // Remove trailing slash
  }
  
  return IS_PROD ? PROD_API_BASE : DEV_API_BASE;
};

/**
 * Resolve WebSocket URL from environment variables.
 * CRITICAL: Always returns an absolute URL, never relative.
 * Relative URLs would connect to the frontend domain instead of backend.
 */
const resolveWsUrl = () => {
  const rawWsUrl = import.meta.env.VITE_WS_URL;
  
  // Check if URL is relative (starts with / or doesn't have protocol)
  const isRelativeUrl = rawWsUrl && (
    rawWsUrl.startsWith('/') || 
    !rawWsUrl.includes('://')
  );
  
  // If relative URL is provided, ignore it and use default
  // This prevents connecting to frontend domain instead of backend
  if (isRelativeUrl) {
    console.warn(
      '[API Config] Relative WebSocket URL detected and ignored:',
      rawWsUrl,
      '- Using default:',
      IS_PROD ? PROD_WS_URL : DEV_WS_URL
    );
    return IS_PROD ? PROD_WS_URL : DEV_WS_URL;
  }

  const candidateUrl = rawWsUrl || (IS_PROD ? PROD_WS_URL : DEV_WS_URL);
  try {
    const parsed = new URL(candidateUrl);
    const normalizedPath = String(parsed.pathname || '').trim();

    // If env only provides a host (for example wss://host), force the live endpoint.
    if (!normalizedPath || normalizedPath === '/') {
      parsed.pathname = '/live';
      return parsed.toString().replace(/\/$/, '');
    }

    return parsed.toString().replace(/\/$/, '');
  } catch (_) {
    console.warn('[API Config] Invalid WebSocket URL detected, using default:', candidateUrl);
    return IS_PROD ? PROD_WS_URL : DEV_WS_URL;
  }
};

// Export resolved URLs
export const API_BASE = resolveApiBase();
export const API_V1_BASE = `${API_BASE}/api/v1`;
export const WS_URL = resolveWsUrl();
export const API_FALLBACK_BASE = (
  import.meta.env.VITE_API_FALLBACK_URL ||
  (IS_PROD ? PROD_API_FALLBACK_BASE : '')
)
  .replace(/\/$/, '');

// Log configuration in development for debugging
if (IS_DEV) {
  console.log('[API Config] Environment:', {
    IS_PROD,
    IS_DEV,
    MODE: import.meta.env.MODE,
    VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL || '(not set)',
    VITE_API_URL: import.meta.env.VITE_API_URL || '(not set)',
    VITE_WS_URL: import.meta.env.VITE_WS_URL || '(not set)',
  });
  console.log('[API Config] Resolved URLs:', {
    API_BASE,
    API_V1_BASE,
    WS_URL,
  });
}

/**
 * Normalize an API endpoint path.
 * Ensures path starts with / and strips any /api/v1 prefix.
 * @param {string} endpoint - The endpoint path
 * @returns {string} Normalized endpoint path
 */
const normalizeEndpoint = (endpoint) => {
  const path = String(endpoint || '').trim();
  if (!path) return '/';
  
  // Ensure path starts with /
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  
  // Strip /api/v1 or /api prefix if present
  if (normalizedPath.startsWith('/api/v1')) {
    return normalizedPath.slice('/api/v1'.length) || '/';
  }
  if (normalizedPath.startsWith('/api')) {
    return normalizedPath.slice('/api'.length) || '/';
  }
  
  return normalizedPath;
};

/**
 * Build a full API URL from an endpoint path.
 * Always returns an absolute URL pointing to the backend.
 * @param {string} endpoint - The endpoint path (e.g., '/health', '/signal/RELIANCE')
 * @returns {string} Full API URL
 * 
 * @example
 * buildApiUrl('/health') // => 'https://api.stockai-pro.in/api/v1/health'
 * buildApiUrl('/api/v1/signal/TCS') // => 'https://api.stockai-pro.in/api/v1/signal/TCS'
 * buildApiUrl('market/snapshot') // => 'https://api.stockai-pro.in/api/v1/market/snapshot'
 */
export const buildApiUrl = (endpoint) => {
  const normalizedEndpoint = normalizeEndpoint(endpoint);
  
  if (!normalizedEndpoint || normalizedEndpoint === '/') {
    return API_V1_BASE;
  }
  
  return `${API_V1_BASE}${normalizedEndpoint}`;
};

/**
 * Build a WebSocket URL with optional authentication token.
 * Always returns an absolute URL pointing to the backend.
 * @param {string} [token] - Optional authentication token
 * @returns {string} Full WebSocket URL with token if provided
 * 
 * @example
 * buildLiveWebSocketUrl() // => 'wss://api.stockai-pro.in/live'
 * buildLiveWebSocketUrl('abc123') // => 'wss://api.stockai-pro.in/live?token=abc123'
 */
export const buildLiveWebSocketUrl = (token = '') => {
  if (!WS_URL) {
    console.error('[API Config] WebSocket URL is not configured');
    return '';
  }

  const normalizedToken = String(token || '').trim();
  if (!normalizedToken) {
    return WS_URL;
  }

  const separator = WS_URL.includes('?') ? '&' : '?';
  return `${WS_URL}${separator}token=${encodeURIComponent(normalizedToken)}`;
};

/**
 * Check if a path is reserved for backend API.
 * Used to prevent frontend routing from intercepting API paths.
 * @param {string} path - The path to check
 * @returns {boolean} True if path should be handled by backend
 */
export const isBackendReservedPath = (path) => {
  const normalizedPath = String(path || '').toLowerCase();
  return (
    normalizedPath.startsWith('/api') ||
    normalizedPath.startsWith('/live') ||
    normalizedPath.startsWith('/ws')
  );
};

/**
 * Get the health check URL for the backend.
 * Useful for connectivity testing.
 * @returns {string} Health check URL
 */
export const getHealthCheckUrl = () => `${API_BASE}/health`;

/**
 * Configuration object for external use.
 */
export const apiConfig = {
  apiBase: API_BASE,
  apiV1Base: API_V1_BASE,
  apiFallbackBase: API_FALLBACK_BASE,
  wsUrl: WS_URL,
  isProd: IS_PROD,
  isDev: IS_DEV,
};

export default apiConfig;
