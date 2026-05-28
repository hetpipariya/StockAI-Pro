/**
 * Phase 1 Build Verification
 * Tests that all modules can be imported without errors
 */

// Test constants import
import {
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
} from '../utils/constants';

// Test formatters import
import {
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
} from '../utils/formatters';

// Test axios import
import axiosInstance from '../api/axios';

// Test WebSocket hook import
import { useWebSocket } from '../hooks/useWebSocket';

// Verify constants are exported correctly
console.log('✓ Constants loaded:', {
  API_BASE_URL,
  WS_RECONNECT_DELAY_MS,
  NSE_INDICES,
  TIMEFRAMES,
});

// Verify formatters work
console.log('✓ Formatters loaded:', {
  testINR: formatINR(1000),
  testPrice: formatPrice(100.5),
  testPercent: formatPercent(5.25),
  testVolume: formatVolume(1000000),
});

// Verify axios instance
console.log('✓ Axios instance loaded:', !!axiosInstance.interceptors);

// Verify WebSocket hook
console.log('✓ WebSocket hook loaded:', typeof useWebSocket);

console.log('\n✅ Phase 1 Build Verification Complete - All modules imported successfully!');
