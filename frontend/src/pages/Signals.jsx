import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Cpu, ShieldAlert } from 'lucide-react';
import { useStore } from '../store/useStore';
import { useToast } from '../components/Toast';
import { Card, Badge, Button } from '../components/ui';
import ConfirmDialog from '../components/ConfirmDialog';
import TradeStatusPanel from '../components/features/TradeStatusPanel';

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const signalVariant = (signal) => {
  const value = String(signal || '').toUpperCase();
  if (value === 'BUY') return 'buy';
  if (value === 'SELL') return 'sell';
  return 'info';
};

export default function Signals() {
  const {
    signals,
    currentSignal,
    executeTrade,
    bundleLoading,
    selectedTimeframe,
    balance,
    tradeDecisionBySymbol,
    tradeDecisionLoadingBySymbol,
    tradeDecisionErrorBySymbol,
    evaluateTradeDecision,
    liveHealth,
    tradingBlockedByLatency,
    liveDataMessage,
  } = useStore();
  const { showToast } = useToast();
  const [confirmTrade, setConfirmTrade] = useState(null);
  const pollIndexRef = useRef(0);

  const signalRows = signals.length ? signals : (currentSignal ? [currentSignal] : []);
  const trackedSymbols = useMemo(
    () => [...new Set(signalRows.map((row) => String(row?.symbol || '').toUpperCase()).filter(Boolean))].slice(0, 12),
    [signalRows],
  );

  useEffect(() => {
    if (!trackedSymbols.length) return undefined;

    let cancelled = false;
    const evaluateNext = async () => {
      const nextIndex = pollIndexRef.current % trackedSymbols.length;
      pollIndexRef.current += 1;

      const symbol = trackedSymbols[nextIndex];
      await evaluateTradeDecision(symbol, selectedTimeframe, {
        capital: balance,
        riskPerTrade: 0.01,
        skipIfLoading: true,
      }).catch(() => null);
    };

    void evaluateNext();

    const intervalId = setInterval(() => {
      if (!cancelled) {
        void evaluateNext();
      }
    }, 4000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [balance, evaluateTradeDecision, selectedTimeframe, trackedSymbols]);

  const handleExecuteConfirmed = async (signal) => {
    try {
      await executeTrade(signal);
      showToast(`Trade executed for ${signal.symbol}`, 'success');
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      setConfirmTrade(null);
    }
  };

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-10">
      <Card className="!p-4 border-cyan-500/20 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.15),_rgba(8,17,32,0.9)_60%)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-bold">Signal Command Desk</p>
            <h2 className="mt-1 text-2xl font-black text-white">Live Signals</h2>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="info">{String(liveHealth || 'STALE').toUpperCase()}</Badge>
            <Badge variant="info">{signalRows.length} Active</Badge>
          </div>
        </div>
      </Card>

      {tradingBlockedByLatency ? (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5" />
          <span>STALE FEED - {liveDataMessage || 'NO LIVE DATA'}. Execution is blocked until latency normalizes.</span>
        </div>
      ) : (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200 flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 mt-0.5" />
          <span>{String(liveHealth || 'LIVE').toUpperCase()} - Feed healthy for execution.</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4">
        {signalRows.map((signal) => {
          const symbol = String(signal?.symbol || '').toUpperCase();
          const decision = tradeDecisionBySymbol?.[symbol] || null;
          const decisionLoading = Boolean(tradeDecisionLoadingBySymbol?.[symbol]);
          const decisionError = tradeDecisionErrorBySymbol?.[symbol] || null;
          const decisionStatus = String(decision?.decision?.status || 'BLOCKED').toUpperCase();
          const executeDisabled = bundleLoading || tradingBlockedByLatency || decisionStatus !== 'READY';

          return (
            <Card key={signal.id || `${signal.symbol}-${signal.timestamp}`} className="!p-4 border-white/10 bg-[#081628]/90">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Instrument</p>
                  <h3 className="text-xl font-black text-white mt-1">{signal.symbol}</h3>
                </div>
                <Badge variant={signalVariant(signal.signal)}>{String(signal.signal || 'HOLD').toUpperCase()}</Badge>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
                  <p className="text-slate-500">Price</p>
                  <p className="text-cyan-200 font-semibold mt-1">₹{toNumber(signal.price ?? signal.currentPrice, 0).toFixed(2)}</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
                  <p className="text-slate-500">Confidence</p>
                  <p className="text-emerald-200 font-semibold mt-1">{toNumber(signal.confidence, 0).toFixed(1)}%</p>
                </div>
              </div>

              <div className="mt-3">
                <TradeStatusPanel
                  symbol={symbol}
                  decision={decision}
                  isLoading={decisionLoading}
                  error={decisionError}
                  compact
                />
              </div>

              <div className="mt-3 flex items-center justify-between gap-2 text-[11px] text-slate-500">
                <span className="inline-flex items-center gap-1.5"><Cpu className="h-3 w-3" />Decision: {decisionStatus}</span>
                <span className="inline-flex items-center gap-1.5"><ShieldAlert className="h-3 w-3" />Risk Gate</span>
              </div>

              <Button
                onClick={() => setConfirmTrade(signal)}
                disabled={executeDisabled}
                className="w-full mt-4"
              >
                {tradingBlockedByLatency ? 'NO LIVE DATA' : (executeDisabled ? 'Execution Blocked' : 'Execute Trade')}
              </Button>
            </Card>
          );
        })}

        {signalRows.length === 0 ? (
          <Card className="!p-8 border-white/10 bg-[#081628]/90 col-span-full">
            <div className="text-center text-slate-400">
              <Activity className="h-6 w-6 mx-auto mb-2" />
              <p>No active signals available.</p>
            </div>
          </Card>
        ) : null}
      </div>

      <ConfirmDialog
        isOpen={!!confirmTrade}
        title="Execute Trade?"
        message={confirmTrade ? `Execute ${confirmTrade.signal} for ${confirmTrade.symbol} at ₹${toNumber(confirmTrade.price ?? confirmTrade.currentPrice, 0).toFixed(2)}?` : ''}
        isDestructive
        confirmText="Execute"
        onConfirm={() => handleExecuteConfirmed(confirmTrade)}
        onCancel={() => setConfirmTrade(null)}
      />
    </div>
  );
}
