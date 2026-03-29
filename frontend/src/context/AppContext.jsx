import React, { createContext, useContext, useMemo, useEffect, useState, useRef, useCallback } from 'react';
import { api, buildWebSocketUrl } from '../api/api';
import { useToast } from '../components/ui/Toast';
import { useAuth } from './AuthContext';

const AppContext = createContext();

const WATCHLIST_SYMBOLS = [
  'RELIANCE',
  'TCS',
  'INFY',
  'HDFCBANK',
  'ICICIBANK',
  'SBIN',
  'ITC',
  'TATASTEEL',
  'AXISBANK',
  'KOTAKBANK',
];

const normalizeTimeframe = (value) => {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return '1m';
  if (raw === '1h' || raw === '1d') return raw;
  if (/^\d+(m|h|d)$/.test(raw)) return raw;
  if (raw === '1m' || raw === '5m' || raw === '15m' || raw === '30m' || raw === '3m') return raw;
  return '1m';
};

const toNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const candleTimestampToSeconds = (value) => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? Math.floor(value / 1000) : Math.floor(value);
  }
  const ms = Date.parse(String(value || ''));
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000);
};

const mapWatchlistPrice = (snapshot = {}) => {
  const ltp = toNumber(snapshot.ltp, null);
  const close = toNumber(snapshot.close, ltp);
  const change = ltp != null && close != null ? ltp - close : null;
  const changePct = ltp != null && close != null && close !== 0 ? ((ltp - close) / close) * 100 : null;
  return {
    price: ltp,
    close,
    change,
    changePct,
  };
};

export const AppProvider = ({ children }) => {
  const { accessToken, isAuthenticated } = useAuth();
  const { showToast } = useToast();
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST_SYMBOLS[0]);
  const [selectedTimeframe, setSelectedTimeframe] = useState('1m');
  const [bundleData, setBundleData] = useState(null);
  const [signalData, setSignalData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSignalLoading, setIsSignalLoading] = useState(false);
  const [error, setError] = useState(null);
  const [signalError, setSignalError] = useState(null);
  const [watchlistPrices, setWatchlistPrices] = useState({});
  const [wsStatus, setWsStatus] = useState('disconnected');
  const [wsConnectionState, setWsConnectionState] = useState('DISCONNECTED');

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectBackoffRef = useRef(1000);
  const shouldReconnectRef = useRef(false);
  const manualCloseRef = useRef(false);
  const selectedSymbolRef = useRef(WATCHLIST_SYMBOLS[0]);
  const previousSymbolRef = useRef(WATCHLIST_SYMBOLS[0]);
  const bundleRequestIdRef = useRef(0);
  const signalRequestIdRef = useRef(0);

  const updateBundleFromTick = useCallback((tick) => {
    const ltp = toNumber(tick?.ltp, null);
    if (ltp == null) return;

    setBundleData((prev) => {
      if (!prev || String(prev.symbol || '').toUpperCase() !== selectedSymbolRef.current) {
        return prev;
      }

      const snapshot = {
        ...(prev.snapshot || {}),
        ltp,
        bid: toNumber(tick.bid, ltp),
        ask: toNumber(tick.ask, ltp),
        volume: toNumber(tick.volume, 0),
        data_source: tick.data_source || prev.snapshot?.data_source || 'UNKNOWN',
      };

      const sourceCandles = Array.isArray(prev.history?.candles) ? prev.history.candles : [];
      const candles = [...sourceCandles];
      const last = candles[candles.length - 1];
      if (last) {
        const close = toNumber(last.close, ltp);
        const high = toNumber(last.high, ltp);
        const low = toNumber(last.low, ltp);
        candles[candles.length - 1] = {
          ...last,
          close: ltp,
          high: Math.max(high, ltp),
          low: Math.min(low, ltp),
          volume: toNumber(tick.volume, toNumber(last.volume, 0)),
        };
      }

      return {
        ...prev,
        snapshot,
        history: {
          ...(prev.history || {}),
          candles,
        },
      };
    });

    setWatchlistPrices((prev) => {
      const existing = prev[selectedSymbolRef.current] || {};
      const close = toNumber(existing.close, ltp);
      return {
        ...prev,
        [selectedSymbolRef.current]: {
          ...existing,
          price: ltp,
          close,
          change: close != null ? ltp - close : 0,
          changePct: close ? ((ltp - close) / close) * 100 : 0,
        },
      };
    });

    setSignalData((prev) => {
      if (!prev) return prev;
      if (String(prev.symbol || '').toUpperCase() !== selectedSymbolRef.current) return prev;
      return {
        ...prev,
        currentPrice: ltp,
        prediction: ltp,
        timestamp: new Date().toISOString(),
      };
    });
  }, []);

  const updateBundleFromCandle = useCallback((message) => {
    if (!message) return;
    const timestamp = message.timestamp;
    if (!timestamp) return;

    const incoming = {
      time: timestamp,
      open: toNumber(message.open, null),
      high: toNumber(message.high, null),
      low: toNumber(message.low, null),
      close: toNumber(message.close, null),
      volume: toNumber(message.volume, 0),
    };

    if (incoming.open == null || incoming.high == null || incoming.low == null || incoming.close == null) {
      return;
    }

    setBundleData((prev) => {
      if (!prev || String(prev.symbol || '').toUpperCase() !== selectedSymbolRef.current) {
        return prev;
      }

      const sourceCandles = Array.isArray(prev.history?.candles) ? prev.history.candles : [];
      const map = new Map(sourceCandles.map((candle) => [String(candle.time), candle]));
      map.set(String(incoming.time), incoming);
      const merged = Array.from(map.values())
        .sort((a, b) => candleTimestampToSeconds(a.time) - candleTimestampToSeconds(b.time))
        .slice(-500);

      return {
        ...prev,
        history: {
          ...(prev.history || {}),
          candles: merged,
        },
      };
    });
  }, []);

  const fetchBundleData = useCallback(
    async (symbol, timeframe, isManualRefresh = false) => {
      const normalizedSymbol = String(symbol || '').trim().toUpperCase();
      const normalizedTimeframe = normalizeTimeframe(timeframe);
      const requestId = ++bundleRequestIdRef.current;

      setIsLoading(true);
      setError(null);

      try {
        const payload = await api.getBundle(normalizedSymbol, normalizedTimeframe, 200, '15m');
        if (requestId !== bundleRequestIdRef.current) return;
        setBundleData(payload);
        setWatchlistPrices((prev) => ({
          ...prev,
          [normalizedSymbol]: mapWatchlistPrice(payload?.snapshot || {}),
        }));
        if (isManualRefresh) {
          showToast(`Updated ${normalizedSymbol} (${normalizedTimeframe})`, 'success');
        }
      } catch (err) {
        if (requestId !== bundleRequestIdRef.current) return;
        const message = err?.message || 'Failed to load market bundle';
        setError(message);
        showToast(message, 'error');
      } finally {
        if (requestId === bundleRequestIdRef.current) {
          setIsLoading(false);
        }
      }
    },
    [showToast]
  );

  const fetchSignalData = useCallback(
    async (symbol, { showErrorToast = false } = {}) => {
      const normalizedSymbol = String(symbol || '').trim().toUpperCase();
      if (!normalizedSymbol) return;

      const requestId = ++signalRequestIdRef.current;
      setIsSignalLoading(true);
      setSignalError(null);

      try {
        const payload = await api.getPrediction(normalizedSymbol);
        if (requestId !== signalRequestIdRef.current) return;
        setSignalData(payload);
      } catch (err) {
        if (requestId !== signalRequestIdRef.current) return;
        const message = err?.message || 'Failed to load live signal';
        setSignalError(message);
        setSignalData(null);
        if (showErrorToast) {
          showToast(message, 'error');
        }
      } finally {
        if (requestId === signalRequestIdRef.current) {
          setIsSignalLoading(false);
        }
      }
    },
    [showToast]
  );

  useEffect(() => {
    selectedSymbolRef.current = selectedSymbol;
  }, [selectedSymbol]);

  useEffect(() => {
    fetchBundleData(selectedSymbol, selectedTimeframe, false);
    fetchSignalData(selectedSymbol, { showErrorToast: false });
  }, [fetchBundleData, fetchSignalData, selectedSymbol, selectedTimeframe]);

  const clearSocket = useCallback(() => {
    clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;

    if (wsRef.current) {
      manualCloseRef.current = true;
      try {
        wsRef.current.close();
      } catch (_) {
        // Ignore close errors.
      }
      wsRef.current = null;
    }
    manualCloseRef.current = false;
  }, []);

  const connectSocket = useCallback(() => {
    if (!accessToken) {
      setWsStatus(isAuthenticated ? 'error' : 'unauthenticated');
      return;
    }

    const wsUrl = buildWebSocketUrl(accessToken);
    if (!wsUrl) {
      setWsStatus('error');
      return;
    }

    setWsStatus('connecting');

    let ws;
    try {
      ws = new WebSocket(wsUrl);
    } catch (_) {
      setWsStatus('error');
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      reconnectBackoffRef.current = 1000;
      setWsStatus('open');
      setWsConnectionState('CONNECTED');
      const symbol = selectedSymbolRef.current;
      if (symbol) {
        ws.send(JSON.stringify({ action: 'subscribe', symbols: [symbol] }));
      }
    };

    ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (!message || typeof message !== 'object') return;

      if (typeof message.connection_state === 'string') {
        setWsConnectionState(message.connection_state);
      }

      if (message.type === 'tick') {
        const symbol = String(message.symbol || '').toUpperCase();
        if (symbol !== selectedSymbolRef.current) return;
        updateBundleFromTick(message);
        return;
      }

      if (message.type === 'candle_update') {
        const symbol = String(message.symbol || '').toUpperCase();
        if (symbol !== selectedSymbolRef.current) return;
        updateBundleFromCandle(message);
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (manualCloseRef.current) {
        setWsStatus('closed');
        return;
      }

      if (!shouldReconnectRef.current) {
        setWsStatus('closed');
        return;
      }

      setWsStatus('reconnecting');
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = setTimeout(() => {
        reconnectBackoffRef.current = Math.min(reconnectBackoffRef.current * 1.8, 15000);
        connectSocket();
      }, reconnectBackoffRef.current);
    };

    ws.onerror = () => {
      setWsStatus('error');
      try {
        ws.close();
      } catch (_) {
        // Ignore close errors.
      }
    };
  }, [accessToken, isAuthenticated, updateBundleFromTick, updateBundleFromCandle]);

  useEffect(() => {
    shouldReconnectRef.current = true;
    clearSocket();
    connectSocket();

    return () => {
      shouldReconnectRef.current = false;
      clearSocket();
    };
  }, [clearSocket, connectSocket]);

  useEffect(() => {
    const ws = wsRef.current;
    const nextSymbol = String(selectedSymbol || '').toUpperCase();
    if (!ws || ws.readyState !== WebSocket.OPEN || !nextSymbol) {
      previousSymbolRef.current = nextSymbol;
      return;
    }

    const previous = previousSymbolRef.current;
    if (previous && previous !== nextSymbol) {
      ws.send(JSON.stringify({ action: 'unsubscribe', symbols: [previous] }));
    }
    ws.send(JSON.stringify({ action: 'subscribe', symbols: [nextSymbol] }));
    previousSymbolRef.current = nextSymbol;
  }, [selectedSymbol]);

  const selectSymbol = useCallback((symbol) => {
    const next = String(symbol || '').trim().toUpperCase();
    if (!next || next === selectedSymbol) return;
    setSelectedSymbol(next);
  }, [selectedSymbol]);

  const selectTimeframe = useCallback((tf) => {
    setSelectedTimeframe(normalizeTimeframe(tf));
  }, []);

  const refreshBundle = useCallback(() => {
    fetchBundleData(selectedSymbol, selectedTimeframe, true);
    fetchSignalData(selectedSymbol, { showErrorToast: true });
  }, [fetchBundleData, fetchSignalData, selectedSymbol, selectedTimeframe]);

  const refreshSignal = useCallback(() => {
    fetchSignalData(selectedSymbol, { showErrorToast: true });
  }, [fetchSignalData, selectedSymbol]);

  const candles = useMemo(() => {
    const rows = Array.isArray(bundleData?.history?.candles) ? bundleData.history.candles : [];
    return rows
      .map((row) => {
        const time = candleTimestampToSeconds(row.time);
        const open = toNumber(row.open, null);
        const high = toNumber(row.high, null);
        const low = toNumber(row.low, null);
        const close = toNumber(row.close, null);
        if (time == null || open == null || high == null || low == null || close == null) {
          return null;
        }
        return { time, open, high, low, close };
      })
      .filter(Boolean);
  }, [bundleData]);

  const snapshot = useMemo(() => bundleData?.snapshot || null, [bundleData]);

  const indicators = useMemo(() => bundleData?.indicators || {}, [bundleData]);

  const currentSignal = useMemo(() => {
    if (signalData) {
      const currentPrice = toNumber(signalData.currentPrice, toNumber(snapshot?.ltp, 0));
      return {
        symbol: String(signalData.symbol || selectedSymbol),
        signal: String(signalData.signal || 'HOLD').toUpperCase(),
        confidence: toNumber(signalData.confidence, 0),
        target: toNumber(signalData.target, currentPrice),
        stopLoss: toNumber(signalData.stopLoss, currentPrice),
        currentPrice,
        timestamp: signalData.timestamp || new Date().toISOString(),
        regime: signalData.regime || 'Unknown',
        explanation: signalData.explanation || '',
        modelVersion: toNumber(signalData.modelVersion, 0),
      };
    }

    if (isSignalLoading || signalError) {
      return null;
    }

    const prediction = bundleData?.prediction;
    if (!prediction) return null;
    const currentPrice = toNumber(snapshot?.ltp, toNumber(prediction.prediction, 0));
    return {
      symbol: String(bundleData?.symbol || selectedSymbol),
      signal: String(prediction.signal || 'HOLD').toUpperCase(),
      confidence: toNumber(prediction.confidence, 0),
      target: toNumber(prediction.target_price, 0),
      stopLoss: toNumber(prediction.stop_loss, 0),
      currentPrice,
      timestamp: new Date().toISOString(),
      regime: prediction.regime || 'Unknown',
      explanation: prediction.explanation || '',
    };
  }, [bundleData, isSignalLoading, selectedSymbol, signalData, signalError, snapshot]);

  const prices = useMemo(() => {
    return WATCHLIST_SYMBOLS.reduce((acc, symbol) => {
      acc[symbol] = watchlistPrices[symbol] || {
        price: null,
        close: null,
        change: null,
        changePct: null,
      };
      return acc;
    }, {});
  }, [watchlistPrices]);

  return (
    <AppContext.Provider value={{
      selectedSymbol,
      selectedTimeframe,
      bundleData,
      snapshot,
      candles,
      indicators,
      currentSignal,
      prices,
      watchlistSymbols: WATCHLIST_SYMBOLS,
      isLoading,
      isSignalLoading,
      error,
      signalError,
      wsStatus,
      wsConnectionState,
      selectSymbol,
      selectTimeframe,
      refreshBundle,
      refreshSignal,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppContext must be used within AppProvider');
  return context;
};
