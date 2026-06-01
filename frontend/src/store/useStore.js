import { create } from 'zustand';
import { TradeService } from '../api/services/trade.service.js';
import { PortfolioService } from '../api/services/portfolio.service.js';
import { SignalService } from '../api/services/signal.service.js';
import { fetchMarketSymbols, fetchStockBundle, fetchTradeDecision } from '../lib/api.js';
import {
  API_TIMEOUT_MS,
  LATENCY_LIVE_MS,
  LATENCY_MAX_MS,
  LATENCY_OVERLOAD_MS,
  cancelActiveRequest,
  isAbortLikeError,
} from '../api/requestGate.js';
import { API_BASE } from '../config/api.js';

const DEFAULT_SYMBOL = 'RELIANCE';
const DEFAULT_TIMEFRAME = '1m';
const BUNDLE_CANDLE_LIMIT = 200;
const BUNDLE_REQUEST_TIMEOUT_MS = 8000;
const DECISION_REQUEST_TIMEOUT_MS = 2500;
const ALLOWED_TIMEFRAMES = new Set(['1m', '5m', '15m', '1h', '1d']);

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const toFiniteNumber = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const PRICE_SOURCE = {
  WS: 'WS',
  API: 'API',
  UNKNOWN: 'UNKNOWN',
};

const LIVE_HEALTH = {
  LIVE: 'LIVE',
  DELAYED: 'DELAYED',
  STALE: 'STALE',
};

const bundleRequestControllers = new Map();
const decisionRequestControllers = new Map();

const isBundleRequestActive = (symbol) => bundleRequestControllers.has(symbol);
const isDecisionRequestActive = (symbol) => decisionRequestControllers.has(symbol);

const replaceRequestController = (map, key) => {
  const previous = map.get(key);
  if (previous) {
    previous.abort('superseded_by_new_request');
  }
  const nextController = new AbortController();
  map.set(key, nextController);
  return nextController;
};

const releaseRequestController = (map, key, controller) => {
  if (map.get(key) === controller) {
    map.delete(key);
  }
};

const abortControllerMap = (map, reason) => {
  for (const controller of map.values()) {
    controller.abort(reason);
  }
  map.clear();
};

const toLatencyHealth = (latencyMs) => {
  const parsed = toFiniteNumber(latencyMs, null);
  if (parsed === null) return LIVE_HEALTH.STALE;
  if (parsed <= LATENCY_LIVE_MS) return LIVE_HEALTH.LIVE;
  if (parsed <= LATENCY_MAX_MS) return LIVE_HEALTH.DELAYED;
  return LIVE_HEALTH.STALE;
};

const SOURCE_PRIORITY = {
  [PRICE_SOURCE.WS]: 3,
  [PRICE_SOURCE.API]: 2,
  [PRICE_SOURCE.UNKNOWN]: 1,
};

const normalizePriceSource = (value) => {
  const raw = String(value || '').trim().toUpperCase();
  if (raw === 'WS' || raw === 'WEBSOCKET') return PRICE_SOURCE.WS;
  if (raw === 'API') return PRICE_SOURCE.API;
  return PRICE_SOURCE.UNKNOWN;
};

const parseTimestampMs = (value, fallback = Date.now()) => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? Math.floor(value) : Math.floor(value * 1000);
  }

  const asNumber = Number(value);
  if (Number.isFinite(asNumber)) {
    return asNumber > 1e12 ? Math.floor(asNumber) : Math.floor(asNumber * 1000);
  }

  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : fallback;
};

const resolveSafePrice = (incomingPrice, previousMeta) => {
  const parsed = toFiniteNumber(incomingPrice, null);
  if (parsed !== null && parsed > 0) {
    return parsed;
  }

  const fallback = toFiniteNumber(previousMeta?.lastValidPrice ?? previousMeta?.currentPrice, null);
  return fallback;
};

const shouldAcceptIncomingPrice = ({ previousMeta, nextTimestamp, nextSource }) => {
  if (nextSource !== PRICE_SOURCE.WS) {
    return false;
  }

  const latencyMs = Math.max(0, Date.now() - nextTimestamp);
  if (latencyMs > LATENCY_MAX_MS) {
    return false;
  }

  if (!previousMeta) {
    return true;
  }

  const previousTimestamp = toFiniteNumber(previousMeta.lastUpdatedTimestamp, 0);
  const previousSource = normalizePriceSource(previousMeta.dataSource);

  if (nextTimestamp < previousTimestamp) {
    return false;
  }

  if (nextTimestamp > previousTimestamp) {
    return true;
  }

  const nextPriority = SOURCE_PRIORITY[nextSource] || 0;
  const previousPriority = SOURCE_PRIORITY[previousSource] || 0;
  if (nextPriority > previousPriority) {
    return true;
  }
  if (nextPriority < previousPriority) {
    return false;
  }

  return true;
};

const mergeSymbolPriceState = (state, symbol, incomingPrice, options = {}) => {
  const normalizedSymbol = normalizeSymbol(symbol);
  if (!normalizedSymbol) {
    return { state, accepted: false, resolvedPrice: null };
  }

  const previousMeta = state.livePriceBySymbol?.[normalizedSymbol];
  const resolvedPrice = resolveSafePrice(incomingPrice, previousMeta);
  if (resolvedPrice === null) {
    return { state, accepted: false, resolvedPrice: null };
  }

  const nextSource = normalizePriceSource(options.dataSource);
  const nextTimestamp = parseTimestampMs(options.timestamp, Date.now());
  const nextLatencyMs = toFiniteNumber(options.latencyMs, Math.max(0, Date.now() - nextTimestamp));

  if (nextLatencyMs > LATENCY_OVERLOAD_MS) {
    return {
      state,
      accepted: false,
      resolvedPrice: toFiniteNumber(previousMeta?.currentPrice, resolvedPrice),
      isStale: true,
      isOverload: true,
      latencyMs: nextLatencyMs,
      health: LIVE_HEALTH.STALE,
    };
  }

  if (nextLatencyMs > LATENCY_MAX_MS) {
    return {
      state,
      accepted: false,
      resolvedPrice: toFiniteNumber(previousMeta?.currentPrice, resolvedPrice),
      isStale: true,
      isOverload: false,
      latencyMs: nextLatencyMs,
      health: LIVE_HEALTH.STALE,
    };
  }

  const shouldAccept = shouldAcceptIncomingPrice({
    previousMeta,
    nextTimestamp,
    nextSource,
  });

  if (!shouldAccept) {
    return {
      state,
      accepted: false,
      resolvedPrice: toFiniteNumber(previousMeta?.currentPrice, resolvedPrice),
      isStale: nextLatencyMs > LATENCY_MAX_MS,
      isOverload: nextLatencyMs > LATENCY_OVERLOAD_MS,
      latencyMs: nextLatencyMs,
      health: toLatencyHealth(nextLatencyMs),
    };
  }

  const nextMeta = {
    currentPrice: resolvedPrice,
    lastValidPrice: resolvedPrice,
    lastUpdatedTimestamp: nextTimestamp,
    dataSource: nextSource,
    latencyMs: nextLatencyMs,
  };

  return {
    accepted: true,
    resolvedPrice,
    meta: nextMeta,
    isStale: false,
    isOverload: false,
    latencyMs: nextLatencyMs,
    health: toLatencyHealth(nextLatencyMs),
    state: {
      ...state,
      livePriceBySymbol: {
        ...(state.livePriceBySymbol || {}),
        [normalizedSymbol]: nextMeta,
      },
      priceBySymbol: {
        ...(state.priceBySymbol || {}),
        [normalizedSymbol]: resolvedPrice,
      },
    },
  };
};

const unwrapApiData = (payload) => {
  if (!payload || typeof payload !== 'object') return payload;
  if (payload.success === true && payload.data !== undefined) return payload.data;
  if (payload.status === 'success' && payload.data !== undefined) return payload.data;
  if (payload.status === 'ok' && payload.data !== undefined) return payload.data;
  if (payload.result !== undefined) return payload.result;
  if (payload.data !== undefined) return payload.data;
  return payload;
};

const normalizeSymbol = (value, fallback = '') => {
  const raw = String(value || fallback || '').trim().toUpperCase();
  return raw;
};

const normalizeConfidence = (value) => {
  const raw = toNumber(value, 0);
  return raw <= 1 ? raw * 100 : raw;
};

const toUiErrorMessage = (error, fallback) => {
  const status = Number(error?.status ?? error?.response?.status ?? 0);
  if (status === 401) return 'Auth Error - Reconnect Required';
  if (status === 404) return 'Data not found for symbol/route';
  return error?.message || fallback;
};

const normalizeBundleWarnings = (bundle) => {
  if (!Array.isArray(bundle?.warnings)) return [];
  return bundle.warnings.filter((item) => typeof item === 'string' && item.trim());
};

const normalizeSignal = (bundle, symbol) => {
  const snapshot = bundle?.snapshot || {};
  const prediction = bundle?.prediction || bundle?.signal || {};
  const price = toNumber(
    snapshot.ltp ?? snapshot.price ?? bundle?.latest_price ?? bundle?.price ?? prediction.prediction,
    0,
  );
  const confidence = normalizeConfidence(prediction.confidence ?? prediction.confidence_pct);

  return {
    id: `${symbol}-${Date.now()}`,
    symbol,
    signal: String(prediction.signal || prediction.type || 'HOLD').toUpperCase(),
    type: String(prediction.signal || prediction.type || 'HOLD').toUpperCase(),
    confidence,
    price,
    currentPrice: price,
    target: toNumber(prediction.target ?? prediction.target_price, price),
    stopLoss: toNumber(prediction.stop_loss ?? prediction.stopLoss, price),
    reason: prediction.reason || prediction.reasoning || prediction.explanation || 'Live bundle signal',
    timestamp: prediction.timestamp || new Date().toISOString(),
  };
};

const normalizeCandles = (rows) => {
  if (!Array.isArray(rows)) return [];

  const parsed = rows
    .map((row) => {
      const time = row?.time || row?.timestamp || row?.datetime;
      const open = toNumber(row?.open, NaN);
      const high = toNumber(row?.high, NaN);
      const low = toNumber(row?.low, NaN);
      const close = toNumber(row?.close, NaN);

      if (!time || !Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low) || !Number.isFinite(close)) {
        return null;
      }

      return {
        time,
        open,
        high,
        low,
        close,
        volume: toNumber(row?.volume, 0),
      };
    })
    .filter(Boolean);

  const deduped = new Map();
  parsed.forEach((candle) => {
    deduped.set(String(candle.time), candle);
  });

  return Array.from(deduped.values()).sort((left, right) => {
    const leftTs = Date.parse(String(left.time || ''));
    const rightTs = Date.parse(String(right.time || ''));
    return (Number.isFinite(leftTs) ? leftTs : 0) - (Number.isFinite(rightTs) ? rightTs : 0);
  });
};

const toChartData = (candles) => {
  return candles.map((candle) => {
    const rawTime = String(candle.time || '');
    const label = rawTime.includes('T')
      ? rawTime.slice(11, 16)
      : rawTime.slice(0, 16);

    return {
      time: label || rawTime,
      value: toNumber(candle.close, 0),
      volume: toNumber(candle.volume, 0),
    };
  });
};

const normalizeTradeRow = (row, index = 0) => {
  const symbol = normalizeSymbol(row?.symbol);
  const entryPrice = toNumber(row?.entry_price ?? row?.entryPrice, 0);
  const quantity = Math.max(1, toNumber(row?.quantity ?? row?.size, 1));
  const direction = String(row?.direction || row?.type || 'BUY').toUpperCase();
  const currentPrice = toNumber(row?.current_price ?? row?.currentPrice ?? entryPrice, entryPrice);

  return {
    id: row?.id || row?.order_id || `trade_${symbol}_${index}`,
    symbol,
    type: direction,
    entryPrice,
    currentPrice,
    pnl: toNumber(row?.pnl, 0),
    size: quantity,
    status: String(row?.status || 'OPEN').toUpperCase(),
    sl: toNumber(row?.stop_loss ?? row?.sl ?? row?.stopLoss, entryPrice),
    tp: toNumber(row?.target ?? row?.tp ?? row?.target_price, entryPrice),
  };
};

const normalizeSignalRow = (row, fallbackSymbol = DEFAULT_SYMBOL) => {
  const symbol = normalizeSymbol(row?.symbol, fallbackSymbol);
  const signal = String(row?.signal || row?.type || 'HOLD').toUpperCase();
  const price = toNumber(
    row?.price
    ?? row?.currentPrice
    ?? row?.ltp
    ?? row?.latest_price
    ?? row?.prediction
    ?? row?.close,
    0,
  );

  return {
    id: row?.id || `${symbol}-${Date.now()}`,
    symbol,
    signal,
    type: signal,
    confidence: normalizeConfidence(row?.confidence ?? row?.confidence_pct),
    price,
    currentPrice: price,
    target: toNumber(row?.target ?? row?.target_price, price),
    stopLoss: toNumber(row?.stop_loss ?? row?.stopLoss, price),
    reason: row?.reason || row?.reasoning || row?.explanation || 'Live signal update',
    timestamp: row?.timestamp || new Date().toISOString(),
  };
};

const hydrateSignalWithPrevious = (nextSignal, previousSignal, fallbackPrice = 0) => {
  const resolvedPrice = nextSignal.price > 0
    ? nextSignal.price
    : toNumber(previousSignal?.price ?? previousSignal?.currentPrice ?? fallbackPrice, 0);

  return {
    ...(previousSignal || {}),
    ...nextSignal,
    price: resolvedPrice,
    currentPrice: resolvedPrice,
    target: nextSignal.target > 0
      ? nextSignal.target
      : toNumber(previousSignal?.target, resolvedPrice),
    stopLoss: nextSignal.stopLoss > 0
      ? nextSignal.stopLoss
      : toNumber(previousSignal?.stopLoss, resolvedPrice),
  };
};

export const useStore = create((set, get) => ({
  activeTrades: [],
  signals: [],
  balance: 100000,
  availableMargin: 100000,
  usedMargin: 0,
  todaysPnL: 0,
  winRate: 0,
  isLoading: false,
  bundleLoading: false,
  bundleError: null,
  bundlePartial: false,
  bundleWarnings: [],
  connectionStatus: 'DISCONNECTED',
  systemStatus: true,
  systemAlert: null,
  isPaperTrading: true,
  riskPercentage: 2,
  selectedSymbol: DEFAULT_SYMBOL,
  selectedTimeframe: DEFAULT_TIMEFRAME,
  symbolCatalog: [],
  priceBySymbol: {},
  livePriceBySymbol: {},
  liveLatencyMs: null,
  liveHealth: LIVE_HEALTH.STALE,
  tradingBlockedByLatency: true,
  liveDataMessage: 'NO LIVE DATA',
  chartData: [],
  candles: [],
  snapshot: null,
  indicators: {},
  currentSignal: null,
  tradeDecisionBySymbol: {},
  tradeDecisionLoadingBySymbol: {},
  tradeDecisionErrorBySymbol: {},
  tradeDecisionRequestSeqBySymbol: {},
  bundleRequestSeqBySymbol: {},
  serverHealthMatrix: {
    database: 'nominal',
    redis: 'nominal',
    ml_workers: 'active',
    websocket_stream: 'nominal',
  },

  setConnectionStatus: (status) => set((state) => {
    const normalized = String(status || 'DISCONNECTED').toUpperCase();
    if (normalized === 'CONNECTED') {
      return {
        connectionStatus: normalized,
        systemAlert: state.systemAlert === 'NO LIVE DATA' ? null : state.systemAlert,
      };
    }

    if (normalized === 'DISCONNECTED' || normalized === 'FAILED' || normalized === 'STALE') {
      return {
        connectionStatus: normalized,
        liveHealth: LIVE_HEALTH.STALE,
        tradingBlockedByLatency: true,
        liveDataMessage: 'NO LIVE DATA',
        systemAlert: 'NO LIVE DATA',
      };
    }

    return { connectionStatus: normalized };
  }),
  setSystemStatus: (status) => set({ systemStatus: status }),
  setSystemAlert: (msg) => set({ systemAlert: msg }),
  toggleSystemStatus: () => set((state) => ({ systemStatus: !state.systemStatus })),
  toggleTradingMode: () => set((state) => ({ isPaperTrading: !state.isPaperTrading })),
  checkBackendReady: async () => {
    try {
      const response = await fetch(`${API_BASE}/health/ready`);
      if (response && response.ok) {
        const data = await response.json();
        set({
          serverHealthMatrix: data?.subsystems || {
            database: 'nominal',
            redis: 'nominal',
            ml_workers: 'active',
            websocket_stream: 'nominal'
          }
        });
      } else {
        set({
          serverHealthMatrix: {
            database: 'unreachable',
            redis: 'unreachable',
            ml_workers: 'idle',
            websocket_stream: 'unreachable'
          }
        });
      }
    } catch {
      set({
        serverHealthMatrix: {
          database: 'unreachable',
          redis: 'unreachable',
          ml_workers: 'idle',
          websocket_stream: 'unreachable'
        }
      });
    }
  },
  setRiskPercentage: (riskPercentage) => set({ riskPercentage: Math.max(1, Math.min(10, toNumber(riskPercentage, 2))) }),
  resetPortfolio: () => set({
    activeTrades: [],
    balance: 100000,
    availableMargin: 100000,
    usedMargin: 0,
    todaysPnL: 0,
  }),

  markRealtimeStale: (latencyMs = null, reason = 'NO LIVE DATA') => set((state) => ({
    connectionStatus: 'STALE',
    liveLatencyMs: toFiniteNumber(latencyMs, state.liveLatencyMs),
    liveHealth: LIVE_HEALTH.STALE,
    tradingBlockedByLatency: true,
    liveDataMessage: reason,
    systemAlert: reason,
  })),

  resetRealtimeState: (reason = 'Realtime overload reset') => {
    abortControllerMap(bundleRequestControllers, 'realtime_overload_reset');
    abortControllerMap(decisionRequestControllers, 'realtime_overload_reset');
    cancelActiveRequest('realtime_overload_reset');

    set(() => ({
      connectionStatus: 'STALE',
      liveLatencyMs: null,
      liveHealth: LIVE_HEALTH.STALE,
      tradingBlockedByLatency: true,
      liveDataMessage: reason,
      systemAlert: reason,
      bundleLoading: false,
      bundlePartial: true,
      bundleWarnings: [reason],
      tradeDecisionLoadingBySymbol: {},
      bundleRequestSeqBySymbol: {},
      tradeDecisionRequestSeqBySymbol: {},
    }));
  },

  loadSymbolCatalog: async (limit = 500) => {
    try {
      const rows = await fetchMarketSymbols(limit, { timeoutMs: API_TIMEOUT_MS });
      set({ symbolCatalog: Array.isArray(rows) ? rows : [] });
    } catch {
      set({ symbolCatalog: [] });
    }
  },

  loadSymbolBundle: async (symbol, timeframe = null, options = {}) => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    const skipIfLoading = Boolean(options?.skipIfLoading);
    const state = get();
    const requestedTimeframe = String(timeframe || state.selectedTimeframe || DEFAULT_TIMEFRAME).trim().toLowerCase();
    const normalizedTimeframe = ALLOWED_TIMEFRAMES.has(requestedTimeframe)
      ? requestedTimeframe
      : DEFAULT_TIMEFRAME;
    if (!normalizedSymbol) return;

    if (skipIfLoading && isBundleRequestActive(normalizedSymbol)) {
      return null;
    }

    const currentSeq = (get().bundleRequestSeqBySymbol?.[normalizedSymbol] || 0) + 1;
    const controller = replaceRequestController(bundleRequestControllers, normalizedSymbol);

    set((prev) => ({
      bundleLoading: true,
      bundleError: null,
      bundleWarnings: prev.bundleWarnings || [],
      selectedSymbol: normalizedSymbol,
      selectedTimeframe: normalizedTimeframe,
      candles: [],
      chartData: [],
      snapshot: null,
      indicators: {},
      currentSignal: null,
      bundleRequestSeqBySymbol: {
        ...prev.bundleRequestSeqBySymbol,
        [normalizedSymbol]: currentSeq,
      },
    }));

    const startMs = Date.now();
    try {
      const bundle = await fetchStockBundle(normalizedSymbol, {
        interval: normalizedTimeframe,
        limit: BUNDLE_CANDLE_LIMIT,
        horizon: '15m',
        signal: controller.signal,
        timeoutMs: BUNDLE_REQUEST_TIMEOUT_MS,
      });
      const requestDurationMs = Date.now() - startMs;

      const activeSeq = get().bundleRequestSeqBySymbol?.[normalizedSymbol] || 0;
      if (controller.signal.aborted || activeSeq !== currentSeq) {
        return null;
      }

      const previousSnapshotTimestamp = parseTimestampMs(
        get().snapshot?.timestamp ?? get().snapshot?.last_updated,
        0,
      );
      const incomingSnapshotTimestamp = parseTimestampMs(
        bundle?.snapshot?.timestamp ?? bundle?.snapshot?.last_updated ?? bundle?.timestamp,
        Date.now(),
      );
      if (incomingSnapshotTimestamp < previousSnapshotTimestamp) {
        return null;
      }

      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log('Bundle response:', bundle);
      }

      const candles = normalizeCandles(bundle?.history?.candles);
      const chartData = toChartData(candles);
      const signal = normalizeSignal(bundle, normalizedSymbol);
      const warnings = normalizeBundleWarnings(bundle);
      const isPartial = Boolean(bundle?.partial) || warnings.length > 0;

      set((prev) => {
        const ltpPrice = toNumber(bundle?.snapshot?.ltp ?? bundle?.snapshot?.price ?? bundle?.latest_price ?? bundle?.price, 0);
        const resolvedCurrentPrice = prev.connectionStatus === 'CONNECTED'
          ? toNumber(prev.livePriceBySymbol?.[normalizedSymbol]?.currentPrice, ltpPrice)
          : ltpPrice;

        const mergedSignal = {
          ...signal,
          price: resolvedCurrentPrice,
          currentPrice: resolvedCurrentPrice,
        };

        const updatedLivePriceBySymbol = { ...(prev.livePriceBySymbol || {}) };
        const updatedPriceBySymbol = { ...(prev.priceBySymbol || {}) };

        if (prev.connectionStatus !== 'CONNECTED' && resolvedCurrentPrice > 0) {
          updatedLivePriceBySymbol[normalizedSymbol] = {
            currentPrice: resolvedCurrentPrice,
            lastValidPrice: resolvedCurrentPrice,
            lastUpdatedTimestamp: Date.now(),
            dataSource: 'API',
            latencyMs: requestDurationMs,
          };
          updatedPriceBySymbol[normalizedSymbol] = resolvedCurrentPrice;
        }

        const isPollingDegraded = prev.connectionStatus !== 'CONNECTED';
        const pollingHealth = requestDurationMs <= LATENCY_MAX_MS ? LIVE_HEALTH.DELAYED : LIVE_HEALTH.STALE;

        return {
          bundleLoading: false,
          bundleError: null,
          bundlePartial: isPartial,
          bundleWarnings: warnings,
          candles,
          chartData,
          snapshot: bundle?.snapshot || null,
          indicators: bundle?.indicators || {},
          systemAlert: isPartial && warnings.length > 0 ? warnings[0] : prev.systemAlert,
          currentSignal: mergedSignal,
          signals: [mergedSignal, ...prev.signals.filter((item) => item.symbol !== normalizedSymbol)].slice(0, 50),
          livePriceBySymbol: updatedLivePriceBySymbol,
          priceBySymbol: updatedPriceBySymbol,
          ...(isPollingDegraded ? {
            liveLatencyMs: requestDurationMs,
            liveHealth: pollingHealth,
            tradingBlockedByLatency: pollingHealth === LIVE_HEALTH.STALE,
            liveDataMessage: pollingHealth === LIVE_HEALTH.STALE ? 'NO LIVE DATA' : null,
          } : {})
        };
      });

      void get().evaluateTradeDecision(normalizedSymbol, normalizedTimeframe, {
        capital: get().balance,
        skipIfLoading: true,
      }).catch(() => null);
      return bundle;
    } catch (error) {
      const activeSeq = get().bundleRequestSeqBySymbol?.[normalizedSymbol] || 0;
      if (controller.signal.aborted || isAbortLikeError(error)) {
        if (activeSeq === currentSeq) {
          set({ bundleLoading: false });
        }
        return null;
      }

      if (activeSeq === currentSeq) {
        const fallbackMessage = get().candles?.length
          ? 'Showing last cached market data while bundle refresh retries.'
          : toUiErrorMessage(error, 'Failed to load stock bundle');
        set({
          bundleLoading: false,
          bundleError: fallbackMessage,
          bundlePartial: true,
          bundleWarnings: [fallbackMessage],
        });
      }
      return null;
    } finally {
      releaseRequestController(bundleRequestControllers, normalizedSymbol, controller);
    }
  },

  evaluateTradeDecision: async (symbol, timeframe = null, options = {}) => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    if (!normalizedSymbol) {
      throw new Error('Symbol is required to evaluate trade decision');
    }

    const skipIfLoading = Boolean(options?.skipIfLoading);
    if (skipIfLoading && isDecisionRequestActive(normalizedSymbol)) {
      return get().tradeDecisionBySymbol?.[normalizedSymbol] || null;
    }

    const requestedTimeframe = String(timeframe || get().selectedTimeframe || DEFAULT_TIMEFRAME).trim().toLowerCase();
    const normalizedTimeframe = ALLOWED_TIMEFRAMES.has(requestedTimeframe)
      ? requestedTimeframe
      : DEFAULT_TIMEFRAME;

    const currentSeq = (get().tradeDecisionRequestSeqBySymbol?.[normalizedSymbol] || 0) + 1;
    const controller = replaceRequestController(decisionRequestControllers, normalizedSymbol);

    set((state) => ({
      tradeDecisionRequestSeqBySymbol: {
        ...state.tradeDecisionRequestSeqBySymbol,
        [normalizedSymbol]: currentSeq,
      },
      tradeDecisionLoadingBySymbol: {
        ...state.tradeDecisionLoadingBySymbol,
        [normalizedSymbol]: true,
      },
      tradeDecisionErrorBySymbol: {
        ...state.tradeDecisionErrorBySymbol,
        [normalizedSymbol]: null,
      },
    }));

    try {
      const payload = await fetchTradeDecision(normalizedSymbol, {
        interval: normalizedTimeframe,
        horizon: options.horizon || '15m',
        capital: toNumber(options.capital, get().balance),
        riskPerTrade: toNumber(options.riskPerTrade, 0.01),
        signal: controller.signal,
        timeoutMs: DECISION_REQUEST_TIMEOUT_MS,
      });

      const activeSeq = get().tradeDecisionRequestSeqBySymbol?.[normalizedSymbol] || 0;
      if (activeSeq !== currentSeq || controller.signal.aborted) {
        return payload;
      }

      const existingDecision = get().tradeDecisionBySymbol?.[normalizedSymbol] || null;
      const existingTimestamp = parseTimestampMs(existingDecision?.evaluated_at, 0);
      const incomingTimestamp = parseTimestampMs(payload?.evaluated_at, Date.now());
      if (incomingTimestamp < existingTimestamp) {
        return existingDecision;
      }

      set((state) => ({
        tradeDecisionBySymbol: {
          ...state.tradeDecisionBySymbol,
          [normalizedSymbol]: payload,
        },
        tradeDecisionLoadingBySymbol: {
          ...state.tradeDecisionLoadingBySymbol,
          [normalizedSymbol]: false,
        },
        tradeDecisionErrorBySymbol: {
          ...state.tradeDecisionErrorBySymbol,
          [normalizedSymbol]: null,
        },
      }));

      return payload;
    } catch (error) {
      const activeSeq = get().tradeDecisionRequestSeqBySymbol?.[normalizedSymbol] || 0;
      if (controller.signal.aborted || isAbortLikeError(error)) {
        if (activeSeq === currentSeq) {
          set((state) => ({
            tradeDecisionLoadingBySymbol: {
              ...state.tradeDecisionLoadingBySymbol,
              [normalizedSymbol]: false,
            },
          }));
        }
        return null;
      }

      if (activeSeq === currentSeq) {
        set((state) => ({
          tradeDecisionLoadingBySymbol: {
            ...state.tradeDecisionLoadingBySymbol,
            [normalizedSymbol]: false,
          },
          tradeDecisionErrorBySymbol: {
            ...state.tradeDecisionErrorBySymbol,
            [normalizedSymbol]: toUiErrorMessage(error, 'Failed to evaluate trade decision'),
          },
        }));
      }
      throw error;
    } finally {
      releaseRequestController(decisionRequestControllers, normalizedSymbol, controller);
    }
  },

  selectTimeframe: async (timeframe) => {
    const requested = String(timeframe || DEFAULT_TIMEFRAME).trim().toLowerCase();
    const nextTimeframe = ALLOWED_TIMEFRAMES.has(requested) ? requested : DEFAULT_TIMEFRAME;
    await get().loadSymbolBundle(get().selectedSymbol, nextTimeframe);
  },

  fetchInitialData: async () => {
    set({ isLoading: true });
    try {
      const tradesResponse = await TradeService.getActive().catch(() => null);
      const portfolioResponse = await PortfolioService.getBalance().catch(() => null);
      const signalsResponse = await SignalService.getActive().catch(() => null);

      const tradesPayload = unwrapApiData(tradesResponse) || {};
      const portfolioPayload = unwrapApiData(portfolioResponse) || {};
      const signalsPayload = unwrapApiData(signalsResponse) || {};

      const activePositions = Array.isArray(tradesPayload?.positions)
        ? tradesPayload.positions
        : (Array.isArray(tradesPayload) ? tradesPayload : []);
      const normalizedTrades = activePositions.map((row, index) => normalizeTradeRow(row, index));

      const signalRows = Array.isArray(signalsPayload?.signals)
        ? signalsPayload.signals
        : (Array.isArray(signalsPayload) ? signalsPayload : []);
      const normalizedSignals = signalRows.map((row) => normalizeSignalRow(row, get().selectedSymbol));

      const selectedSymbol = get().selectedSymbol;
      const selectedSignal = normalizedSignals.find((row) => row.symbol === selectedSymbol) || normalizedSignals[0] || null;

      set({ 
        activeTrades: normalizedTrades,
        balance: toNumber(portfolioPayload?.equity ?? portfolioPayload?.total, get().balance),
        availableMargin: toNumber(portfolioPayload?.available_balance ?? portfolioPayload?.available, get().availableMargin),
        usedMargin: toNumber(portfolioPayload?.gross_exposure ?? portfolioPayload?.usedMargin, get().usedMargin),
        todaysPnL: toNumber(portfolioPayload?.unrealized_pnl ?? portfolioPayload?.todaysPnL, get().todaysPnL),
        winRate: toNumber(portfolioPayload?.win_rate ?? portfolioPayload?.winRate, get().winRate),
        signals: normalizedSignals,
        currentSignal: selectedSignal || get().currentSignal,
        isLoading: false,
      });

      await get().loadSymbolCatalog().catch(() => null);
      await get().loadSymbolBundle(get().selectedSymbol, get().selectedTimeframe).catch(() => null);
    } catch { set({ isLoading: false }); }
  },
  
  executeTrade: async (signal) => {
    const state = get(); if (!state.systemStatus) throw new Error("API Offline");
    if (state.tradingBlockedByLatency) {
      throw new Error(state.liveDataMessage || 'Trading blocked: live data is stale');
    }
    const tradeType = String(signal?.type || signal?.signal || 'BUY').toUpperCase();
    const signalSymbol = String(signal?.symbol || state.selectedSymbol || '').toUpperCase();
    const entryPrice = toNumber(signal?.price ?? signal?.currentPrice ?? state.priceBySymbol[signalSymbol], 0);
    const tp = toNumber(signal?.tp ?? signal?.target, entryPrice);
    const sl = toNumber(signal?.sl ?? signal?.stopLoss, entryPrice);

    const decisionPayload = await state.evaluateTradeDecision(signalSymbol, state.selectedTimeframe, {
      capital: state.balance,
      riskPerTrade: 0.01,
    });
    const decisionStatus = String(decisionPayload?.decision?.status || 'BLOCKED').toUpperCase();
    if (decisionStatus !== 'READY') {
      const reasons = Array.isArray(decisionPayload?.decision?.reasons)
        ? decisionPayload.decision.reasons.filter(Boolean)
        : [];
      const reasonText = reasons.length
        ? reasons.slice(0, 3).join(' | ')
        : 'Decision engine blocked trade';
      throw new Error(`Trade blocked: ${reasonText}`);
    }

    const tempId = `temp_${Date.now()}`;
    const tempTrade = { 
      id: tempId,
      symbol: signalSymbol,
      type: tradeType,
      entryPrice,
      currentPrice: entryPrice,
      pnl: 0,
      size: signal?.size || 1,
      status: 'EXECUTING',
      sl,
      tp,
    };

    set(s => ({ activeTrades: [tempTrade, ...s.activeTrades] }));
    try {
      const { tradeId, executedPrice } = await TradeService.execute(
        signal?.id || signal?.signalId || signalSymbol,
        signalSymbol,
        tradeType,
        tempTrade.size,
        tp,
        sl,
      );

      set(s => ({ activeTrades: s.activeTrades.map(t => t.id === tempId ? { ...t, id: tradeId, status: 'OPEN', entryPrice: executedPrice || t.entryPrice } : t) }));
    } catch (e) { 
      set(s => ({ activeTrades: s.activeTrades.filter(t => t.id !== tempId) })); 
      throw e; 
    }
  },
  
  closeTrade: async (tradeId) => {
    const state = get(); if (!state.systemStatus) throw new Error("API Offline");
    const tradeToClose = state.activeTrades.find(t => t.id === tradeId); if (!tradeToClose) return;
    set(s => ({ activeTrades: s.activeTrades.filter(t => t.id !== tradeId) }));
    try { await TradeService.close(tradeId); } catch (e) { set(s => ({ activeTrades: [...s.activeTrades, tradeToClose] })); throw e; }
  },
  
  syncPortfolio: (p) => set(s => ({
    balance: p.total || s.balance,
    availableMargin: p.available || s.availableMargin,
    usedMargin: p.usedMargin || s.usedMargin,
    todaysPnL: p.todaysPnL || s.todaysPnL,
    winRate: toNumber(p.winRate, s.winRate),
  })),

  addLiveSignal: (signal) => set((s) => {
    const normalized = normalizeSignalRow(signal, s.selectedSymbol);
    const previousBySymbol = s.signals.find((item) => item.symbol === normalized.symbol);
    const canonicalPrice = toNumber(
      s.livePriceBySymbol?.[normalized.symbol]?.currentPrice,
      s.priceBySymbol[normalized.symbol],
    );
    const merged = hydrateSignalWithPrevious(
      normalized,
      previousBySymbol,
      canonicalPrice,
    );
    const nextSignals = [merged, ...s.signals.filter((item) => item.symbol !== normalized.symbol)].slice(0, 50);
    return {
      signals: nextSignals,
      currentSignal: merged.symbol === s.selectedSymbol
        ? {
            ...(s.currentSignal || {}),
            ...merged,
          }
        : s.currentSignal,
    };
  }),

  upsertLiveSignal: (signal) => set((s) => {
    const normalized = normalizeSignalRow(signal, s.selectedSymbol);
    const previousBySymbol = s.signals.find((item) => item.symbol === normalized.symbol);
    const canonicalPrice = toNumber(
      s.livePriceBySymbol?.[normalized.symbol]?.currentPrice,
      s.priceBySymbol[normalized.symbol],
    );
    const merged = hydrateSignalWithPrevious(
      normalized,
      previousBySymbol,
      canonicalPrice,
    );
    const nextSignals = [merged, ...s.signals.filter((item) => item.symbol !== normalized.symbol)].slice(0, 50);
    return {
      signals: nextSignals,
      currentSignal: merged.symbol === s.selectedSymbol
        ? {
            ...(s.currentSignal || {}),
            ...merged,
          }
        : s.currentSignal,
    };
  }),

  upsertLiveCandle: (symbol, payload) => set((s) => {
    const normalizedSymbol = normalizeSymbol(symbol);
    if (!normalizedSymbol) return s;

    const time = String(payload?.timestamp || payload?.time || '').trim();
    const open = toNumber(payload?.open, NaN);
    const high = toNumber(payload?.high, NaN);
    const low = toNumber(payload?.low, NaN);
    const close = toNumber(payload?.close, NaN);
    const volume = toNumber(payload?.volume, 0);

    if (!time || !Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low) || !Number.isFinite(close)) {
      return s;
    }

    const shouldUpdateSelected = normalizedSymbol === s.selectedSymbol;
    const nextCandle = { time, open, high, low, close, volume };

    let nextCandles = s.candles;
    if (shouldUpdateSelected) {
      const existingIndex = s.candles.findIndex((item) => String(item.time) === time);
      if (existingIndex >= 0) {
        nextCandles = [...s.candles];
        nextCandles[existingIndex] = nextCandle;
      } else {
        nextCandles = [...s.candles, nextCandle].slice(-BUNDLE_CANDLE_LIMIT);
      }
    }

    return {
      candles: shouldUpdateSelected ? nextCandles : s.candles,
      chartData: shouldUpdateSelected ? toChartData(nextCandles) : s.chartData,
      snapshot: shouldUpdateSelected
        ? {
            ...(s.snapshot || {}),
            close,
            high,
            low,
            open,
            volume,
            last_candle_time: time,
          }
        : s.snapshot,
    };
  }),

  syncTradeEvents: (p) => set(s => ({ activeTrades: s.activeTrades.filter(t => t.id !== p.tradeId) })),

  updateAssetPrice: (sym, px, options = {}) => set((s) => {
    const symbol = String(sym || '').toUpperCase();
    if (!symbol) return s;
    const isSelectedSymbol = symbol === s.selectedSymbol;

    const mergedPrice = mergeSymbolPriceState(s, symbol, px, {
      dataSource: options.dataSource || PRICE_SOURCE.WS,
      timestamp: options.timestamp,
      latencyMs: options.latencyMs,
    });

    if (!mergedPrice.accepted || mergedPrice.resolvedPrice === null) {
      if (!isSelectedSymbol) {
        return s;
      }

      if (mergedPrice.isOverload) {
        return {
          ...s,
          connectionStatus: 'STALE',
          liveHealth: LIVE_HEALTH.STALE,
          tradingBlockedByLatency: true,
          liveDataMessage: 'OVERLOAD: realtime feed reset required',
          systemAlert: 'OVERLOAD: realtime feed reset required',
          liveLatencyMs: mergedPrice.latencyMs,
        };
      }

      if (mergedPrice.isStale) {
        return {
          ...s,
          connectionStatus: 'STALE',
          liveHealth: LIVE_HEALTH.STALE,
          tradingBlockedByLatency: true,
          liveDataMessage: 'NO LIVE DATA',
          systemAlert: 'NO LIVE DATA',
          liveLatencyMs: mergedPrice.latencyMs,
        };
      }

      return s;
    }

    const price = mergedPrice.resolvedPrice;

    const updatedTrades = s.activeTrades.map((t) => {
      if (String(t.symbol).toUpperCase() !== symbol) return t;
      const direction = t.type === 'BUY' || t.type === 'LONG' ? 1 : -1;
      return {
        ...t,
        currentPrice: price,
        pnl: direction * (price - t.entryPrice) * t.size,
      };
    });

    const shouldUpdateSignal = String(s.currentSignal?.symbol || '').toUpperCase() === symbol;
    const shouldUpdateSnapshot = isSelectedSymbol;

    return {
      ...mergedPrice.state,
      activeTrades: updatedTrades,
      connectionStatus: isSelectedSymbol ? 'CONNECTED' : s.connectionStatus,
      liveLatencyMs: isSelectedSymbol ? mergedPrice.latencyMs : s.liveLatencyMs,
      liveHealth: isSelectedSymbol ? mergedPrice.health : s.liveHealth,
      tradingBlockedByLatency: isSelectedSymbol
        ? mergedPrice.health === LIVE_HEALTH.STALE
        : s.tradingBlockedByLatency,
      liveDataMessage: isSelectedSymbol
        ? (mergedPrice.health === LIVE_HEALTH.STALE ? 'NO LIVE DATA' : null)
        : s.liveDataMessage,
      systemAlert: isSelectedSymbol
        ? (mergedPrice.health === LIVE_HEALTH.STALE ? 'NO LIVE DATA' : null)
        : s.systemAlert,
      snapshot: shouldUpdateSnapshot
        ? {
            ...(s.snapshot || {}),
            ltp: price,
            price,
          }
        : s.snapshot,
      currentSignal: shouldUpdateSignal
        ? {
            ...s.currentSignal,
            price,
            currentPrice: price,
          }
        : s.currentSignal,
    };
  }),
}));

if (typeof window !== 'undefined') window.addEventListener('api:system_offline', () => { useStore.getState().setSystemStatus(false); useStore.getState().setSystemAlert('API Systems Offline. Trading suspended.'); });
