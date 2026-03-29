import { useCallback, useEffect, useRef, useState } from 'react';
import { buildWebSocketUrl, getStoredAccessToken } from '../api/api';

const toNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

export function useWebSocket(symbol, enabled = true) {
  const [livePrice, setLivePrice] = useState(null);
  const [priceChange, setPriceChange] = useState(null);
  const [changePct, setChangePct] = useState(null);
  const [wsStatus, setWsStatus] = useState('disconnected');

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const backoffRef = useRef(1000);
  const previousSymbolRef = useRef('');
  const selectedSymbol = String(symbol || '').trim().toUpperCase();

  const connect = useCallback(() => {
    if (!enabled || !selectedSymbol) return;

    const token = getStoredAccessToken();
    const wsUrl = buildWebSocketUrl(token);
    if (!wsUrl) {
      setWsStatus('unauthenticated');
      return;
    }

    setWsStatus('connecting');

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('open');
      backoffRef.current = 1000;
      ws.send(JSON.stringify({ action: 'subscribe', symbols: [selectedSymbol] }));
      previousSymbolRef.current = selectedSymbol;
    };

    ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (!message || typeof message !== 'object') return;

      if (message.type !== 'tick' || String(message.symbol || '').toUpperCase() !== selectedSymbol) {
        return;
      }

      const ltp = toNumber(message.ltp, null);
      if (ltp == null) return;

      setLivePrice((prev) => {
        if (prev == null) return ltp;
        const delta = ltp - prev;
        setPriceChange(delta);
        setChangePct(prev !== 0 ? (delta / prev) * 100 : 0);
        return ltp;
      });
    };

    ws.onclose = () => {
      wsRef.current = null;
      setWsStatus('reconnecting');
      clearTimeout(reconnectRef.current);
      reconnectRef.current = setTimeout(() => {
        backoffRef.current = Math.min(backoffRef.current * 1.8, 15000);
        connect();
      }, backoffRef.current);
    };

    ws.onerror = () => {
      setWsStatus('error');
      try {
        ws.close();
      } catch (_) {
        // ignore
      }
    };
  }, [enabled, selectedSymbol]);

  useEffect(() => {
    clearTimeout(reconnectRef.current);
    setLivePrice(null);
    setPriceChange(null);
    setChangePct(null);

    connect();

    return () => {
      clearTimeout(reconnectRef.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onclose = null;
        try {
          if (previousSymbolRef.current) {
            ws.send(JSON.stringify({ action: 'unsubscribe', symbols: [previousSymbolRef.current] }));
          }
        } catch (_) {
          // ignore
        }
        try {
          ws.close();
        } catch (_) {
          // ignore
        }
      }
    };
  }, [connect]);

  return { livePrice, priceChange, changePct, wsStatus };
}

export const useWebsocket = useWebSocket;
