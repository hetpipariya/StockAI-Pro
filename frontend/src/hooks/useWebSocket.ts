/**
 * useWebSocket Hook
 * Manages WebSocket connection with automatic reconnection and exponential backoff
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { WS_RECONNECT_DELAY_MS, WS_MAX_RECONNECT_ATTEMPTS, STORAGE_KEYS } from '../utils/constants';

interface UseWebSocketOptions {
  /** WebSocket URL (absolute, not relative) */
  url: string;
  /** Callback when message is received */
  onMessage?: (data: any) => void;
  /** Callback when connection opens */
  onOpen?: () => void;
  /** Callback when connection closes */
  onClose?: () => void;
  /** Callback when error occurs */
  onError?: (error: Event) => void;
  /** Enable/disable the WebSocket connection */
  enabled?: boolean;
}

interface UseWebSocketReturn {
  /** Send message through WebSocket */
  send: (data: any) => void;
  /** Current connection status */
  isConnected: boolean;
  /** Reconnect manually */
  reconnect: () => void;
  /** Close connection */
  disconnect: () => void;
}

/**
 * WebSocket hook with automatic reconnection
 *
 * @param options - Configuration options
 * @returns Object with send function and connection status
 *
 * @example
 * ```tsx
 * const { send, isConnected } = useWebSocket({
 *   url: 'ws://localhost:8000/live?token=abc123',
 *   onMessage: (data) => console.log(data),
 *   onOpen: () => console.log('Connected'),
 *   enabled: true,
 * });
 *
 * if (isConnected) {
 *   send({ action: 'subscribe', symbol: 'RELIANCE' });
 * }
 * ```
 */
export function useWebSocket({
  url,
  onMessage,
  onOpen,
  onClose,
  onError,
  enabled = true,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  /**
   * Calculate reconnection delay with exponential backoff
   */
  const getReconnectDelay = useCallback((): number => {
    const delay = WS_RECONNECT_DELAY_MS * Math.pow(1.5, reconnectAttemptsRef.current);
    // Cap the delay at 30 seconds
    return Math.min(delay, 30000);
  }, []);

  /**
   * Connect to WebSocket
   */
  const connect = useCallback(() => {
    if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      // Construct WebSocket URL with auth token
      let wsUrl = url;

      // Add token to URL if not already present
      if (!wsUrl.includes('?') && !wsUrl.includes('token=')) {
        const accessToken = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
        if (accessToken) {
          const separator = wsUrl.includes('?') ? '&' : '?';
          wsUrl = `${wsUrl}${separator}token=${encodeURIComponent(accessToken)}`;
        }
      }

      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WebSocket] Connected:', url);
        reconnectAttemptsRef.current = 0;
        setIsConnected(true);
        onOpen?.();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage?.(data);
        } catch (error) {
          // If data is not JSON, pass it as is
          onMessage?.(event.data);
        }
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
        onError?.(error);
      };

      ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
        setIsConnected(false);
        onClose?.();

        // Attempt reconnection if enabled
        if (enabled && reconnectAttemptsRef.current < WS_MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1;
          const delay = getReconnectDelay();

          console.log(
            `[WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${WS_MAX_RECONNECT_ATTEMPTS})`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else if (enabled && reconnectAttemptsRef.current >= WS_MAX_RECONNECT_ATTEMPTS) {
          console.error('[WebSocket] Max reconnection attempts reached');
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error);
      setIsConnected(false);
    }
  }, [enabled, url, onMessage, onOpen, onClose, onError, getReconnectDelay]);

  /**
   * Send message through WebSocket
   */
  const send = useCallback(
    (data: any) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          const message = typeof data === 'string' ? data : JSON.stringify(data);
          wsRef.current.send(message);
        } catch (error) {
          console.error('[WebSocket] Send error:', error);
        }
      } else {
        console.warn('[WebSocket] Connection not ready. Current state:', wsRef.current?.readyState);
      }
    },
    []
  );

  /**
   * Manually reconnect
   */
  const reconnect = useCallback(() => {
    console.log('[WebSocket] Manual reconnect triggered');
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  /**
   * Disconnect WebSocket
   */
  const disconnect = useCallback(() => {
    console.log('[WebSocket] Disconnecting');
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
  }, []);

  /**
   * Effect: Connect/disconnect based on enabled flag
   */
  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      // Cleanup on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [enabled, connect, disconnect]);

  /**
   * Effect: Refresh token in WebSocket URL when token changes
   */
  useEffect(() => {
    const handleStorageChange = () => {
      // Token updated in localStorage, reconnect with new token
      if (enabled && wsRef.current?.readyState === WebSocket.OPEN) {
        reconnect();
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [enabled, reconnect]);

  return {
    send,
    isConnected,
    reconnect,
    disconnect,
  };
}

export type { UseWebSocketOptions, UseWebSocketReturn };
