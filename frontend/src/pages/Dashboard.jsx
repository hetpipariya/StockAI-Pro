import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Bell,
  Bot,
  Building2,
  Clock3,
  Sparkles,
  TrendingDown,
  TrendingUp,
  User,
  Waves,
} from 'lucide-react';

import CandlestickChart from '../components/dashboard/CandlestickChart';
import SmartSearchBar from '../components/dashboard/SmartSearchBar';
import { buildLiveWebSocketUrl } from '../config/api';
import MobileLayoutEnhanced from '../layouts/MobileLayoutEnhanced';
import { fetchMarketSymbols, getBundle } from '../lib/api';

const DEFAULT_WATCHLIST_SYMBOLS = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '1d'];
const MOBILE_BREAKPOINT_QUERY = '(max-width: 1023px)';

const HORIZON_BY_INTERVAL = {
  '1m': '15m',
  '5m': '15m',
  '15m': '1h',
  '1h': '1d',
  '1d': '1d',
};

const SIGNAL_META = {
  BUY: {
    title: 'Momentum Long',
    subtitle: 'Bullish trend structure detected',
    icon: TrendingUp,
    card: 'border-emerald-400/35 bg-gradient-to-b from-emerald-500/15 to-[#0A1119]/90',
    accent: 'text-emerald-300',
    button: 'bg-emerald-400 text-emerald-950',
  },
  SELL: {
    title: 'Defensive Short',
    subtitle: 'Bearish structure with downside pressure',
    icon: TrendingDown,
    card: 'border-rose-400/35 bg-gradient-to-b from-rose-500/15 to-[#0A1119]/90',
    accent: 'text-rose-300',
    button: 'bg-rose-400 text-rose-950',
  },
  HOLD: {
    title: 'Range Guard',
    subtitle: 'Wait for cleaner setup',
    icon: Activity,
    card: 'border-cyan-400/35 bg-gradient-to-b from-cyan-500/15 to-[#0A1119]/90',
    accent: 'text-cyan-300',
    button: 'bg-stockai-neon text-black',
  },
};

const toFiniteNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatCurrency = (value) => {
  const amount = toFiniteNumber(value);
  return amount === null ? '--' : `₹ ${amount.toFixed(2)}`;
};

const formatSigned = (value) => {
  const amount = toFiniteNumber(value);
  if (amount === null) return '--';
  const sign = amount >= 0 ? '+' : '-';
  return `${sign}${Math.abs(amount).toFixed(2)}`;
};

const formatChangePercent = (price, change) => {
  const safePrice = toFiniteNumber(price);
  const safeChange = toFiniteNumber(change);
  if (safePrice === null || safePrice === 0 || safeChange === null) return '--';

  const pct = (safeChange / safePrice) * 100;
  const sign = pct >= 0 ? '+' : '-';
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
};

const uniqueSymbols = (symbols) => {
  const seen = new Set();
  const out = [];

  symbols.forEach((item) => {
    const value = String(item || '').trim().toUpperCase();
    if (!value || seen.has(value)) return;
    seen.add(value);
    out.push(value);
  });

  return out;
};

const WatchlistItem = React.memo(function WatchlistItem({
  symbol,
  companyName,
  active,
  latestPrice,
  latestChange,
  onSelect,
}) {
  const changeValue = toFiniteNumber(latestChange);
  const isPositive = changeValue === null ? true : changeValue >= 0;

  return (
    <button
      type="button"
      onClick={() => onSelect(symbol)}
      className={`w-full rounded-2xl border px-3 py-3 text-left transition-all ${
        active
          ? 'border-stockai-neon/60 bg-stockai-neon/10'
          : 'border-white/5 bg-[#070D15] hover:border-white/20 hover:bg-white/[0.03]'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-white truncate">{companyName}</p>
          <p className="text-[11px] text-stockai-muted font-mono mt-0.5">{symbol}</p>
          <p className="text-xs text-stockai-muted font-mono mt-2">{formatCurrency(latestPrice)}</p>
        </div>
        <div className="text-right shrink-0 pt-1">
          <p className={`text-sm font-semibold ${isPositive ? 'text-emerald-300' : 'text-rose-300'}`}>
            {formatSigned(latestChange)}
          </p>
          <p className={`text-[11px] font-mono ${isPositive ? 'text-emerald-300/90' : 'text-rose-300/90'}`}>
            {formatChangePercent(latestPrice, latestChange)}
          </p>
        </div>
      </div>
    </button>
  );
});

const StatCard = ({ label, value, subvalue, tone = 'neutral', icon: Icon }) => {
  const toneClass = {
    positive: 'text-emerald-300 border-emerald-400/30',
    negative: 'text-rose-300 border-rose-400/30',
    neutral: 'text-white border-white/10',
  }[tone] || 'text-white border-white/10';

  return (
    <div className={`rounded-2xl border bg-[#0A1119] px-4 py-3 ${toneClass}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] uppercase tracking-widest text-stockai-muted">{label}</p>
        {Icon ? <Icon className="w-4 h-4 text-stockai-muted" /> : null}
      </div>
      <p className="mt-2 text-xl font-bold text-white">{value}</p>
      {subvalue ? <p className="mt-1 text-xs font-mono text-stockai-muted">{subvalue}</p> : null}
    </div>
  );
};

const SignalPanel = ({ signal, target, stopLoss, reason, loading, accuracyPct }) => {
  const style = SIGNAL_META[signal] || SIGNAL_META.HOLD;
  const Icon = style.icon;

  return (
    <div className={`rounded-2xl border p-5 relative overflow-hidden ${style.card}`}>
      <div className="absolute top-4 right-4 opacity-20">
        <Icon className={`w-12 h-12 ${style.accent}`} />
      </div>

      <div className="text-xs uppercase tracking-widest text-stockai-muted mb-2 flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-stockai-neon" /> AI Signal Core
      </div>

      {loading ? (
        <div className="space-y-3">
          <div className="h-6 w-2/3 rounded bg-white/10 animate-pulse" />
          <div className="h-4 w-1/2 rounded bg-white/10 animate-pulse" />
          <div className="h-20 rounded-xl bg-white/5 animate-pulse" />
        </div>
      ) : (
        <>
          <p className={`text-2xl font-extrabold ${style.accent}`}>{style.title}</p>
          <p className="text-xs text-stockai-muted mb-4">{style.subtitle}</p>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between border-b border-white/10 pb-2">
              <span className="text-stockai-muted">Target</span>
              <span className="font-mono text-white">{formatCurrency(target)}</span>
            </div>
            <div className="flex justify-between border-b border-white/10 pb-2">
              <span className="text-stockai-muted">Dynamic Stop</span>
              <span className="font-mono text-rose-300">{formatCurrency(stopLoss)}</span>
            </div>
            <div className="flex justify-between border-b border-white/10 pb-2">
              <span className="text-stockai-muted">Accuracy</span>
              <span className="font-mono text-stockai-neon">{accuracyPct === null ? 'N/A' : `${accuracyPct.toFixed(1)}%`}</span>
            </div>
          </div>

          <p className="text-xs text-stockai-muted mt-4 leading-relaxed">
            {reason || 'Signal context unavailable.'}
          </p>

          <button type="button" className={`w-full mt-4 py-2.5 rounded-xl font-bold transition-all ${style.button}`}>
            Execute Paper Trade
          </button>
        </>
      )}
    </div>
  );
};

const Dashboard = () => {
  const [selectedSymbol, setSelectedSymbol] = useState('RELIANCE');
  const [timeframe, setTimeframe] = useState('1m');
  const [symbolMetaMap, setSymbolMetaMap] = useState({});
  const [toastMessage, setToastMessage] = useState('');
  const [priceBySymbol, setPriceBySymbol] = useState({});
  const [changeBySymbol, setChangeBySymbol] = useState({});
  const [isMobileView, setIsMobileView] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(MOBILE_BREAKPOINT_QUERY).matches;
  });

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const shouldReconnectRef = useRef(true);
  const reconnectBackoffMsRef = useRef(1000);
  const trackedSymbolsRef = useRef([]);
  const closeBySymbolRef = useRef({});

  const { data: symbolCatalog = [] } = useQuery({
    queryKey: ['marketSymbols', 500],
    queryFn: () => fetchMarketSymbols(500),
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: false,
    retry: 2,
  });

  const symbolMetaFromCatalog = useMemo(() => {
    const map = {};
    (Array.isArray(symbolCatalog) ? symbolCatalog : []).forEach((item) => {
      const symbol = String(item?.symbol || '').trim().toUpperCase();
      if (!symbol) return;
      map[symbol] = {
        symbol,
        name: String(item?.name || symbol),
        type: String(item?.type || 'stock').toLowerCase(),
        sector: String(item?.sector || ''),
      };
    });
    return map;
  }, [symbolCatalog]);

  const symbolMeta = useMemo(() => {
    return {
      ...symbolMetaFromCatalog,
      ...symbolMetaMap,
    };
  }, [symbolMetaFromCatalog, symbolMetaMap]);

  const stockUniverse = useMemo(() => {
    const rows = Object.values(symbolMetaFromCatalog);
    const stockRows = rows.filter((item) => item.type !== 'index');
    const preferred = stockRows.length ? stockRows : rows;
    const extracted = preferred.map((item) => item.symbol);
    return extracted.length ? extracted : DEFAULT_WATCHLIST_SYMBOLS;
  }, [symbolMetaFromCatalog]);

  const watchlistSymbols = useMemo(() => {
    return uniqueSymbols([selectedSymbol, ...stockUniverse]).slice(0, 10);
  }, [selectedSymbol, stockUniverse]);

  const trendingSymbols = useMemo(() => {
    return uniqueSymbols([selectedSymbol, ...stockUniverse]).slice(0, 6);
  }, [selectedSymbol, stockUniverse]);

  const trackedSymbols = useMemo(() => {
    return uniqueSymbols([selectedSymbol, ...watchlistSymbols, ...trendingSymbols]);
  }, [selectedSymbol, watchlistSymbols, trendingSymbols]);

  useEffect(() => {
    trackedSymbolsRef.current = trackedSymbols;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && trackedSymbols.length) {
      ws.send(JSON.stringify({ action: 'subscribe', symbols: trackedSymbols }));
    }
  }, [trackedSymbols]);

  useEffect(() => {
    if (selectedSymbol) return;
    if (!stockUniverse.length) return;
    setSelectedSymbol(stockUniverse[0]);
  }, [selectedSymbol, stockUniverse]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;

    const mediaQuery = window.matchMedia(MOBILE_BREAKPOINT_QUERY);
    const syncView = (event) => {
      setIsMobileView(event.matches);
    };

    setIsMobileView(mediaQuery.matches);

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', syncView);
      return () => mediaQuery.removeEventListener('change', syncView);
    }

    mediaQuery.addListener(syncView);
    return () => mediaQuery.removeListener(syncView);
  }, []);

  const {
    data: bundleData,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: ['stockBundle', selectedSymbol, timeframe],
    queryFn: () => getBundle(selectedSymbol, {
      interval: timeframe,
      horizon: HORIZON_BY_INTERVAL[timeframe] || '15m',
      limit: 200,
    }),
    staleTime: 45_000,
    gcTime: 300_000,
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    placeholderData: (previousData) => previousData,
    enabled: Boolean(selectedSymbol),
  });

  const candles = useMemo(
    () => bundleData?.history?.candles || bundleData?.candles || [],
    [bundleData],
  );
  const indicators = useMemo(() => bundleData?.indicators || {}, [bundleData]);
  const snapshot = useMemo(() => bundleData?.snapshot || {}, [bundleData]);
  const prediction = useMemo(() => bundleData?.prediction || {}, [bundleData]);

  const bundlePrice = toFiniteNumber(snapshot?.price ?? snapshot?.ltp);
  const bundleChange = toFiniteNumber(snapshot?.change);

  const displayPrice = toFiniteNumber(priceBySymbol[selectedSymbol]) ?? bundlePrice;
  const displayChange = toFiniteNumber(changeBySymbol[selectedSymbol]) ?? bundleChange;

  useEffect(() => {
    if (!selectedSymbol || bundlePrice === null) return;

    setPriceBySymbol((previous) => ({
      ...previous,
      [selectedSymbol]: bundlePrice,
    }));

    const close = toFiniteNumber(snapshot?.close);
    if (close !== null) {
      closeBySymbolRef.current[selectedSymbol] = close;
    }
  }, [bundlePrice, selectedSymbol, snapshot?.close]);

  useEffect(() => {
    if (!selectedSymbol || bundleChange === null) return;
    setChangeBySymbol((previous) => ({
      ...previous,
      [selectedSymbol]: bundleChange,
    }));
  }, [bundleChange, selectedSymbol]);

  useEffect(() => {
    shouldReconnectRef.current = true;

    const connect = () => {
      if (!shouldReconnectRef.current) return;

      const token = localStorage.getItem('stockai_token') || localStorage.getItem('stockai_access_token') || '';
      if (!token) return;

      let ws;
      try {
        ws = new WebSocket(buildLiveWebSocketUrl(token));
      } catch {
        return;
      }

      wsRef.current = ws;

      ws.onopen = () => {
        reconnectBackoffMsRef.current = 1000;
        const symbols = trackedSymbolsRef.current;
        if (symbols.length) {
          ws.send(JSON.stringify({ action: 'subscribe', symbols }));
        }
      };

      ws.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        if (!message || typeof message !== 'object') return;

        if (message.type === 'tick') {
          const symbol = String(message.symbol || '').trim().toUpperCase();
          const ltp = toFiniteNumber(message.ltp);
          if (!symbol || ltp === null) return;

          const reportedChange = toFiniteNumber(message.change);

          setPriceBySymbol((previous) => ({
            ...previous,
            [symbol]: ltp,
          }));

          setChangeBySymbol((previous) => {
            const knownClose = toFiniteNumber(closeBySymbolRef.current[symbol]);
            const computed = knownClose === null ? null : ltp - knownClose;
            const nextChange = reportedChange ?? computed ?? toFiniteNumber(previous[symbol]) ?? 0;
            return {
              ...previous,
              [symbol]: nextChange,
            };
          });

          return;
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (!shouldReconnectRef.current) return;
        const nextDelay = reconnectBackoffMsRef.current;
        reconnectBackoffMsRef.current = Math.min(reconnectBackoffMsRef.current * 2, 15000);
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = setTimeout(connect, nextDelay);
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          // Ignore socket close errors.
        }
      };
    };

    connect();

    return () => {
      shouldReconnectRef.current = false;
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // Ignore socket close errors.
        }
        wsRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!error) return undefined;

    setToastMessage('Unable to fetch market data');
    const timer = setTimeout(() => setToastMessage(''), 2800);
    return () => clearTimeout(timer);
  }, [error]);

  const handleSelectSymbol = useCallback((nextSymbol, stockMeta) => {
    const normalizedSymbol = String(nextSymbol || '').trim().toUpperCase();
    if (!normalizedSymbol) return;

    if (stockMeta && typeof stockMeta === 'object') {
      setSymbolMetaMap((previous) => ({
        ...previous,
        [normalizedSymbol]: {
          symbol: normalizedSymbol,
          name: String(stockMeta.name || normalizedSymbol),
          type: 'stock',
          sector: String(stockMeta.sector || ''),
        },
      }));
    }

    setSelectedSymbol(normalizedSymbol);
  }, []);

  const selectedCompanyName = symbolMeta[selectedSymbol]?.name || selectedSymbol;
  const signal = String(prediction.signal || 'HOLD').toUpperCase();
  const signalReason = String(prediction.reasoning || prediction.reason || prediction.explanation || '').trim();
  const target = toFiniteNumber(prediction.target);
  const stopLoss = toFiniteNumber(prediction.stop_loss);
  const marketStatus = String(bundleData?.market_status || snapshot?.market_status || 'UNKNOWN');

  const accuracyPct = useMemo(() => {
    const rawPct = toFiniteNumber(prediction.confidence_pct);
    const rawConfidence = toFiniteNumber(prediction.confidence);

    let normalized = null;
    if (rawPct !== null) {
      normalized = rawPct;
    } else if (rawConfidence !== null) {
      normalized = rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence;
    }

    const noConfidence = normalized === null || normalized <= 0;
    const unavailableReason = /unavailable|insufficient|timed out|failed/i.test(signalReason);

    if (noConfidence && unavailableReason) {
      return null;
    }

    if (normalized === null) return null;
    return Math.max(0, Math.min(100, normalized));
  }, [prediction.confidence, prediction.confidence_pct, signalReason, marketStatus]);

  const rsi = toFiniteNumber(indicators.rsi);
  const volumeRatio = toFiniteNumber(prediction.volume_ratio) ?? toFiniteNumber(indicators.volume_ratio);
  const hasBundleData = Boolean(bundleData && typeof bundleData === 'object');
  const showSkeleton = !hasBundleData && (isLoading || isFetching);

  if (isMobileView) {
    return (
      <>
        <MobileLayoutEnhanced
          selectedSymbol={selectedSymbol}
          selectedCompanyName={selectedCompanyName}
          timeframe={timeframe}
          timeframes={TIMEFRAMES}
          setTimeframe={setTimeframe}
          handleSelectSymbol={handleSelectSymbol}
          watchlistSymbols={watchlistSymbols}
          symbolMeta={symbolMeta}
          priceBySymbol={priceBySymbol}
          changeBySymbol={changeBySymbol}
          displayPrice={displayPrice}
          displayChange={displayChange}
          marketStatus={marketStatus}
          snapshot={snapshot}
          candles={candles}
          indicators={indicators}
          signal={signal}
          signalReason={signalReason}
          accuracyPct={accuracyPct}
          target={target}
          stopLoss={stopLoss}
          rsi={rsi}
          volumeRatio={volumeRatio}
          showSkeleton={showSkeleton}
          isLoading={isLoading}
          isFetching={isFetching}
          error={error}
          onRetry={refetch}
          symbolCatalog={symbolCatalog}
          trendingSymbols={trendingSymbols}
        />

        {toastMessage ? (
          <div className="fixed top-5 right-5 z-[90] px-4 py-2 rounded-xl border border-rose-400/50 bg-[#130a11]/95 text-rose-300 text-sm shadow-2xl">
            {toastMessage}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="min-h-screen bg-stockai-bg text-white">
      <header className="sticky top-0 z-20 border-b border-white/5 bg-[#050A11]/95 backdrop-blur-md">
        <div className="px-4 md:px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <Activity className="w-6 h-6 text-stockai-neon" />
              <p className="text-2xl font-bold">StockAI<span className="text-stockai-neon">Pro</span></p>
            </div>

            <div className="flex items-center gap-4 text-stockai-muted">
              <Bell className="w-4 h-4" />
              <div className="w-8 h-8 rounded-full border border-stockai-neon/40 bg-stockai-neon/15 flex items-center justify-center">
                <User className="w-4 h-4 text-stockai-neon" />
              </div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 xl:grid-cols-[1fr_auto] gap-4 items-start">
            <div>
              <SmartSearchBar
                selectedSymbol={selectedSymbol}
                onSelectSymbol={handleSelectSymbol}
                priceBySymbol={priceBySymbol}
                catalog={symbolCatalog}
                trendingSymbols={trendingSymbols}
              />

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[11px] uppercase tracking-widest text-stockai-muted">Trending</span>
                {trendingSymbols.map((symbol) => {
                  const companyName = symbolMeta[symbol]?.name || symbol;
                  return (
                    <button
                      key={symbol}
                      type="button"
                      onClick={() => handleSelectSymbol(symbol)}
                      className={`px-3 py-1.5 rounded-full text-xs border transition-all max-w-[180px] truncate ${
                        selectedSymbol === symbol
                          ? 'border-stockai-neon/70 bg-stockai-neon/10 text-stockai-neon'
                          : 'border-white/10 text-stockai-muted hover:border-white/30 hover:text-white'
                      }`}
                      title={`${companyName} (${symbol})`}
                    >
                      {companyName}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {TIMEFRAMES.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setTimeframe(item)}
                  className={`px-3 py-2 rounded-xl text-xs border font-semibold transition-all ${
                    timeframe === item
                      ? 'border-stockai-neon/70 bg-stockai-neon/10 text-stockai-neon'
                      : 'border-white/10 text-stockai-muted hover:text-white hover:border-white/30'
                  }`}
                >
                  {item.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main className="px-4 md:px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-2xl border border-rose-400/40 bg-rose-950/20 px-4 py-3 flex items-center justify-between gap-3">
            <p className="text-sm text-rose-200">Failed to load bundle data. Please retry.</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg bg-rose-400/90 text-rose-950 px-3 py-1.5 text-xs font-semibold hover:bg-rose-300 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : null}

        {showSkeleton ? (
          <div className="grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_340px] gap-5 min-h-[calc(100vh-170px)] animate-pulse">
            <div className="rounded-3xl border border-white/10 bg-[#070D15] p-4" />
            <div className="rounded-3xl border border-white/10 bg-[#070E16] p-4 min-h-[520px]" />
            <div className="rounded-3xl border border-white/10 bg-[#070E16] p-4" />
          </div>
        ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_340px] gap-5 min-h-[calc(100vh-170px)]">
          <aside className="rounded-3xl border border-white/10 bg-[#070D15] p-4 overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <p className="text-xs uppercase tracking-widest text-stockai-muted">Watchlist</p>
              <span className="text-xs text-stockai-muted">{watchlistSymbols.length} symbols</span>
            </div>

            <div className="space-y-2 overflow-y-auto pr-1">
              {watchlistSymbols.map((symbol) => (
                <WatchlistItem
                  key={symbol}
                  symbol={symbol}
                  companyName={symbolMeta[symbol]?.name || symbol}
                  active={symbol === selectedSymbol}
                  latestPrice={priceBySymbol[symbol]}
                  latestChange={changeBySymbol[symbol]}
                  onSelect={handleSelectSymbol}
                />
              ))}
            </div>
          </aside>

          <section className="min-w-0 flex flex-col gap-4">
            <div className="rounded-3xl border border-white/10 bg-[#070E16] p-5">
              <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-3">
                <div>
                  <p className="text-3xl font-extrabold text-white leading-tight">{selectedCompanyName}</p>
                  <div className="mt-2 flex items-center gap-2 text-xs text-stockai-muted">
                    <Building2 className="w-3.5 h-3.5" />
                    <span className="font-mono">{selectedSymbol}</span>
                    <span>•</span>
                    <span>NSE EQUITY</span>
                    <span>•</span>
                    <span className="uppercase">{marketStatus}</span>
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-4xl font-bold text-white">{formatCurrency(displayPrice)}</p>
                  <p className={`text-lg font-semibold ${toFiniteNumber(displayChange) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {formatSigned(displayChange)} ({formatChangePercent(displayPrice, displayChange)})
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-5">
                <StatCard
                  label="Volume"
                  value={(toFiniteNumber(snapshot?.volume) ?? 0).toLocaleString('en-IN')}
                  icon={Waves}
                />
                <StatCard
                  label="Session High"
                  value={formatCurrency(snapshot?.high)}
                  icon={TrendingUp}
                />
                <StatCard
                  label="Session Low"
                  value={formatCurrency(snapshot?.low)}
                  icon={TrendingDown}
                />
              </div>
            </div>

            <div className="flex-1 min-h-0">
              <CandlestickChart
                candles={candles}
                symbol={selectedSymbol}
                timeframe={timeframe}
                indicators={indicators}
                isLoading={(isLoading || isFetching) && candles.length === 0}
              />
            </div>
          </section>

          <aside className="min-w-0 flex flex-col gap-4">
            <SignalPanel
              signal={signal}
              target={target}
              stopLoss={stopLoss}
              reason={signalReason}
              accuracyPct={accuracyPct}
              loading={isLoading && candles.length === 0}
            />

            <div className="rounded-2xl border border-white/10 bg-[#070E16] p-5">
              <p className="text-xs uppercase tracking-widest text-stockai-muted mb-4">Risk Context</p>

              <div className="space-y-4">
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-stockai-muted">Volatility (RSI)</span>
                    <span className="text-yellow-300">{rsi === null ? '--' : rsi.toFixed(2)}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-yellow-400 transition-all"
                      style={{ width: `${Math.max(8, Math.min(100, rsi ?? 40))}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-stockai-muted">Liquidity</span>
                    <span className="text-stockai-neon">{(volumeRatio ?? 1) >= 1 ? 'High' : 'Moderate'}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-stockai-neon transition-all"
                      style={{ width: `${Math.max(10, Math.min(100, (volumeRatio ?? 1) * 50))}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#070E16] p-5">
              <p className="text-xs uppercase tracking-widest text-stockai-muted mb-4">AI Assistant</p>
              <button
                type="button"
                className="w-full flex items-center justify-center gap-2 rounded-xl border border-stockai-neon/30 bg-stockai-neon/10 text-stockai-neon py-2.5 hover:bg-stockai-neon/20 transition-all"
              >
                <Bot className="w-4 h-4" /> Open Trading Copilot
              </button>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#070E16] px-4 py-3 flex items-center gap-2 text-xs text-stockai-muted">
              <Clock3 className="w-4 h-4" /> Live refresh every 15 seconds. Search any company to load full bundle data.
            </div>
          </aside>
        </div>
        )}
      </main>

      {toastMessage ? (
        <div className="fixed top-5 right-5 z-[90] px-4 py-2 rounded-xl border border-rose-400/50 bg-[#130a11]/95 text-rose-300 text-sm shadow-2xl">
          {toastMessage}
        </div>
      ) : null}
    </div>
  );
};

export default Dashboard;
