/**
 * @file useWebsocket.js
 * WebSocket hook for real-time price updates.
 * 
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Connection state management
 * - Symbol subscription management
 * - Error handling and recovery
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { buildLiveWebSocketUrl, WS_URL } from '../config/api';
import { getStoredAccessToken } from '../api/api';

// WebSocket connection states
export const WS_STATES = {
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  ERROR: 'error',
  UNAUTHENTICATED: 'unauthenticated',
};

// Reconnection configuration
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_MULTIPLIER = 1.5;
const MAX_RECONNECT_ATTEMPTS = 10;

// Reconnectable close codes (not permanent failures)
const RECONNECTABLE_CLOSE_CODES = new Set([
  1001, // Going Away
  1005, // No Status Received
  1006, // Abnormal Closure
  1011, // Unexpected Condition
  1012, // Service Restart
  1013, // Try Again Later
]);

/**
 * Convert a value to a finite number or return fallback.
 */
const toNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

/**
 * Hook for WebSocket connection to receive real-time price updates.
 * 
 * @param {string} symbol - Stock symbol to subscribe to
 * @param {boolean} enabled - Whether the WebSocket should be active
 * @returns {Object} WebSocket state and data
 */
export function useWebSocket(symbol, enabled = true) {
  const [livePrice, setLivePrice] = useState(null);
  const [priceChange, setPriceChange] = useState(null);
  const [changePct, setChangePct] = useState(null);
  const [wsStatus, setWsStatus] = useState(WS_STATES.DISCONNECTED);
  const [lastError, setLastError] = useState(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const previousSymbolRef = useRef('');
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);

  const selectedSymbol = String(symbol || '').trim().toUpperCase();

  /**
   * Clear all timers and reset state.
   */
  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  /**
   * Schedule a reconnection attempt with exponential backoff.
   */
  const scheduleReconnect = useCallback((connect) => {
    if (!mountedRef.current) return;
    
    reconnectAttemptsRef.current += 1;
    setReconnectAttempts(reconnectAttemptsRef.current);

    if (reconnectAttemptsRef.current > MAX_RECONNECT_ATTEMPTS) {
      console.error('[WebSocket] Max reconnection attempts reached');
      setWsStatus(WS_STATES.ERROR);
      setLastError('Max reconnection attempts reached. Please refresh the page.');
      return;
    }

    const delay = backoffRef.current;
    console.log(`[WebSocket] Scheduling reconnect in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
    
    setWsStatus(WS_STATES.RECONNECTING);
    
    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        backoffRef.current = Math.min(
          backoffRef.current * BACKOFF_MULTIPLIER,
          MAX_BACKOFF_MS
        );
        connect();
      }
    }, delay);
  }, []);

  /**
   * Connect to the WebSocket server.
   */
  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled || !selectedSymbol) {
      return;
    }

    // Check for authentication token
    const token = getStoredAccessToken();
    if (!token) {
      console.warn('[WebSocket] No authentication token available');
      setWsStatus(WS_STATES.UNAUTHENTICATED);
      return;
    }

    // Build WebSocket URL with token
    const wsUrl = buildLiveWebSocketUrl(token);
    if (!wsUrl) {
      console.error('[WebSocket] Failed to build WebSocket URL');
      setWsStatus(WS_STATES.ERROR);
      setLastError('WebSocket URL configuration error');
      return;
    }

    // Log connection attempt (mask token for security)
    console.log('[WebSocket] Connecting to:', wsUrl.replace(/token=[^&]+/, 'token=***'));

    setWsStatus(WS_STATES.CONNECTING);
    setLastError(null);

    let ws;
    try {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;
    } catch (error) {
      console.error('[WebSocket] Failed to create WebSocket:', error);
      setWsStatus(WS_STATES.ERROR);
      setLastError(`Failed to create WebSocket: ${error.message}`);
      scheduleReconnect(connect);
      return;
    }

    ws.onopen = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      
      console.log('[WebSocket] Connected successfully');
      setWsStatus(WS_STATES.CONNECTED);
      setLastError(null);
      
      // Reset backoff on successful connection
      backoffRef.current = INITIAL_BACKOFF_MS;
      reconnectAttemptsRef.current = 0;
      setReconnectAttempts(0);

      // Subscribe to the selected symbol
      try {
        ws.send(JSON.stringify({ 
          action: 'subscribe', 
          symbols: [selectedSymbol] 
        }));
        previousSymbolRef.current = selectedSymbol;
        console.log('[WebSocket] Subscribed to:', selectedSymbol);
      } catch (error) {
        console.error('[WebSocket] Failed to send subscription:', error);
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current || wsRef.current !== ws) return;

      let message;
      try {
        message = JSON.parse(event.data);
      } catch (error) {
        console.warn('[WebSocket] Failed to parse message:', error);
        return;
      }

      if (!message || typeof message !== 'object') return;

      // Handle heartbeat
      if (message.type === 'heartbeat') {
        try {
          ws.send(JSON.stringify({ action: 'pong' }));
        } catch (error) {
          console.warn('[WebSocket] Failed to send pong:', error);
        }
        return;
      }

      // Handle tick data
      if (message.type === 'tick') {
        const tickSymbol = String(message.symbol || '').toUpperCase();
        if (tickSymbol !== selectedSymbol) return;

        const ltp = toNumber(message.ltp, null);
        if (ltp == null) return;

        setLivePrice((prev) => {
          if (prev == null) return ltp;
          const delta = ltp - prev;
          setPriceChange(delta);
          setChangePct(prev !== 0 ? (delta / prev) * 100 : 0);
          return ltp;
        });
      }

      // Handle error messages from server
      if (message.type === 'error') {
        console.error('[WebSocket] Server error:', message.message || message);
        setLastError(message.message || 'Server error');
      }
    };

    ws.onclose = (event) => {
      if (wsRef.current === ws) {
        wsRef.current = null;
      }

      if (!mountedRef.current) return;

      console.log('[WebSocket] Connection closed:', {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
      });

      // Check if we should attempt to reconnect
      if (RECONNECTABLE_CLOSE_CODES.has(event.code) || !event.wasClean) {
        scheduleReconnect(connect);
      } else {
        setWsStatus(WS_STATES.DISCONNECTED);
      }
    };

    ws.onerror = (error) => {
      if (!mountedRef.current || wsRef.current !== ws) return;

      console.error('[WebSocket] Error:', error);
      setWsStatus(WS_STATES.ERROR);
      setLastError('WebSocket connection error');

      // Close the socket to trigger onclose handler
      try {
        ws.close();
      } catch (closeError) {
        console.warn('[WebSocket] Error closing socket:', closeError);
        scheduleReconnect(connect);
      }
    };
  }, [enabled, selectedSymbol, scheduleReconnect]);

  /**
   * Disconnect from the WebSocket server.
   */
  const disconnect = useCallback(() => {
    cleanup();
    
    const ws = wsRef.current;
    wsRef.current = null;

    if (ws) {
      // Remove event handlers to prevent reconnection
      ws.onclose = null;
      ws.onerror = null;

      // Unsubscribe from previous symbol
      if (previousSymbolRef.current) {
        try {
          ws.send(JSON.stringify({ 
            action: 'unsubscribe', 
            symbols: [previousSymbolRef.current] 
          }));
        } catch (error) {
          // Ignore errors during cleanup
        }
      }

      // Close the connection
      try {
        ws.close(1000, 'Client disconnect');
      } catch (error) {
        // Ignore errors during cleanup
      }
    }

    setWsStatus(WS_STATES.DISCONNECTED);
  }, [cleanup]);

  /**
   * Force reconnect (useful for manual retry).
   */
  const reconnect = useCallback(() => {
    disconnect();
    backoffRef.current = INITIAL_BACKOFF_MS;
    reconnectAttemptsRef.current = 0;
    setReconnectAttempts(0);
    connect();
  }, [disconnect, connect]);

  // Effect to manage connection lifecycle
  useEffect(() => {
    mountedRef.current = true;

    // Reset state when symbol changes
    setLivePrice(null);
    setPriceChange(null);
    setChangePct(null);
    setLastError(null);

    // Connect to WebSocket
    connect();

    // Cleanup on unmount or dependency change
    return () => {
      mountedRef.current = false;
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    // Price data
    livePrice,
    priceChange,
    changePct,
    
    // Connection state
    wsStatus,
    isConnected: wsStatus === WS_STATES.CONNECTED,
    isConnecting: wsStatus === WS_STATES.CONNECTING || wsStatus === WS_STATES.RECONNECTING,
    
    // Error handling
    lastError,
    reconnectAttempts,
    
    // Actions
    reconnect,
    disconnect,
  };
}

// Alias for backward compatibility
export const useWebsocket = useWebSocket;

export default useWebSocket;
