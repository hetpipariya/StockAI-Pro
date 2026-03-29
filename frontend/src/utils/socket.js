/**
 * @file socket.js
 * WebSocket manager for real-time data connections.
 * 
 * Features:
 * - Singleton pattern per URL
 * - Auto-reconnect with exponential backoff
 * - Connection state management
 * - Symbol subscription management
 * - Heartbeat handling
 * - Tick message throttling
 */

import { buildLiveWebSocketUrl } from '../config/api';

// Store for WebSocket managers (singleton per URL)
const managers = new Map();

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

// Tick throttle interval (ms)
const TICK_THROTTLE_MS = 32;

/**
 * WebSocket connection manager class.
 * Handles connection lifecycle, reconnection, and message routing.
 */
class SocketManager {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.authToken = null;
    this.refCount = 0;
    this.shouldReconnect = false;
    this.reconnectTimer = null;
    this.connectTimer = null;
    this.backoffMs = INITIAL_BACKOFF_MS;
    this.maxBackoffMs = MAX_BACKOFF_MS;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = MAX_RECONNECT_ATTEMPTS;
    this.reconnectableCloseCodes = RECONNECTABLE_CLOSE_CODES;
    this.subscriptions = new Set();
    this.messageListeners = new Set();
    this.connectionListeners = new Set();
    this.pendingTick = null;
    this.tickFlushTimer = null;
    this.connectionState = 'DISCONNECTED';
  }

  /**
   * Get current connection state.
   */
  getState() {
    return this.connectionState;
  }

  /**
   * Check if connected.
   */
  isConnected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Notify all connection listeners of state change.
   */
  notifyConnection(isConnected) {
    this.connectionState = isConnected ? 'CONNECTED' : 'DISCONNECTED';
    this.connectionListeners.forEach((listener) => {
      try {
        listener(isConnected, this.connectionState);
      } catch (error) {
        console.warn('[SocketManager] Connection listener error:', error);
      }
    });
  }

  /**
   * Notify all message listeners of new message.
   */
  notifyMessage(message) {
    this.messageListeners.forEach((listener) => {
      try {
        listener(message);
      } catch (error) {
        console.warn('[SocketManager] Message listener error:', error);
      }
    });
  }

  /**
   * Flush pending tick message (throttled).
   */
  flushTick() {
    this.tickFlushTimer = null;
    if (!this.pendingTick) return;
    this.notifyMessage(this.pendingTick);
    this.pendingTick = null;
  }

  /**
   * Schedule a reconnection attempt with exponential backoff.
   */
  scheduleReconnect() {
    if (!this.shouldReconnect) return;

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[SocketManager] Max reconnection attempts reached');
      this.connectionState = 'ERROR';
      return;
    }
    
    clearTimeout(this.reconnectTimer);
    const delay = this.backoffMs;
    this.reconnectAttempts += 1;
    
    console.log(`[SocketManager] Scheduling reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
    this.connectionState = 'RECONNECTING';
    
    this.reconnectTimer = setTimeout(() => {
      if (!this.shouldReconnect) return;
      this.backoffMs = Math.min(
        Math.round(this.backoffMs * BACKOFF_MULTIPLIER),
        this.maxBackoffMs
      );
      this.connect();
    }, delay);
  }

  /**
   * Connect to the WebSocket server.
   */
  connect() {
    if (!this.url) {
      console.error('[SocketManager] No URL configured');
      return;
    }

    // Don't connect if already connected or connecting
    if (this.ws?.readyState === WebSocket.OPEN || 
        this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    console.log('[SocketManager] Connecting to:', this.url.replace(/token=[^&]+/, 'token=***'));
    this.connectionState = 'CONNECTING';

    let socket = null;
    try {
      socket = new WebSocket(this.url);
      this.ws = socket;
    } catch (error) {
      console.error('[SocketManager] Failed to create WebSocket:', error);
      this.scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      if (this.ws !== socket) return;
      
      console.log('[SocketManager] Connected successfully');
      this.backoffMs = INITIAL_BACKOFF_MS;
      this.reconnectAttempts = 0;
      this.notifyConnection(true);
      
      // Send authentication if token is set
      this.sendAuth();
      
      // Resubscribe to all symbols
      if (this.subscriptions.size > 0) {
        this.send({ 
          action: 'subscribe', 
          symbols: Array.from(this.subscriptions) 
        });
        console.log('[SocketManager] Resubscribed to:', Array.from(this.subscriptions));
      }
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      
      try {
        const msg = JSON.parse(event.data);
        if (!msg || typeof msg !== 'object') return;

        // Handle heartbeat
        if (msg.type === 'heartbeat') {
          this.send({ action: 'pong' });
          return;
        }

        // Throttle tick messages to prevent UI overload
        if (msg.type === 'tick') {
          this.pendingTick = msg;
          if (!this.tickFlushTimer) {
            this.tickFlushTimer = setTimeout(
              () => this.flushTick(),
              TICK_THROTTLE_MS
            );
          }
          return;
        }

        // Forward all other messages immediately
        this.notifyMessage(msg);
      } catch (error) {
        console.warn('[SocketManager] Failed to parse message:', error);
      }
    };

    socket.onclose = (event) => {
      if (this.ws === socket) {
        this.ws = null;
      }
      
      console.log('[SocketManager] Connection closed:', {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
      });
      
      this.notifyConnection(false);
      
      // Attempt reconnection for recoverable close codes
      if (this.shouldReconnect && 
          (this.reconnectableCloseCodes.has(event.code) || !event.wasClean)) {
        this.scheduleReconnect();
      }
    };

    socket.onerror = (error) => {
      if (this.ws !== socket) return;
      
      console.error('[SocketManager] WebSocket error:', error);
      this.connectionState = 'ERROR';
      
      try {
        socket.close();
      } catch (closeError) {
        console.warn('[SocketManager] Error closing socket:', closeError);
        this.scheduleReconnect();
      }
    };
  }

  /**
   * Attach a consumer (increment reference count and connect).
   */
  attach() {
    this.refCount += 1;
    this.shouldReconnect = true;
    
    clearTimeout(this.connectTimer);
    this.connectTimer = setTimeout(() => this.connect(), 40);
  }

  /**
   * Detach a consumer (decrement reference count and disconnect if zero).
   */
  detach() {
    this.refCount = Math.max(0, this.refCount - 1);
    if (this.refCount > 0) return;

    this.shouldReconnect = false;
    clearTimeout(this.connectTimer);
    clearTimeout(this.reconnectTimer);
    clearTimeout(this.tickFlushTimer);
    this.tickFlushTimer = null;
    this.pendingTick = null;

    if (this.ws) {
      const socket = this.ws;
      this.ws = null;
      socket.onclose = null;
      try {
        socket.close(1000, 'Client detach');
      } catch (error) {
        // Ignore close errors
      }
    }

    this.notifyConnection(false);
  }

  /**
   * Register a message listener.
   * @returns {Function} Unsubscribe function
   */
  onMessage(listener) {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  /**
   * Register a connection state listener.
   * @returns {Function} Unsubscribe function
   */
  onConnection(listener) {
    this.connectionListeners.add(listener);
    return () => this.connectionListeners.delete(listener);
  }

  /**
   * Send a message to the server.
   * @returns {boolean} True if message was sent
   */
  send(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    
    try {
      this.ws.send(JSON.stringify(payload));
      return true;
    } catch (error) {
      console.warn('[SocketManager] Failed to send message:', error);
      return false;
    }
  }

  /**
   * Set authentication token.
   */
  setAuthToken(token) {
    this.authToken = typeof token === 'string' && token.trim() 
      ? token.trim() 
      : null;
    this.sendAuth();
  }

  /**
   * Send authentication message.
   */
  sendAuth() {
    if (!this.authToken) return false;
    return this.send({ action: 'auth', token: this.authToken });
  }

  /**
   * Subscribe to symbols.
   */
  subscribe(symbols) {
    const safe = Array.isArray(symbols)
      ? symbols
          .filter((symbol) => typeof symbol === 'string' && symbol.trim())
          .map((symbol) => symbol.trim().toUpperCase())
      : [];
    
    safe.forEach((symbol) => this.subscriptions.add(symbol));
    
    if (safe.length > 0) {
      this.send({ action: 'subscribe', symbols: safe });
      console.log('[SocketManager] Subscribed to:', safe);
    }
  }

  /**
   * Unsubscribe from symbols.
   */
  unsubscribe(symbols) {
    const safe = Array.isArray(symbols)
      ? symbols
          .filter((symbol) => typeof symbol === 'string' && symbol.trim())
          .map((symbol) => symbol.trim().toUpperCase())
      : [];
    
    safe.forEach((symbol) => this.subscriptions.delete(symbol));
    
    if (safe.length > 0) {
      this.send({ action: 'unsubscribe', symbols: safe });
      console.log('[SocketManager] Unsubscribed from:', safe);
    }
  }

  /**
   * Check if subscribed to a symbol.
   */
  isSubscribed(symbol) {
    return this.subscriptions.has(String(symbol || '').toUpperCase());
  }

  /**
   * Force reconnection.
   */
  reconnect() {
    this.backoffMs = INITIAL_BACKOFF_MS;
    this.reconnectAttempts = 0;
    
    if (this.ws) {
      const socket = this.ws;
      this.ws = null;
      socket.onclose = null;
      try {
        socket.close(1000, 'Force reconnect');
      } catch (error) {
        // Ignore close errors
      }
    }
    
    this.connect();
  }
}

/**
 * Get or create a SocketManager for the given URL.
 * @param {string} [url] - WebSocket URL (defaults to configured live URL)
 * @returns {SocketManager} Socket manager instance
 */
export const getSocketManager = (url = buildLiveWebSocketUrl()) => {
  if (!url) {
    console.error('[SocketManager] No WebSocket URL provided');
    return null;
  }
  
  if (!managers.has(url)) {
    managers.set(url, new SocketManager(url));
  }
  return managers.get(url);
};

/**
 * Get the default socket manager using configured WS_URL.
 * @returns {SocketManager} Default socket manager instance
 */
export const getDefaultSocketManager = () => getSocketManager(buildLiveWebSocketUrl());

export default SocketManager;
