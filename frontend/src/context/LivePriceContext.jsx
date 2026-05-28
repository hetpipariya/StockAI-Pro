import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useStore } from '../store/useStore.js';
import { LATENCY_LIVE_MS, LATENCY_MAX_MS } from '../api/requestGate.js';

const LivePriceContext = createContext(null);

const SOURCE = {
  WS: 'WS',
  UNKNOWN: 'UNKNOWN',
};

const SOURCE_PRIORITY = {
  [SOURCE.WS]: 3,
  [SOURCE.UNKNOWN]: 1,
};

const HEALTH = {
  LIVE: 'LIVE',
  DELAYED: 'DELAYED',
  STALE: 'STALE',
};

const toFiniteNumber = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalizeSource = (value) => {
  const raw = String(value || '').trim().toUpperCase();
  if (raw === 'WS' || raw === 'WEBSOCKET') return SOURCE.WS;
  return SOURCE.UNKNOWN;
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

const isWsConnected = (status) => String(status || '').toUpperCase() === 'CONNECTED';

const buildInitialState = (symbol, connectionStatus) => ({
  symbol,
  currentPrice: null,
  lastValidPrice: null,
  lastUpdatedTimestamp: 0,
  dataSource: SOURCE.UNKNOWN,
  connectionStatus,
});

export function LivePriceProvider({ children }) {
  const selectedSymbol = useStore((state) => state.selectedSymbol);
  const livePriceBySymbol = useStore((state) => state.livePriceBySymbol);
  const connectionStatus = useStore((state) => state.connectionStatus);
  const liveLatencyMs = useStore((state) => state.liveLatencyMs);
  const markRealtimeStale = useStore((state) => state.markRealtimeStale);

  const [livePriceState, setLivePriceState] = useState(() => buildInitialState(selectedSymbol, connectionStatus));
  const [clockMs, setClockMs] = useState(() => Date.now());
  const latestStateRef = useRef(livePriceState);
  const selectionRef = useRef({ symbol: selectedSymbol });

  useEffect(() => {
    const intervalId = setInterval(() => {
      setClockMs(Date.now());
    }, 500);
    return () => clearInterval(intervalId);
  }, []);

  useEffect(() => {
    selectionRef.current = {
      symbol: selectedSymbol,
    };
  }, [selectedSymbol]);

  const commitCandidate = useCallback((candidate) => {
    if (!candidate) return;

    const activeSymbol = selectionRef.current.symbol;
    if (String(candidate.symbol || '').toUpperCase() !== String(activeSymbol || '').toUpperCase()) {
      return;
    }

    const previous = latestStateRef.current;
    const previousTimestamp = parseTimestampMs(previous?.lastUpdatedTimestamp, 0);
    const nextTimestamp = parseTimestampMs(candidate.lastUpdatedTimestamp, Date.now());
    const previousSource = normalizeSource(previous?.dataSource);
    const nextSource = normalizeSource(candidate.dataSource);
    const latencyMs = Math.max(0, Date.now() - nextTimestamp);

    if (nextSource !== SOURCE.WS) {
      return;
    }

    if (latencyMs > LATENCY_MAX_MS) {
      markRealtimeStale(latencyMs, 'NO LIVE DATA');
      return;
    }

    if (nextTimestamp < previousTimestamp) {
      return;
    }

    if (nextTimestamp === previousTimestamp) {
      const nextPriority = SOURCE_PRIORITY[nextSource] || 0;
      const previousPriority = SOURCE_PRIORITY[previousSource] || 0;
      if (nextPriority < previousPriority) {
        return;
      }
    }

    const incomingPrice = toFiniteNumber(candidate.currentPrice, null);
    const safePrice = incomingPrice !== null && incomingPrice > 0
      ? incomingPrice
      : toFiniteNumber(previous?.lastValidPrice ?? previous?.currentPrice, null);

    if (safePrice === null) {
      return;
    }

    const nextState = {
      symbol: activeSymbol,
      currentPrice: safePrice,
      lastValidPrice: safePrice,
      lastUpdatedTimestamp: nextTimestamp,
      dataSource: nextSource,
      latencyMs,
      connectionStatus,
    };

    const unchanged = previous
      && previous.currentPrice === nextState.currentPrice
      && previous.lastUpdatedTimestamp === nextState.lastUpdatedTimestamp
      && previous.dataSource === nextState.dataSource
      && previous.connectionStatus === nextState.connectionStatus
      && previous.symbol === nextState.symbol;

    if (unchanged) {
      return;
    }

    latestStateRef.current = nextState;
    setLivePriceState(nextState);
  }, [connectionStatus]);

  useEffect(() => {
    const nextState = buildInitialState(selectedSymbol, connectionStatus);
    latestStateRef.current = nextState;
    setLivePriceState(nextState);
  }, [selectedSymbol]);

  useEffect(() => {
    const symbolState = livePriceBySymbol?.[selectedSymbol];
    if (!symbolState) return;

    commitCandidate({
      symbol: selectedSymbol,
      currentPrice: symbolState.currentPrice,
      lastUpdatedTimestamp: symbolState.lastUpdatedTimestamp,
      dataSource: symbolState.dataSource,
    });
  }, [commitCandidate, livePriceBySymbol, selectedSymbol]);

  const latency = livePriceState.lastUpdatedTimestamp
    ? Math.max(0, clockMs - livePriceState.lastUpdatedTimestamp)
    : null;

  const health = useMemo(() => {
    const status = String(connectionStatus || '').toUpperCase();
    if (!isWsConnected(status)) {
      return HEALTH.STALE;
    }

    const effectiveLatency = toFiniteNumber(liveLatencyMs, latency);
    if (effectiveLatency === null) {
      return HEALTH.STALE;
    }
    if (effectiveLatency <= LATENCY_LIVE_MS) {
      return HEALTH.LIVE;
    }
    if (effectiveLatency <= LATENCY_MAX_MS) {
      return HEALTH.DELAYED;
    }
    return HEALTH.STALE;
  }, [connectionStatus, latency, liveLatencyMs]);

  const value = useMemo(() => ({
    symbol: selectedSymbol,
    currentPrice: livePriceState.currentPrice,
    lastUpdatedTimestamp: livePriceState.lastUpdatedTimestamp,
    dataSource: livePriceState.dataSource,
    latency,
    health,
    canTrade: health !== HEALTH.STALE,
    noLiveData: health === HEALTH.STALE,
    connectionStatus,
    isWsConnected: isWsConnected(connectionStatus),
  }), [connectionStatus, health, latency, livePriceState, selectedSymbol]);

  return (
    <LivePriceContext.Provider value={value}>
      {children}
    </LivePriceContext.Provider>
  );
}

export function useLivePrice() {
  const context = useContext(LivePriceContext);
  if (!context) {
    throw new Error('useLivePrice must be used within LivePriceProvider');
  }
  return context;
}
