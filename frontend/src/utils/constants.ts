/**
 * Application Constants
 * Central configuration for API endpoints, timeframes, indicators, and WebSocket settings
 */

// API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/live';

// WebSocket Configuration
export const WS_RECONNECT_DELAY_MS = 3000;
export const WS_MAX_RECONNECT_ATTEMPTS = 10;

// Polling Configuration
export const SIGNAL_POLL_INTERVAL_MS = 30000; // 30 seconds

// NSE Indices
export const NSE_INDICES = [
  'NIFTY 50',
  'NIFTY BANK',
  'NIFTY IT',
  'NIFTY MIDCAP',
] as const;

export type NSEIndex = (typeof NSE_INDICES)[number];

// Timeframes Configuration
export interface Timeframe {
  label: string;
  value: string;
  seconds?: number;
}

export const TIMEFRAMES: Timeframe[] = [
  { label: '1m', value: '1minute', seconds: 60 },
  { label: '5m', value: '5minute', seconds: 300 },
  { label: '15m', value: '15minute', seconds: 900 },
  { label: '30m', value: '30minute', seconds: 1800 },
  { label: '1h', value: '60minute', seconds: 3600 },
  { label: '1D', value: '1day', seconds: 86400 },
  { label: '1W', value: '1week', seconds: 604800 },
  { label: '1M', value: '1month', seconds: 2592000 },
];

// Technical Indicators
export const INDICATORS = [
  'EMA9',
  'EMA21',
  'EMA50',
  'RSI',
  'MACD',
  'VWAP',
] as const;

export type Indicator = (typeof INDICATORS)[number];

// API Endpoints
export const API_ENDPOINTS = {
  // Authentication
  LOGIN: '/api/v1/auth/login',
  LOGOUT: '/api/v1/auth/logout',
  REFRESH_TOKEN: '/api/v1/auth/refresh',
  VERIFY_TOKEN: '/api/v1/auth/verify',

  // User
  USER_PROFILE: '/api/v1/user/profile',
  USER_PREFERENCES: '/api/v1/user/preferences',
  UPDATE_PREFERENCES: '/api/v1/user/preferences',

  // Stock Data
  STOCK_SEARCH: '/api/v1/stocks/search',
  STOCK_DETAILS: '/api/v1/stocks/:symbol',
  STOCK_QUOTE: '/api/v1/stocks/:symbol/quote',
  STOCK_HISTORICAL: '/api/v1/stocks/:symbol/historical',
  STOCK_INDICATORS: '/api/v1/stocks/:symbol/indicators',

  // Signals
  SIGNALS_LIST: '/api/v1/signals',
  SIGNAL_DETAILS: '/api/v1/signals/:id',
  SIGNAL_TRADES: '/api/v1/signals/:id/trades',

  // Watchlist
  WATCHLIST: '/api/v1/watchlist',
  WATCHLIST_CREATE: '/api/v1/watchlist',
  WATCHLIST_UPDATE: '/api/v1/watchlist/:id',
  WATCHLIST_DELETE: '/api/v1/watchlist/:id',
  WATCHLIST_ADD_STOCK: '/api/v1/watchlist/:id/stocks',
  WATCHLIST_REMOVE_STOCK: '/api/v1/watchlist/:id/stocks/:symbol',

  // Portfolio
  PORTFOLIO: '/api/v1/portfolio',
  PORTFOLIO_HOLDINGS: '/api/v1/portfolio/holdings',
  PORTFOLIO_TRADES: '/api/v1/portfolio/trades',

  // Alerts
  ALERTS: '/api/v1/alerts',
  ALERT_CREATE: '/api/v1/alerts',
  ALERT_UPDATE: '/api/v1/alerts/:id',
  ALERT_DELETE: '/api/v1/alerts/:id',

  // Market Data
  MARKET_STATUS: '/api/v1/market/status',
  MARKET_GAINERS: '/api/v1/market/gainers',
  MARKET_LOSERS: '/api/v1/market/losers',
  MARKET_INDICES: '/api/v1/market/indices',
} as const;

// Local Storage Keys
export const STORAGE_KEYS = {
  ACCESS_TOKEN: 'stockai_access_token',
  REFRESH_TOKEN: 'stockai_refresh_token',
  USER_DATA: 'stockai_user_data',
  USER_PREFERENCES: 'stockai_preferences',
  WATCHLISTS: 'stockai_watchlists',
  ALERTS: 'stockai_alerts',
} as const;

// HTTP Status Codes
export const HTTP_STATUS = {
  OK: 200,
  CREATED: 201,
  NO_CONTENT: 204,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  CONFLICT: 409,
  UNPROCESSABLE_ENTITY: 422,
  INTERNAL_SERVER_ERROR: 500,
  SERVICE_UNAVAILABLE: 503,
} as const;

// Chart Configuration
export const CHART_CONFIG = {
  HEIGHT_TRADING: 500,
  HEIGHT_MINI: 200,
  CANDLESTICK_UPCOLOR: '#10b981',
  CANDLESTICK_DOWNCOLOR: '#ef4444',
  VOLUME_COLOR: 'rgba(0, 212, 255, 0.3)',
  GRID_COLOR: 'rgba(255, 255, 255, 0.05)',
} as const;

// Pagination
export const PAGINATION = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
} as const;

// Validation Rules
export const VALIDATION = {
  MIN_PASSWORD_LENGTH: 8,
  MAX_WATCHLIST_NAME_LENGTH: 50,
  MAX_ALERT_DESCRIPTION_LENGTH: 200,
  MIN_STOCK_SYMBOL_LENGTH: 1,
  MAX_STOCK_SYMBOL_LENGTH: 20,
} as const;

// Retry Configuration
export const RETRY_CONFIG = {
  MAX_ATTEMPTS: 3,
  INITIAL_DELAY_MS: 1000,
  BACKOFF_MULTIPLIER: 2,
  MAX_DELAY_MS: 10000,
} as const;
