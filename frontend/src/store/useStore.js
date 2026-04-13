import { create } from 'zustand';
import { TradeService } from '../api/services/trade.service.js';
import { PortfolioService } from '../api/services/portfolio.service.js';
import { SignalService } from '../api/services/signal.service.js';
import { fetchMarketSymbols, fetchStockBundle } from '../lib/api.js';

const DEFAULT_SYMBOL = 'RELIANCE';
const DEFAULT_TIMEFRAME = '1m';
const BUNDLE_CANDLE_LIMIT = 100;
const ALLOWED_TIMEFRAMES = new Set(['1m', '5m', '15m', '1h', '1d']);

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
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

  return rows
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
  connectionStatus: 'DISCONNECTED',
  systemStatus: true,
  systemAlert: null,
  isPaperTrading: true,
  riskPercentage: 2,
  selectedSymbol: DEFAULT_SYMBOL,
  selectedTimeframe: DEFAULT_TIMEFRAME,
  symbolCatalog: [],
  priceBySymbol: {},
  chartData: [],
  candles: [],
  snapshot: null,
  indicators: {},
  currentSignal: null,

  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setSystemStatus: (status) => set({ systemStatus: status }),
  setSystemAlert: (msg) => set({ systemAlert: msg }),
  toggleSystemStatus: () => set((state) => ({ systemStatus: !state.systemStatus })),
  toggleTradingMode: () => set((state) => ({ isPaperTrading: !state.isPaperTrading })),
  setRiskPercentage: (riskPercentage) => set({ riskPercentage: Math.max(1, Math.min(10, toNumber(riskPercentage, 2))) }),
  resetPortfolio: () => set({
    activeTrades: [],
    balance: 100000,
    availableMargin: 100000,
    usedMargin: 0,
    todaysPnL: 0,
  }),

  loadSymbolCatalog: async (limit = 500) => {
    try {
      const rows = await fetchMarketSymbols(limit);
      set({ symbolCatalog: Array.isArray(rows) ? rows : [] });
    } catch {
      set({ symbolCatalog: [] });
    }
  },

  loadSymbolBundle: async (symbol, timeframe = null) => {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    const state = get();
    const requestedTimeframe = String(timeframe || state.selectedTimeframe || DEFAULT_TIMEFRAME).trim().toLowerCase();
    const normalizedTimeframe = ALLOWED_TIMEFRAMES.has(requestedTimeframe)
      ? requestedTimeframe
      : DEFAULT_TIMEFRAME;
    if (!normalizedSymbol) return;

    set({
      bundleLoading: true,
      bundleError: null,
      selectedSymbol: normalizedSymbol,
      selectedTimeframe: normalizedTimeframe,
    });

    try {
      const bundle = await fetchStockBundle(normalizedSymbol, {
        interval: normalizedTimeframe,
        limit: BUNDLE_CANDLE_LIMIT,
        horizon: '15m',
      });

      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log('Bundle response:', bundle);
      }

      const candles = normalizeCandles(bundle?.history?.candles);
      const chartData = toChartData(candles);
      const signal = normalizeSignal(bundle, normalizedSymbol);
      const ltp = toNumber(
        bundle?.snapshot?.ltp ?? bundle?.snapshot?.price ?? bundle?.latest_price ?? bundle?.price,
        signal.price,
      );

      set((prev) => ({
        bundleLoading: false,
        bundleError: null,
        candles,
        chartData,
        snapshot: bundle?.snapshot || null,
        indicators: bundle?.indicators || {},
        currentSignal: signal,
        signals: [signal, ...prev.signals.filter((item) => item.symbol !== normalizedSymbol)].slice(0, 50),
        priceBySymbol: {
          ...prev.priceBySymbol,
          [normalizedSymbol]: ltp,
        },
      }));
    } catch (error) {
      set({
        bundleLoading: false,
        bundleError: error?.message || 'Failed to load stock bundle',
      });
      throw error;
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
      const [tradesResponse, portfolioResponse, signalsResponse] = await Promise.all([
        TradeService.getActive().catch(() => null),
        PortfolioService.getBalance().catch(() => null),
        SignalService.getActive().catch(() => null),
      ]);

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

      await Promise.all([
        get().loadSymbolCatalog().catch(() => null),
        get().loadSymbolBundle(get().selectedSymbol, get().selectedTimeframe).catch(() => null),
      ]);
    } catch { set({ isLoading: false }); }
  },
  
  executeTrade: async (signal) => {
    const state = get(); if (!state.systemStatus) throw new Error("API Offline");
    const tradeType = String(signal?.type || signal?.signal || 'BUY').toUpperCase();
    const signalSymbol = String(signal?.symbol || state.selectedSymbol || '').toUpperCase();
    const entryPrice = toNumber(signal?.price ?? signal?.currentPrice ?? state.priceBySymbol[signalSymbol], 0);
    const tp = toNumber(signal?.tp ?? signal?.target, entryPrice);
    const sl = toNumber(signal?.sl ?? signal?.stopLoss, entryPrice);

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
    const merged = hydrateSignalWithPrevious(
      normalized,
      previousBySymbol,
      s.priceBySymbol[normalized.symbol],
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
    const merged = hydrateSignalWithPrevious(
      normalized,
      previousBySymbol,
      s.priceBySymbol[normalized.symbol],
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
            ltp: close,
            price: close,
            close,
            high,
            low,
            open,
            volume,
          }
        : s.snapshot,
      priceBySymbol: {
        ...s.priceBySymbol,
        [normalizedSymbol]: close,
      },
      currentSignal: shouldUpdateSelected && s.currentSignal
        ? {
            ...s.currentSignal,
            price: close,
            currentPrice: close,
          }
        : s.currentSignal,
    };
  }),

  syncTradeEvents: (p) => set(s => ({ activeTrades: s.activeTrades.filter(t => t.id !== p.tradeId) })),

  updateAssetPrice: (sym, px) => set(s => {
    const symbol = String(sym || '').toUpperCase();
    const price = toNumber(px, null);
    if (!symbol || price === null) return s;

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

    return {
      activeTrades: updatedTrades,
      priceBySymbol: {
        ...s.priceBySymbol,
        [symbol]: price,
      },
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