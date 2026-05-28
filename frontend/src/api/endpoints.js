export const API_ENDPOINTS = {
  AUTH: {
    REGISTER: '/auth/register',
    LOGIN: '/auth/login',
    REFRESH: '/auth/refresh',
    LOGOUT: '/auth/logout',
    ME: '/auth/me',
  },
  PORTFOLIO: { BALANCE: '/portfolio/balance', HISTORY: '/portfolio/history' },
  SIGNALS: { ACTIVE: '/signals', DETAILS: (id) => `/signals/${id}` },
  TRADES: {
    EXECUTE: '/trading/execute',
    CLOSE: (id) => `/trades/${id}/close`,
    ACTIVE: '/trades/active',
  },
  /** Closed trades / journal — backend: GET /api/v1/trading/journal */
  TRADING: { JOURNAL: '/trading/journal' },
  SETTINGS: '/settings',
  SYSTEM_STATUS: '/system/status',
};