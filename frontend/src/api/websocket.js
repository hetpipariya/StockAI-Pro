import { useStore } from '../store/useStore.js';

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

export class WSManager {
  constructor() { 
    this.ws = null; 
    this.reconnectAttempts = 0; 
    this.maxReconnectAttempts = 5; 
    this.pingInterval = null; 
    this.subscribedSymbols = new Set(); 
    this.manualClose = false;
  }
  
  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    const token = localStorage.getItem('access_token');
    if (!token) {
      useStore.getState().setConnectionStatus('DISCONNECTED');
      return;
    }

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
      if (!this.manualClose) {
        this.attemptReconnect(); 
      }
    };
    
    this.ws.onerror = (err) => {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.error('[WS] error:', err);
      }
    };
  }
  
  handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[WS] message:', payload);
    }

    const store = useStore.getState();
    switch (payload.type) {
      case 'tick': {
        store.updateAssetPrice(payload.symbol, payload.ltp ?? payload.price);
        break;
      }
      case 'candle_update': {
        store.upsertLiveCandle(payload.symbol, payload);
        break;
      }
      case 'signal_update': {
        store.upsertLiveSignal(payload);
        break;
      }
      case 'status': {
        store.setConnectionStatus(payload.connected ? 'CONNECTED' : 'DISCONNECTED');
        if (!payload.connected && payload.detail) {
          store.setSystemAlert(payload.detail);
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
      case 'subscribed':
      case 'unsubscribed':
      case 'heartbeat':
      case 'pong':
      default:
        break;
    }
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
    this.pingInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'ping' }));
      }
    }, 30000);
  }
  
  stopHeartbeat() { clearInterval(this.pingInterval); }

  disconnect() {
    this.manualClose = true;
    this.stopHeartbeat();
    this.reconnectAttempts = 0;

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.ws.close(1000, 'client_disconnect');
    }

    this.ws = null;
    useStore.getState().setConnectionStatus('DISCONNECTED');
  }
  
  attemptReconnect() { 
    const token = localStorage.getItem('access_token');
    if (!token) {
      useStore.getState().setConnectionStatus('DISCONNECTED');
      return;
    }

    if (this.reconnectAttempts < this.maxReconnectAttempts) { 
      this.reconnectAttempts++; 
      setTimeout(() => this.connect(), Math.pow(2, this.reconnectAttempts) * 1000); 
    } else { 
      useStore.getState().setConnectionStatus('FAILED'); 
    } 
  }
}
export const wsManager = new WSManager();