import { useStore } from '../store/useStore.js';
import { getStoredAccessToken } from '../utils/authStorage.js';
import { LATENCY_MAX_MS, LATENCY_OVERLOAD_MS } from './requestGate.js';

const trimTrailingSlash = (value) => String(value || '').trim().replace(/\/$/, '');

const toWsOrigin = (value) => String(value || '').replace(/^http/i, 'ws');

const normalizeWsPath = (value) => {
  const path = String(value || '').trim();
  if (!path || path === '/') return '/ws';
  if (path === '/ws/v1') return '/ws';
  return path;
};

const resolveWebSocketUrl = () => {
  const envWsUrl = String(import.meta.env.VITE_WS_URL || '').trim();
  const envApiBase = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || '');
  const browserOrigin = typeof window !== 'undefined' ? trimTrailingSlash(window.location.origin) : '';

  if (envWsUrl) {
    try {
      const parsed = new URL(envWsUrl.startsWith('/') && browserOrigin
        ? `${toWsOrigin(browserOrigin)}${normalizeWsPath(envWsUrl)}`
        : envWsUrl);
      parsed.protocol = parsed.protocol.replace(/^http/i, 'ws');
      parsed.pathname = normalizeWsPath(parsed.pathname);
      return parsed.toString();
    } catch {
      // ignore and fallback below
    }
  }

  const base = envApiBase
    ? (envApiBase.startsWith('/')
      ? `${browserOrigin || 'http://localhost:8000'}${envApiBase}`
      : envApiBase)
    : (browserOrigin || 'http://localhost:8000');
  try {
    const parsed = new URL(base);
    parsed.protocol = parsed.protocol.replace(/^http/i, 'ws');
    parsed.pathname = '/ws';
    parsed.search = '';
    return parsed.toString();
  } catch {
    return 'ws://localhost:8000/ws';
  }
};

const parseTimestampMs = (value, fallback = Date.now()) => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? Math.floor(value) : Math.floor(value * 1000);
  }

  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric > 1e12 ? Math.floor(numeric) : Math.floor(numeric * 1000);
  }

  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : fallback;
};

export class WSManager {
  constructor() { 
    this.ws = null; 
    this.reconnectAttempts = 0; 
    this.maxReconnectAttempts = 10; 
    this.reconnectBaseMs = 1000;
    this.reconnectDelayMs = this.reconnectBaseMs;
    this.reconnectMaxMs = 30000;
    this.reconnectJitterMs = 400;
    this.pingInterval = null; 
    this.reconnectTimer = null;
    this.fallbackPollTimer = null;
    this.fallbackPollIntervalMs = 4000;
    this.fallbackReason = null;
    this.subscribedSymbols = new Set(); 
    this.manualClose = false;
    this.lastDataTimestampMs = 0;
    this.lastHeartbeatTimestampMs = 0;
    this.connectedAtMs = 0;
    this.healthCheckMs = 2000;
    this.noDataTimeoutMs = 8000;
  }
  
  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    const token = getStoredAccessToken();
    if (!token) {
      useStore.getState().setConnectionStatus('DISCONNECTED');
      useStore.getState().markRealtimeStale(null, 'NO LIVE DATA');
      return;
    }

    useStore.getState().setConnectionStatus('CONNECTING');

    const selectedSymbol = String(useStore.getState().selectedSymbol || 'RELIANCE').toUpperCase();
    if (selectedSymbol) {
      this.subscribedSymbols.add(selectedSymbol);
    }

    const wsUrl = resolveWebSocketUrl();
    const separator = wsUrl.includes('?') ? '&' : '?';
    this.manualClose = false;
    this.ws = new WebSocket(`${wsUrl}${separator}token=${encodeURIComponent(token)}`);
    
    this.ws.onopen = () => { 
      this.reconnectAttempts = 0; 
      this.reconnectDelayMs = this.reconnectBaseMs;
      this.lastDataTimestampMs = 0;
      this.lastHeartbeatTimestampMs = Date.now();
      this.connectedAtMs = this.lastHeartbeatTimestampMs;
      this.stopFallbackPolling();
      this.startHeartbeat(); 
      this.flushSubscriptions(); 
      useStore.getState().setConnectionStatus('CONNECTED'); 

      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log('[WS] connected:', wsUrl);
      }
    };
    
    this.ws.onmessage = this.handleMessage.bind(this);
    
    this.ws.onclose = () => { 
      this.stopHeartbeat(); 
      useStore.getState().setConnectionStatus('DISCONNECTED'); 
      useStore.getState().markRealtimeStale(null, 'NO LIVE DATA');
      if (!this.manualClose) {
        this.startFallbackPolling('ws_closed');
        this.attemptReconnect(); 
      }
    };
    
    this.ws.onerror = (err) => {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.error('[WS] error:', err);
      }
      this.startFallbackPolling('ws_error');
    };
  }
  
  handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    const receivedAtMs = Date.now();

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[WS] message:', payload);
    }

    const store = useStore.getState();
    switch (payload.type) {
      case 'tick': {
        this.lastDataTimestampMs = receivedAtMs;
        this.stopFallbackPolling();
        const tickTimestamp = payload.timestamp
          ?? payload.ts
          ?? payload.exchange_timestamp
          ?? payload.last_trade_time
          ?? Date.now();
        const tickTimestampMs = parseTimestampMs(tickTimestamp, Date.now());
        const latencyMs = Math.max(0, Date.now() - tickTimestampMs);

        if (latencyMs > LATENCY_OVERLOAD_MS) {
          store.resetRealtimeState(`OVERLOAD: live tick latency ${Math.round(latencyMs)}ms`);
          this.forceReconnect('latency_overload');
          return;
        }

        if (latencyMs > LATENCY_MAX_MS) {
          store.markRealtimeStale(latencyMs, 'NO LIVE DATA');
          return;
        }

        store.updateAssetPrice(payload.symbol, payload.ltp ?? payload.price, {
          timestamp: tickTimestampMs,
          dataSource: 'WS',
          latencyMs,
        });
        break;
      }
      case 'candle_update': {
        this.lastDataTimestampMs = receivedAtMs;
        this.stopFallbackPolling();
        store.upsertLiveCandle(payload.symbol, payload);
        break;
      }
      case 'signal_update': {
        this.lastDataTimestampMs = receivedAtMs;
        this.stopFallbackPolling();
        store.upsertLiveSignal(payload);
        break;
      }
      case 'status': {
        store.setConnectionStatus(payload.connected ? 'CONNECTED' : 'DISCONNECTED');
        if (!payload.connected) {
          store.markRealtimeStale(null, 'NO LIVE DATA');
          this.startFallbackPolling('ws_status');
        } else {
          this.stopFallbackPolling();
        }
        if (!payload.connected && payload.detail) {
          store.setSystemAlert(payload.detail);
        }
        break;
      }
      case 'subscribed': {
        const accepted = Array.isArray(payload.symbols) ? payload.symbols : [];
        const rejected = Array.isArray(payload.rejected_symbols) ? payload.rejected_symbols : [];

        if (rejected.length > 0) {
          store.setSystemAlert(`WS unsupported symbols: ${rejected.join(', ')}`);
          if (accepted.length === 0) {
            store.markRealtimeStale(null, 'NO LIVE DATA');
          }
        }
        break;
      }
      case 'error': {
        if (payload.message) {
          store.setSystemAlert(payload.message);
        }
        break;
      }
      case 'connected':
      case 'unsubscribed':
      case 'heartbeat':
        this.lastHeartbeatTimestampMs = receivedAtMs;
        break;
      case 'pong':
        this.lastHeartbeatTimestampMs = receivedAtMs;
        break;
      default:
        break;
    }
  }

  startFallbackPolling(reason = 'ws_fallback') {
    if (this.fallbackPollTimer) {
      return;
    }

    this.fallbackReason = reason;

    const poll = () => {
      const state = useStore.getState();
      const symbol = String(state.selectedSymbol || '').trim().toUpperCase();
      const timeframe = String(state.selectedTimeframe || '1m').trim().toLowerCase();
      if (!symbol) return;
      state.loadSymbolBundle(symbol, timeframe, { skipIfLoading: true });
    };

    poll();
    this.fallbackPollTimer = setInterval(poll, this.fallbackPollIntervalMs);
  }

  stopFallbackPolling() {
    if (!this.fallbackPollTimer) return;
    clearInterval(this.fallbackPollTimer);
    this.fallbackPollTimer = null;
    this.fallbackReason = null;
  }
  
  subscribeSymbol(symbol) {
    const normalized = String(symbol || '').trim().toUpperCase();
    if (!normalized) return;

    this.subscribedSymbols.add(normalized);
    this.flushSubscriptions();
  }
  
  unsubscribeSymbol(symbol) {
    const normalized = String(symbol || '').trim().toUpperCase();
    if (!normalized) return;

    this.subscribedSymbols.delete(normalized);

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'unsubscribe', symbols: [normalized] }));
    }
  }

  subscribe(symbolOrSymbols) {
    const items = Array.isArray(symbolOrSymbols) ? symbolOrSymbols : [symbolOrSymbols];
    items.forEach((item) => this.subscribeSymbol(item));
  }
  
  unsubscribe(symbolOrSymbols) {
    const items = Array.isArray(symbolOrSymbols) ? symbolOrSymbols : [symbolOrSymbols];
    items.forEach((item) => this.unsubscribeSymbol(item));
  }
  
  flushSubscriptions() {
    if (this.ws?.readyState !== WebSocket.OPEN) return;

    const symbols = [...this.subscribedSymbols];
    if (!symbols.length) return;

    this.ws.send(JSON.stringify({ action: 'subscribe', symbols }));
  }
  
  startHeartbeat() { 
    this.stopHeartbeat();
    this.pingInterval = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        return;
      }

      this.ws.send(JSON.stringify({ action: 'ping', ts: Date.now() }));

      const baselineMs = this.lastDataTimestampMs || this.connectedAtMs || Date.now();
      const silenceMs = Math.max(0, Date.now() - baselineMs);
      if (silenceMs > this.noDataTimeoutMs) {
        useStore.getState().markRealtimeStale(silenceMs, 'NO LIVE DATA');
        this.startFallbackPolling('no_data_timeout');
        this.forceReconnect('no_data_timeout');
      }
    }, this.healthCheckMs);
  }
  
  stopHeartbeat() {
    clearInterval(this.pingInterval);
    this.pingInterval = null;
  }

  forceReconnect(reason = 'reconnect') {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[WS] reconnect requested:', reason);
    }

    this.reconnectAttempts = 0;
    this.reconnectDelayMs = this.reconnectBaseMs;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      try {
        this.ws.close(4000, reason);
      } catch {
        // noop
      }
    } else {
      this.attemptReconnect();
    }
  }

  disconnect() {
    this.manualClose = true;
    this.stopHeartbeat();
    this.stopFallbackPolling();
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.reconnectAttempts = 0;
    this.reconnectDelayMs = this.reconnectBaseMs;

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.ws.close(1000, 'client_disconnect');
    }

    this.ws = null;
    useStore.getState().setConnectionStatus('DISCONNECTED');
    useStore.getState().markRealtimeStale(null, 'NO LIVE DATA');
  }
  
  attemptReconnect() { 
    if (this.manualClose) {
      return;
    }
    const token = getStoredAccessToken();
    if (!token) {
      useStore.getState().setConnectionStatus('DISCONNECTED');
      useStore.getState().markRealtimeStale(null, 'NO LIVE DATA');
      return;
    }

    if (this.reconnectTimer) {
      return;
    }

    if (this.reconnectAttempts < this.maxReconnectAttempts) { 
      this.reconnectAttempts++; 
      const jitter = Math.floor(Math.random() * this.reconnectJitterMs);
      const delay = Math.min(this.reconnectDelayMs, this.reconnectMaxMs) + jitter;
      useStore.getState().setConnectionStatus('RECONNECTING');
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, delay); 
      this.reconnectDelayMs = Math.min(
        Math.round(this.reconnectDelayMs * 1.6),
        this.reconnectMaxMs,
      );
    } else { 
      useStore.getState().setConnectionStatus('FAILED'); 
      useStore.getState().markRealtimeStale(null, 'NO LIVE DATA');
    } 
  }
}
export const wsManager = new WSManager();
