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

const WS_MAX_RECONNECT_ATTEMPTS = 10;

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

const normalizeConfidencePct = (value, fallback = 0) => {
  const raw = toNumber(value, null);
  if (raw == null) return fallback;
  const pct = raw <= 1 ? raw * 100 : raw;
  return Math.max(0, Math.min(100, pct));
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
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(false);
  const manualCloseRef = useRef(false);
  const selectedSymbolRef = useRef(WATCHLIST_SYMBOLS[0]);
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

  const updateWatchlistFromTick = useCallback((symbol, tick) => {
    const normalizedSymbol = String(symbol || '').toUpperCase();
    if (!normalizedSymbol) return;

    const ltp = toNumber(tick?.ltp, null);
    if (ltp == null) return;

    setWatchlistPrices((prev) => {
      const existing = prev[normalizedSymbol] || {};
      const close = toNumber(existing.close, ltp);
      return {
        ...prev,
        [normalizedSymbol]: {
          ...existing,
          price: ltp,
          close,
          change: close != null ? ltp - close : 0,
          changePct: close ? ((ltp - close) / close) * 100 : 0,
        },
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
        const payload = await api.getBundle(normalizedSymbol, normalizedTimeframe, 100, '15m');
        if (requestId !== bundleRequestIdRef.current) return;
        setBundleData(payload);
        const bundledPrediction = payload?.prediction;
        if (bundledPrediction && typeof bundledPrediction === 'object') {
          setSignalData({
            symbol: normalizedSymbol,
            signal: bundledPrediction.signal,
            confidence: normalizeConfidencePct(
              bundledPrediction.confidence,
              toNumber(bundledPrediction.confidence_pct, 0)
            ),
            momentumScore: toNumber(bundledPrediction.momentum_score, 50),
            trendScore: toNumber(bundledPrediction.trend_score, 50),
            volatilityScore: toNumber(bundledPrediction.volatility_score, 50),
            volatilityState: bundledPrediction.volatility_state || 'MISSING',
            volumeScore: toNumber(bundledPrediction.volume_score, 50),
            volumeRatio: toNumber(bundledPrediction.volume_ratio, 1),
            volumeRatioFlag: bundledPrediction.volume_ratio_flag || 'NORMAL',
            volumeSpike: Boolean(bundledPrediction.volume_spike),
            volumeSpikeStrength: toNumber(bundledPrediction.volume_spike_strength, 0),
            vwapDeviation: toNumber(bundledPrediction.vwap_deviation, 0),
            vwapBias: bundledPrediction.vwap_bias || 'NEUTRAL',
            obvSlope: toNumber(bundledPrediction.obv_slope, 0),
            obvDivergence: Boolean(bundledPrediction.obv_divergence),
            volumeTrendSlope: toNumber(bundledPrediction.volume_trend_slope, 0),
            volumeTrendDirection: bundledPrediction.volume_trend_direction || 'FLAT',
            positionSizeFactor: toNumber(bundledPrediction.position_size_factor, 0.75),
            mtfAlignment: bundledPrediction.mtf_alignment || 'NEUTRAL',
            emaStructure: bundledPrediction.ema_structure || 'MIXED STACK',
            currentPrice: payload?.snapshot?.ltp,
            target: bundledPrediction.target_price,
            stopLoss: bundledPrediction.stop_loss,
            regime: bundledPrediction.regime,
            reason: bundledPrediction.reason || bundledPrediction.explanation,
            explanation: bundledPrediction.explanation,
            timestamp: new Date().toISOString(),
          });
          setSignalError(null);
        }
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

  useEffect(() => {
    selectedSymbolRef.current = selectedSymbol;
  }, [selectedSymbol]);

  useEffect(() => {
    fetchBundleData(selectedSymbol, selectedTimeframe, false);

    const pollId = setInterval(() => {
      fetchBundleData(selectedSymbol, selectedTimeframe, false);
    }, 20000);

    return () => {
      clearInterval(pollId);
    };
  }, [fetchBundleData, selectedSymbol, selectedTimeframe]);

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
      reconnectAttemptsRef.current = 0;
      setWsStatus('open');
      setWsConnectionState('CONNECTED');
      if (WATCHLIST_SYMBOLS.length) {
        ws.send(JSON.stringify({ action: 'subscribe', symbols: WATCHLIST_SYMBOLS }));
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
        if (!symbol) return;
        updateWatchlistFromTick(symbol, message);
        if (symbol === selectedSymbolRef.current) {
          updateBundleFromTick(message);
        }
        return;
      }

      if (message.type === 'candle_update') {
        const symbol = String(message.symbol || '').toUpperCase();
        if (symbol !== selectedSymbolRef.current) return;
        updateBundleFromCandle(message);
        return;
      }

      if (message.type === 'signal_update') {
        const symbol = String(message.symbol || '').toUpperCase();
        if (symbol !== selectedSymbolRef.current) return;

        setSignalData((prev) => ({
          ...(prev || {}),
          symbol,
          signal: String(message.signal || 'HOLD').toUpperCase(),
          confidence: normalizeConfidencePct(
            message.confidence,
            toNumber(message.confidence_pct, 0)
          ),
          momentumScore: toNumber(message.momentum_score, toNumber(prev?.momentumScore, 50)),
          trendScore: toNumber(message.trend_score, toNumber(prev?.trendScore, 50)),
          volatilityScore: toNumber(message.volatility_score, toNumber(prev?.volatilityScore, 50)),
          volatilityState: message.volatility_state || prev?.volatilityState || 'MISSING',
          volumeScore: toNumber(message.volume_score, toNumber(prev?.volumeScore, 50)),
          volumeRatio: toNumber(message.volume_ratio, toNumber(prev?.volumeRatio, 1)),
          volumeRatioFlag: message.volume_ratio_flag || prev?.volumeRatioFlag || 'NORMAL',
          volumeSpike: Boolean(message.volume_spike),
          volumeSpikeStrength: toNumber(message.volume_spike_strength, toNumber(prev?.volumeSpikeStrength, 0)),
          vwapDeviation: toNumber(message.vwap_deviation, toNumber(prev?.vwapDeviation, 0)),
          vwapBias: message.vwap_bias || prev?.vwapBias || 'NEUTRAL',
          obvSlope: toNumber(message.obv_slope, toNumber(prev?.obvSlope, 0)),
          obvDivergence: Boolean(message.obv_divergence),
          volumeTrendSlope: toNumber(message.volume_trend_slope, toNumber(prev?.volumeTrendSlope, 0)),
          volumeTrendDirection: message.volume_trend_direction || prev?.volumeTrendDirection || 'FLAT',
          positionSizeFactor: toNumber(message.position_size_factor, toNumber(prev?.positionSizeFactor, 0.75)),
          mtfAlignment: message.mtf_alignment || prev?.mtfAlignment || 'NEUTRAL',
          emaStructure: message.ema_structure || prev?.emaStructure || 'MIXED STACK',
          currentPrice: toNumber(message.prediction, toNumber(prev?.currentPrice, 0)),
          target: toNumber(message.target_price, toNumber(prev?.target, 0)),
          stopLoss: toNumber(message.stop_loss, toNumber(prev?.stopLoss, 0)),
          regime: message.regime || prev?.regime || 'Unknown',
          reason: message.reason || message.explanation || prev?.reason || '',
          explanation: message.explanation || prev?.explanation || '',
          timestamp: message.timestamp || new Date().toISOString(),
        }));
        setSignalError(null);
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

      reconnectAttemptsRef.current += 1;
      if (reconnectAttemptsRef.current > WS_MAX_RECONNECT_ATTEMPTS) {
        setWsStatus('error');
        setWsConnectionState('ERROR');
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
  }, [accessToken, isAuthenticated, updateBundleFromTick, updateBundleFromCandle, updateWatchlistFromTick]);

  useEffect(() => {
    shouldReconnectRef.current = true;
    clearSocket();
    connectSocket();

    return () => {
      shouldReconnectRef.current = false;
      clearSocket();
    };
  }, [clearSocket, connectSocket]);

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
  }, [fetchBundleData, selectedSymbol, selectedTimeframe]);

  const refreshSignal = useCallback(() => {
    fetchBundleData(selectedSymbol, selectedTimeframe, true);
  }, [fetchBundleData, selectedSymbol, selectedTimeframe]);

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
        confidence: normalizeConfidencePct(signalData.confidence, 0),
        momentumScore: toNumber(signalData.momentumScore, 50),
        trendScore: toNumber(signalData.trendScore, 50),
        volatilityScore: toNumber(signalData.volatilityScore, 50),
        volatilityState: signalData.volatilityState || 'MISSING',
        volumeScore: toNumber(signalData.volumeScore, 50),
        volumeRatio: toNumber(signalData.volumeRatio, 1),
        volumeRatioFlag: signalData.volumeRatioFlag || 'NORMAL',
        volumeSpike: Boolean(signalData.volumeSpike),
        volumeSpikeStrength: toNumber(signalData.volumeSpikeStrength, 0),
        vwapDeviation: toNumber(signalData.vwapDeviation, 0),
        vwapBias: signalData.vwapBias || 'NEUTRAL',
        obvSlope: toNumber(signalData.obvSlope, 0),
        obvDivergence: Boolean(signalData.obvDivergence),
        volumeTrendSlope: toNumber(signalData.volumeTrendSlope, 0),
        volumeTrendDirection: signalData.volumeTrendDirection || 'FLAT',
        positionSizeFactor: toNumber(signalData.positionSizeFactor, 0.75),
        mtfAlignment: signalData.mtfAlignment || 'NEUTRAL',
        emaStructure: signalData.emaStructure || 'MIXED STACK',
        target: toNumber(signalData.target, currentPrice),
        stopLoss: toNumber(signalData.stopLoss, currentPrice),
        currentPrice,
        timestamp: signalData.timestamp || new Date().toISOString(),
        regime: signalData.regime || 'Unknown',
        reason: signalData.reason || signalData.explanation || '',
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
      confidence: normalizeConfidencePct(
        prediction.confidence,
        toNumber(prediction.confidence_pct, 0)
      ),
      momentumScore: toNumber(prediction.momentum_score, 50),
      trendScore: toNumber(prediction.trend_score, 50),
      volatilityScore: toNumber(prediction.volatility_score, 50),
      volatilityState: prediction.volatility_state || 'MISSING',
      volumeScore: toNumber(prediction.volume_score, 50),
      volumeRatio: toNumber(prediction.volume_ratio, 1),
      volumeRatioFlag: prediction.volume_ratio_flag || 'NORMAL',
      volumeSpike: Boolean(prediction.volume_spike),
      volumeSpikeStrength: toNumber(prediction.volume_spike_strength, 0),
      vwapDeviation: toNumber(prediction.vwap_deviation, 0),
      vwapBias: prediction.vwap_bias || 'NEUTRAL',
      obvSlope: toNumber(prediction.obv_slope, 0),
      obvDivergence: Boolean(prediction.obv_divergence),
      volumeTrendSlope: toNumber(prediction.volume_trend_slope, 0),
      volumeTrendDirection: prediction.volume_trend_direction || 'FLAT',
      positionSizeFactor: toNumber(prediction.position_size_factor, 0.75),
      mtfAlignment: prediction.mtf_alignment || 'NEUTRAL',
      emaStructure: prediction.ema_structure || 'MIXED STACK',
      target: toNumber(prediction.target_price, 0),
      stopLoss: toNumber(prediction.stop_loss, 0),
      currentPrice,
      timestamp: new Date().toISOString(),
      regime: prediction.regime || 'Unknown',
      reason: prediction.reason || prediction.explanation || '',
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
