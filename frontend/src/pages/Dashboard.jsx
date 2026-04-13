import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { useStore } from '../store/useStore';
import { useToast } from '../components/Toast';
import { Card, Badge, Button } from '../components/ui';
import SmartSearchBar from '../components/dashboard/SmartSearchBar';
import CandlestickChart from '../components/dashboard/CandlestickChart';
import KpiCards from '../components/dashboard/KpiCards';
import TopMovers from '../components/dashboard/TopMovers';
import { wsManager } from '../api/websocket.js';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '1d'];
const TRENDING_SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK'];

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const toFinite = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatOptionalCurrency = (value) => {
  const parsed = toFinite(value);
  if (parsed === null || parsed <= 0) return '--';
  return `₹${parsed.toFixed(2)}`;
};

const formatOptionalPercent = (value) => {
  const parsed = toFinite(value);
  if (parsed === null || parsed <= 0) return '--';
  return `${parsed.toFixed(1)}%`;
};

const signalVariant = (signal) => {
  const value = String(signal || '').toUpperCase();
  if (value === 'BUY') return 'buy';
  if (value === 'SELL') return 'sell';
  return 'info';
};

export default function Dashboard() {
  const { showToast } = useToast();

  const {
    balance,
    todaysPnL,
    winRate,
    activeTrades,
    selectedSymbol,
    selectedTimeframe,
    symbolCatalog,
    priceBySymbol,
    currentSignal,
    candles,
    indicators,
    bundleLoading,
    bundleError,
    loadSymbolCatalog,
    loadSymbolBundle,
    selectTimeframe,
  } = useStore();

  const autoLoadAttemptsRef = useRef(new Set());
  const selectedSignalSymbol = String(currentSignal?.symbol || '').toUpperCase();
  const hasSignalForSelectedSymbol = selectedSignalSymbol === String(selectedSymbol || '').toUpperCase();

  useEffect(() => {
    if (!symbolCatalog.length) {
      void loadSymbolCatalog();
    }
  }, [symbolCatalog.length, loadSymbolCatalog]);

  useEffect(() => {
    const key = `${selectedSymbol}:${selectedTimeframe}`;

    if (bundleLoading || hasSignalForSelectedSymbol || autoLoadAttemptsRef.current.has(key)) {
      return;
    }

    autoLoadAttemptsRef.current.add(key);

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[Dashboard] auto-loading bundle:', { selectedSymbol, selectedTimeframe });
    }

    void loadSymbolBundle(selectedSymbol, selectedTimeframe).catch(() => null);
  }, [bundleLoading, hasSignalForSelectedSymbol, loadSymbolBundle, selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    const normalized = String(selectedSymbol || '').trim().toUpperCase();
    if (!normalized) return undefined;

    wsManager.subscribe(normalized);
    return () => {
      wsManager.unsubscribe(normalized);
    };
  }, [selectedSymbol]);

  const handleSelectSymbol = useCallback(async (symbol) => {
    try {
      await loadSymbolBundle(symbol, selectedTimeframe);
    } catch (error) {
      showToast(error?.message || 'Unable to load symbol bundle', 'error');
    }
  }, [loadSymbolBundle, selectedTimeframe, showToast]);

  const handleChangeTimeframe = useCallback(async (timeframe) => {
    try {
      await selectTimeframe(timeframe);
    } catch (error) {
      showToast(error?.message || 'Unable to switch timeframe', 'error');
    }
  }, [selectTimeframe, showToast]);

  const liveSignalLabel = String(currentSignal?.signal || currentSignal?.type || 'HOLD').toUpperCase();

  const livePrice = useMemo(() => {
    const fromTicker = toFinite(priceBySymbol?.[selectedSymbol]);
    if (fromTicker !== null && fromTicker > 0) return fromTicker;

    const fromSignal = toFinite(currentSignal?.price ?? currentSignal?.currentPrice);
    if (fromSignal !== null && fromSignal > 0) return fromSignal;

    return null;
  }, [currentSignal?.currentPrice, currentSignal?.price, priceBySymbol, selectedSymbol]);

  const kpidata = [
    { label: 'Total Equity', value: `₹${toNumber(balance, 0).toLocaleString('en-IN')}` },
    { label: 'Today P&L', value: `₹${toNumber(todaysPnL, 0).toLocaleString('en-IN')}` },
    { label: 'Win Rate', value: `${toNumber(winRate, 0).toFixed(1)}%` },
    { label: 'Active Trades', value: activeTrades.length },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      <KpiCards kpidata={kpidata} />

      <Card className="space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="text-xl font-bold text-white">All Stock Search</h3>
          <Badge variant="info">Bundle API • 100 Candles</Badge>
        </div>

        <SmartSearchBar
          selectedSymbol={selectedSymbol}
          onSelectSymbol={handleSelectSymbol}
          priceBySymbol={priceBySymbol}
          catalog={symbolCatalog}
          trendingSymbols={TRENDING_SYMBOLS}
        />

        <div className="flex gap-2 flex-wrap">
          {TIMEFRAMES.map((item) => (
            <Button
              key={item}
              type="button"
              variant={selectedTimeframe === item ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => handleChangeTimeframe(item)}
            >
              {item.toUpperCase()}
            </Button>
          ))}
        </div>

        <p className="text-xs text-gray-400">
          Timeframes: 1m, 5m, 15m, 1h, 1d. Each selection loads last 100 candles using the bundle API.
        </p>
      </Card>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between gap-2 mb-4">
            <h3 className="text-xl font-bold text-white">{selectedSymbol} Live Chart</h3>
            {bundleLoading ? <Badge variant="info">Loading...</Badge> : null}
          </div>

          {bundleError ? (
            <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {bundleError}
            </div>
          ) : null}

          <CandlestickChart
            candles={candles}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            indicators={indicators}
            isLoading={bundleLoading}
          />
        </Card>
        
        <div className="lg:col-span-1 space-y-6">
          <Card>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-bold text-white">Live Signal</h3>
              <Badge variant={signalVariant(liveSignalLabel)}>
                {liveSignalLabel}
              </Badge>
            </div>

            <div className="space-y-2 text-sm">
              <p className="text-gray-300">Symbol: <span className="font-semibold text-white">{selectedSymbol}</span></p>
              <p className="text-gray-300">Price: <span className="font-semibold text-white">{formatOptionalCurrency(livePrice)}</span></p>
              <p className="text-gray-300">Confidence: <span className="font-semibold text-white">{formatOptionalPercent(currentSignal?.confidence)}</span></p>
              <p className="text-gray-300">Target: <span className="font-semibold text-green-300">{formatOptionalCurrency(currentSignal?.target)}</span></p>
              <p className="text-gray-300">Stop Loss: <span className="font-semibold text-red-300">{formatOptionalCurrency(currentSignal?.stopLoss)}</span></p>
            </div>

            <p className="mt-3 text-xs text-gray-400 leading-relaxed">
              {currentSignal?.reason || 'Waiting for latest signal update...'}
            </p>
          </Card>

          <TopMovers />
        </div>
      </div>
    </div>
  );
}