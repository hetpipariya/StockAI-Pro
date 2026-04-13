export const API_ENDPOINTS = {
  AUTH: { REGISTER: '/auth/register', LOGIN: '/auth/login', REFRESH: '/auth/refresh', LOGOUT: '/auth/logout', ME: '/auth/me' },
  PORTFOLIO: { BALANCE: '/portfolio/balance', HISTORY: '/portfolio/history' },
  SIGNALS: { ACTIVE: '/signals', DETAILS: id => `/signals/${id}` },
  TRADES: { EXECUTE: '/trades/execute', CLOSE: id => `/trades/${id}/close`, ACTIVE: '/trades/active', HISTORY: '/trades/history' },
  SETTINGS: '/settings', SYSTEM_STATUS: '/system/status'
};