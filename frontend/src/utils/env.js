/**
 * @file env.js
 * Environment utilities - re-exports from centralized config.
 * 
 * This file exists for backward compatibility.
 * New code should import directly from '../config/api'.
 */

import {
  API_BASE as CONFIG_API_BASE,
  API_V1_BASE,
  WS_URL,
  buildApiUrl,
  buildLiveWebSocketUrl,
  isBackendReservedPath,
  getHealthCheckUrl,
  apiConfig,
} from '../config/api';

// Re-export WebSocket URL
export { WS_URL };

// Re-export API URLs
export const API_ORIGIN = CONFIG_API_BASE;
export const API_BASE = API_V1_BASE;

// For backward compatibility - list of API origin candidates
// In the new architecture, we only use one origin
export const API_ORIGIN_CANDIDATES = [API_ORIGIN];

// Re-export utilities
export { 
  buildApiUrl, 
  buildLiveWebSocketUrl, 
  isBackendReservedPath,
  getHealthCheckUrl,
  apiConfig,
};

// Default export
export default apiConfig;
