/**
 * useWebSocket Hook
 * Custom WebSocket hook with debounce logic for high-frequency data streams.
 * Prevents React state from being overwhelmed during high volatility.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

const WS_STATES = {
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  ERROR: 'error',
};

/**
 * Custom WebSocket hook with debouncing
 * @param {string} url - WebSocket URL
 * @param {number} debounceMs - Debounce interval in milliseconds (default 32ms ≈ 30Hz)
 * @returns {Object} WebSocket state and methods
 */
export function useWebSocket(url, debounceMs = 32) {
  const [status, setStatus] = useState(WS_STATES.DISCONNECTED);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const wsRef = useRef(null);
  const debounceTimerRef = useRef(null);
  const pendingDataRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const maxReconnectAttemptsRef = useRef(5);

  /**
   * Connect to WebSocket with automatic reconnection
   */
  const connect = useCallback(() => {
    if (!url) return;

    setStatus(WS_STATES.CONNECTING);
    setError(null);

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setStatus(WS_STATES.CONNECTED);
        reconnectAttemptRef.current = 0;
        console.log('[WebSocket] Connected');
      };

      ws.onmessage = (event) => {
        // Buffer incoming data
        pendingDataRef.current = JSON.parse(event.data);

        // Debounce state updates
        if (debounceTimerRef.current) {
          clearTimeout(debounceTimerRef.current);
        }

        debounceTimerRef.current = setTimeout(() => {
          if (pendingDataRef.current) {
            setData(pendingDataRef.current);
            pendingDataRef.current = null;
          }
        }, debounceMs);
      };

      ws.onerror = (err) => {
        setStatus(WS_STATES.ERROR);
        setError('WebSocket connection error');
        console.error('[WebSocket] Error:', err);
      };

      ws.onclose = () => {
        setStatus(WS_STATES.DISCONNECTED);

        // Attempt automatic reconnection with backoff
        if (reconnectAttemptRef.current < maxReconnectAttemptsRef.current) {
          reconnectAttemptRef.current += 1;
          const delay = Math.pow(2, reconnectAttemptRef.current) * 1000;
          console.log(
            `[WebSocket] Attempting reconnection in ${delay}ms (attempt ${reconnectAttemptRef.current})`
          );
          setTimeout(connect, delay);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      setStatus(WS_STATES.ERROR);
      setError('Failed to create WebSocket connection');
      console.error('[WebSocket] Creation failed:', err);
    }
  }, [url, debounceMs]);

  /**
   * Disconnect WebSocket
   */
  const disconnect = useCallback(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }

    setStatus(WS_STATES.DISCONNECTED);
  }, []);

  /**
   * Send message through WebSocket
   */
  const send = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    data,
    error,
    send,
    reconnect: connect,
  };
}

export default useWebSocket;
