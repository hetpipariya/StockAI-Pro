/**
 * Phase 1 Exports Index
 * Convenient re-exports of all Phase 1 utilities for easy importing
 * 
 * Usage:
 *   import { formatINR, useWebSocket, axiosInstance } from '@/phase1';
 */

// Constants
export {
  API_BASE_URL,
  WS_URL,
  WS_RECONNECT_DELAY_MS,
  WS_MAX_RECONNECT_ATTEMPTS,
  SIGNAL_POLL_INTERVAL_MS,
  NSE_INDICES,
  TIMEFRAMES,
  INDICATORS,
  API_ENDPOINTS,
  STORAGE_KEYS,
  HTTP_STATUS,
  CHART_CONFIG,
  PAGINATION,
  VALIDATION,
  RETRY_CONFIG,
  type NSEIndex,
  type Indicator,
  type Timeframe,
} from './utils/constants';

// Formatters
export {
  formatINR,
  formatPrice,
  formatPercent,
  formatVolume,
  formatLargeINR,
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  getChangeColor,
  getStatusColor,
} from './utils/formatters';

// API Client
export { default as axiosInstance } from './api/axios';

// Hooks
export { useWebSocket, type UseWebSocketOptions, type UseWebSocketReturn } from './hooks/useWebSocket';
