import React from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Building2,
  Clock3,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Waves,
} from 'lucide-react';

import CandlestickChart from '../components/dashboard/CandlestickChart';
import SmartSearchBar from '../components/dashboard/SmartSearchBar';

const SIGNAL_VISUALS = {
  BUY: {
    title: 'Aggressive Long Bias',
    subtitle: 'Momentum and structure remain supportive.',
    icon: TrendingUp,
    accent: 'text-emerald-300',
    card: 'border-emerald-400/35 bg-gradient-to-br from-emerald-500/20 via-[#081219]/95 to-[#050B13]/95',
    progress: 'bg-emerald-300',
  },
  SELL: {
    title: 'Defensive Short Bias',
    subtitle: 'Price action shows downside pressure.',
    icon: TrendingDown,
    accent: 'text-rose-300',
    card: 'border-rose-400/35 bg-gradient-to-br from-rose-500/20 via-[#101019]/95 to-[#080A13]/95',
    progress: 'bg-rose-300',
  },
  HOLD: {
    title: 'Wait And Confirm',
    subtitle: 'Signal quality is mixed right now.',
    icon: Activity,
    accent: 'text-cyan-300',
    card: 'border-cyan-400/35 bg-gradient-to-br from-cyan-500/20 via-[#081219]/95 to-[#050B13]/95',
    progress: 'bg-cyan-300',
  },
};

const toFiniteNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatCurrency = (value) => {
  const amount = toFiniteNumber(value);
  return amount === null ? '--' : `INR ${amount.toFixed(2)}`;
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

const MobileMetricCard = ({ label, value, icon: Icon }) => (
  <article className="rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
    <div className="flex items-center justify-between gap-2 text-[11px] uppercase tracking-wider text-stockai-muted">
      <span>{label}</span>
      {Icon ? <Icon className="h-3.5 w-3.5 text-stockai-muted" /> : null}
    </div>
    <p className="mt-1.5 text-sm font-semibold text-white">{value}</p>
  </article>
);

const MobileWatchlistCard = ({
  symbol,
  companyName,
  latestPrice,
  latestChange,
  isActive,
  onSelectSymbol,
}) => {
  const changeValue = toFiniteNumber(latestChange);
  const isPositive = changeValue === null ? true : changeValue >= 0;

  return (
    <button
      type="button"
      onClick={() => onSelectSymbol(symbol)}
      className={`min-w-[164px] rounded-2xl border px-3 py-3 text-left transition-all ${
        isActive
          ? 'border-stockai-neon/70 bg-stockai-neon/10'
          : 'border-white/10 bg-[#08111A]/80 hover:border-white/30'
      }`}
    >
      <p className="truncate text-[13px] font-semibold text-white">{companyName}</p>
      <p className="mt-0.5 text-[11px] font-mono text-stockai-muted">{symbol}</p>
      <p className="mt-3 text-sm font-semibold text-white">{formatCurrency(latestPrice)}</p>
      <p className={`text-xs font-mono ${isPositive ? 'text-emerald-300' : 'text-rose-300'}`}>
        {formatSigned(latestChange)} ({formatChangePercent(latestPrice, latestChange)})
      </p>
    </button>
  );
};

const MobileLayoutEnhanced = ({
  selectedSymbol,
  selectedCompanyName,
  timeframe,
  timeframes,
  setTimeframe,
  handleSelectSymbol,
  watchlistSymbols,
  symbolMeta,
  priceBySymbol,
  changeBySymbol,
  displayPrice,
  displayChange,
  marketStatus,
  snapshot,
  candles,
  indicators,
  signal,
  signalReason,
  accuracyPct,
  target,
  stopLoss,
  rsi,
  volumeRatio,
  showSkeleton,
  isLoading,
  isFetching,
  error,
  onRetry,
  symbolCatalog,
  trendingSymbols,
}) => {
  const signalVisual = SIGNAL_VISUALS[signal] || SIGNAL_VISUALS.HOLD;
  const SignalIcon = signalVisual.icon;

  const liveChange = toFiniteNumber(displayChange);
  const isPositive = liveChange === null ? true : liveChange >= 0;
  const signalConfidence = accuracyPct === null ? 0 : Math.max(0, Math.min(100, accuracyPct));
  const rsiBar = Math.max(8, Math.min(100, rsi ?? 45));
  const liquidityBar = Math.max(10, Math.min(100, (volumeRatio ?? 1) * 50));
  const reasoningText = signalReason && signalReason.length > 165
    ? `${signalReason.slice(0, 162)}...`
    : (signalReason || 'Signal context unavailable.');

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-[#04070D] text-white">
      <div className="pointer-events-none absolute -top-24 -right-16 h-64 w-64 rounded-full bg-emerald-400/25 blur-3xl" />
      <div className="pointer-events-none absolute top-44 -left-16 h-72 w-72 rounded-full bg-cyan-400/20 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_0%,rgba(255,255,255,0.14),transparent_40%)]" />

      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#050A11]/80 backdrop-blur-xl">
        <div className="px-4 pb-4 pt-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-stockai-neon/30 bg-stockai-neon/10 shadow-[0_0_25px_rgba(0,255,159,0.2)]">
                <Activity className="h-5 w-5 text-stockai-neon" />
              </div>
              <div>
                <p className="text-sm font-black tracking-wide">StockAI Pro</p>
                <p className="text-[11px] text-stockai-muted">Mobile command deck</p>
              </div>
            </div>
            <span className="rounded-full border border-white/15 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-widest text-stockai-muted">
              {marketStatus}
            </span>
          </div>

          <SmartSearchBar
            selectedSymbol={selectedSymbol}
            onSelectSymbol={handleSelectSymbol}
            priceBySymbol={priceBySymbol}
            catalog={symbolCatalog}
            trendingSymbols={trendingSymbols}
          />

          <div className="flex gap-2 overflow-x-auto pb-1">
            {timeframes.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setTimeframe(item)}
                className={`shrink-0 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all ${
                  timeframe === item
                    ? 'border-stockai-neon/70 bg-stockai-neon/15 text-stockai-neon shadow-[0_0_18px_rgba(0,255,159,0.15)]'
                    : 'border-white/10 bg-[#080F17]/80 text-stockai-muted'
                }`}
              >
                {item.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="relative z-10 space-y-4 px-4 pb-24 pt-4">
        {error ? (
          <section className="flex items-center justify-between gap-3 rounded-2xl border border-rose-400/40 bg-rose-950/20 px-3.5 py-3">
            <div className="flex items-center gap-2 text-sm text-rose-200">
              <AlertTriangle className="h-4 w-4" />
              <span>Could not load bundle data.</span>
            </div>
            <button
              type="button"
              onClick={onRetry}
              className="rounded-lg bg-rose-400/90 px-3 py-1.5 text-xs font-semibold text-rose-950"
            >
              Retry
            </button>
          </section>
        ) : null}

        {showSkeleton ? (
          <div className="space-y-4 animate-pulse">
            <div className="h-48 rounded-3xl border border-white/10 bg-[#070F18]" />
            <div className="h-[430px] rounded-3xl border border-white/10 bg-[#070E16]" />
            <div className="h-56 rounded-3xl border border-white/10 bg-[#070E16]" />
          </div>
        ) : (
          <>
            <section className="rounded-3xl border border-white/15 bg-gradient-to-br from-[#0D1A2A]/90 via-[#08111B]/95 to-[#060D16]/95 p-4 shadow-[0_20px_45px_rgba(0,0,0,0.35)]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-[0.26em] text-stockai-muted">Live Market Pulse</p>
                  <h1 className="mt-2 truncate text-[26px] font-black leading-tight text-white">{selectedCompanyName}</h1>
                  <div className="mt-1.5 flex items-center gap-2 text-xs text-stockai-muted">
                    <Building2 className="h-3.5 w-3.5" />
                    <span className="font-mono">{selectedSymbol}</span>
                    <span>•</span>
                    <span>NSE</span>
                  </div>
                </div>

                <div className={`rounded-2xl border px-3 py-2 text-right ${
                  isPositive
                    ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300'
                    : 'border-rose-400/40 bg-rose-400/10 text-rose-300'
                }`}>
                  <p className="text-[10px] uppercase tracking-wider opacity-80">Change</p>
                  <p className="text-sm font-bold">{formatSigned(displayChange)}</p>
                  <p className="text-[11px] font-mono">{formatChangePercent(displayPrice, displayChange)}</p>
                </div>
              </div>

              <div className="mt-4 flex items-end justify-between gap-3">
                <p className="text-4xl font-black tracking-tight">{formatCurrency(displayPrice)}</p>
                <div className="text-right">
                  <p className="text-[10px] uppercase tracking-wider text-stockai-muted">Volume</p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {(toFiniteNumber(snapshot?.volume) ?? 0).toLocaleString('en-IN')}
                  </p>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <MobileMetricCard label="Session High" value={formatCurrency(snapshot?.high)} icon={TrendingUp} />
                <MobileMetricCard label="Session Low" value={formatCurrency(snapshot?.low)} icon={TrendingDown} />
              </div>
            </section>

            <section className="rounded-3xl border border-white/10 bg-[#060D15]/80 p-2 shadow-[0_15px_35px_rgba(0,0,0,0.28)]">
              <CandlestickChart
                candles={candles}
                symbol={selectedSymbol}
                timeframe={timeframe}
                indicators={indicators}
                isLoading={(isLoading || isFetching) && candles.length === 0}
              />
            </section>

            <section className={`relative overflow-hidden rounded-3xl border p-4 ${signalVisual.card}`}>
              <div className="pointer-events-none absolute -right-4 -top-4 opacity-25">
                <SignalIcon className="h-16 w-16" />
              </div>

              <p className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-stockai-muted">
                <Sparkles className="h-3.5 w-3.5 text-stockai-neon" />
                AI Signal Core
              </p>

              <h2 className={`text-2xl font-black ${signalVisual.accent}`}>{signalVisual.title}</h2>
              <p className="mt-1 text-xs text-stockai-muted">{signalVisual.subtitle}</p>

              <div className="mt-4 h-2 rounded-full bg-white/10">
                <div
                  className={`h-full rounded-full transition-all ${signalVisual.progress}`}
                  style={{ width: `${Math.max(10, signalConfidence)}%` }}
                />
              </div>
              <p className="mt-1.5 text-[11px] text-stockai-muted">
                Confidence: {accuracyPct === null ? 'N/A' : `${accuracyPct.toFixed(1)}%`}
              </p>

              <div className="mt-4 grid grid-cols-2 gap-2.5 text-sm">
                <article className="rounded-xl border border-white/10 bg-black/20 px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wider text-stockai-muted">Target</p>
                  <p className="mt-1 font-mono text-emerald-300">{formatCurrency(target)}</p>
                </article>
                <article className="rounded-xl border border-white/10 bg-black/20 px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wider text-stockai-muted">Dynamic Stop</p>
                  <p className="mt-1 font-mono text-rose-300">{formatCurrency(stopLoss)}</p>
                </article>
              </div>

              <p className="mt-3 text-xs leading-relaxed text-stockai-muted">{reasoningText}</p>
            </section>

            <section className="rounded-3xl border border-white/10 bg-[#08111A]/90 p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-[0.2em] text-stockai-muted">Risk Context</p>
                <Waves className="h-4 w-4 text-stockai-neon" />
              </div>

              <div className="space-y-3">
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-stockai-muted">RSI Volatility</span>
                    <span className="font-mono text-yellow-300">{rsi === null ? '--' : rsi.toFixed(2)}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-yellow-300 transition-all" style={{ width: `${rsiBar}%` }} />
                  </div>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-stockai-muted">Liquidity Pressure</span>
                    <span className="font-mono text-stockai-neon">{(volumeRatio ?? 1) >= 1 ? 'High' : 'Moderate'}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-stockai-neon transition-all" style={{ width: `${liquidityBar}%` }} />
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-3xl border border-white/10 bg-[#08111A]/90 p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-[0.2em] text-stockai-muted">Watchlist</p>
                <span className="text-[11px] text-stockai-muted">{watchlistSymbols.length} symbols</span>
              </div>

              <div className="flex gap-2 overflow-x-auto pb-1">
                {watchlistSymbols.map((symbol) => (
                  <MobileWatchlistCard
                    key={symbol}
                    symbol={symbol}
                    companyName={symbolMeta[symbol]?.name || symbol}
                    latestPrice={priceBySymbol[symbol]}
                    latestChange={changeBySymbol[symbol]}
                    isActive={symbol === selectedSymbol}
                    onSelectSymbol={handleSelectSymbol}
                  />
                ))}
              </div>
            </section>

            <button
              type="button"
              className="w-full rounded-2xl border border-stockai-neon/35 bg-stockai-neon/10 px-4 py-3.5 text-sm font-semibold text-stockai-neon transition-all hover:bg-stockai-neon/20"
            >
              <span className="inline-flex items-center gap-2">
                <Bot className="h-4 w-4" />
                Launch Trading Copilot
              </span>
            </button>
          </>
        )}
      </main>

      <div className="fixed bottom-3 left-3 right-3 z-40 rounded-2xl border border-white/10 bg-[#050A11]/90 px-4 py-2.5 backdrop-blur-xl shadow-[0_14px_30px_rgba(0,0,0,0.45)]">
        <div className="flex items-center justify-between text-xs">
          <span className="inline-flex items-center gap-1.5 text-stockai-muted">
            <Clock3 className="h-3.5 w-3.5" />
            Refresh every 15s
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/35 bg-emerald-400/10 px-2 py-0.5 font-semibold text-emerald-300">
            Live
          </span>
        </div>
      </div>
    </div>
  );
};

export default MobileLayoutEnhanced;
