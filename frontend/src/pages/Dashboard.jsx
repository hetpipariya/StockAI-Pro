import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { useStore } from '../store/useStore.js';
import { useToast } from '../components/Toast';
import { wsManager } from '../api/websocket.js';
import { useLivePrice } from '../context/LivePriceContext';
import CandlestickChart from '../components/dashboard/CandlestickChart';
import Topbar from '../components/dashboard/Topbar';
import Bottombar from '../components/dashboard/Bottombar';
import AiTerminalPanel from '../components/dashboard/AiTerminalPanel';
import { AlertTriangle, Layers, Maximize2 } from 'lucide-react';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '1d'];

export default function Dashboard() {
  const { showToast } = useToast();

  const { currentPrice, dataSource, connectionStatus } = useLivePrice();

  // Selector-based Zustand subscriptions to minimize global page reconciliation
  const selectedSymbol = useStore(state => state.selectedSymbol);
  const selectedTimeframe = useStore(state => state.selectedTimeframe);
  const symbolCatalog = useStore(state => state.symbolCatalog);
  const candles = useStore(state => state.candles);
  const snapshot = useStore(state => state.snapshot);
  const indicators = useStore(state => state.indicators);
  const currentSignal = useStore(state => state.currentSignal);
  const bundleLoading = useStore(state => state.bundleLoading);
  const bundleError = useStore(state => state.bundleError);
  const bundleWarnings = useStore(state => state.bundleWarnings);
  const loadSymbolCatalog = useStore(state => state.loadSymbolCatalog);
  const loadSymbolBundle = useStore(state => state.loadSymbolBundle);
  const selectTimeframe = useStore(state => state.selectTimeframe);

  const autoLoadAttemptsRef = useRef(new Set());
  const selectedSignalSymbol = String(currentSignal?.symbol || '').toUpperCase();
  const hasSignalForSelectedSymbol = selectedSignalSymbol === String(selectedSymbol || '').toUpperCase();

  const livePrice = Number(currentPrice) || Number(snapshot?.ltp) || (candles.length > 0 ? candles[candles.length - 1].close : 0);
  const dataSourceLabel = String(dataSource || 'NSE_API').toUpperCase();

  // Load symbols catalog on mount
  useEffect(() => {
    if (!symbolCatalog.length) {
      void loadSymbolCatalog();
    }
  }, [symbolCatalog.length, loadSymbolCatalog]);

  // Load symbol bundle
  useEffect(() => {
    const key = `${selectedSymbol}:${selectedTimeframe}`;
    if (bundleLoading || hasSignalForSelectedSymbol || autoLoadAttemptsRef.current.has(key)) {
      return;
    }
    autoLoadAttemptsRef.current.add(key);
    void loadSymbolBundle(selectedSymbol, selectedTimeframe).catch(() => null);
  }, [bundleLoading, hasSignalForSelectedSymbol, loadSymbolBundle, selectedSymbol, selectedTimeframe]);

  // WebSocket Subscription management
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

  const tradeLevels = useMemo(() => {
    if (!hasSignalForSelectedSymbol || !currentSignal) {
      return { entry: null, stopLoss: null, target: null };
    }
    return {
      entry: currentSignal.entry || currentSignal.price || null,
      stopLoss: currentSignal.stopLoss || currentSignal.stop_loss || null,
      target: currentSignal.target || currentSignal.target_price || null,
    };
  }, [hasSignalForSelectedSymbol, currentSignal]);

  return (
    <div className="w-full h-full flex flex-col bg-[#050816] text-slate-200 overflow-hidden font-sans relative">
      
      {/* Realtime Terminal Header */}
      <Topbar handleSelectSymbol={handleSelectSymbol} />

      {/* Main Split: Chart + AI Intel */}
      <div className="flex-1 flex overflow-hidden w-full relative">
        
        {/* Chart Viewport (83%) */}
        <main className="flex-1 h-full flex flex-col min-w-0 bg-[#050816]">
          
          {/* Chart Header Bar */}
          <div className="h-[5vh] min-h-[38px] shrink-0 border-b border-white/5 bg-[#060A14] px-4 flex items-center justify-between select-none">
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-white tracking-widest font-mono">{selectedSymbol}</span>
              <span className="text-[9px] text-slate-500 font-mono">({dataSourceLabel})</span>
              {connectionStatus === 'FAILED' && (
                <span className="text-[9px] text-rose-400 font-mono font-bold animate-pulse px-1.5 py-0.5 rounded border border-rose-500/20 bg-rose-500/5">
                  DEGRADED (POLLING)
                </span>
              )}
              
              {/* Timeframe Controls */}
              <div className="flex items-center bg-white/5 rounded-lg p-0.5 border border-white/5 ml-4">
                {TIMEFRAMES.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => handleChangeTimeframe(item)}
                    className={`rounded px-2.5 py-0.5 text-[9px] font-bold font-mono transition-all ${
                      selectedTimeframe === item
                        ? 'text-cyan-300 bg-[#0C1425] border border-cyan-500/20 shadow-[0_0_8px_rgba(6,182,212,0.15)]'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    {item.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Indicator status panel */}
            <div className="hidden sm:flex items-center gap-2">
              <span className="text-[9px] text-slate-500 font-mono mr-2">ACTIVE ENGINES:</span>
              <div className="px-2 py-0.5 rounded border border-cyan-500/20 bg-cyan-500/5 text-[8px] font-mono text-cyan-300 font-bold">EMA(20)</div>
              <div className="px-2 py-0.5 rounded border border-cyan-500/20 bg-cyan-500/5 text-[8px] font-mono text-cyan-300 font-bold">EMA(50)</div>
              <div className="px-2 py-0.5 rounded border border-amber-500/20 bg-amber-500/5 text-[8px] font-mono text-amber-300 font-bold">RSI(14)</div>
            </div>
          </div>

          {/* Interactive TradingView Canvas Container */}
          <div className="flex-1 min-h-0 bg-[#050816] relative p-2 flex flex-col">
            
            {/* System Warnings / Alerts Banner */}
            {bundleWarnings.length > 0 && (
              <div className="mb-2 shrink-0 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 flex items-center gap-2 text-[10px] text-amber-300 font-mono">
                <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                <span>{bundleWarnings[0]}</span>
              </div>
            )}

            <div className="flex-1 min-h-0 relative rounded-xl border border-white/5 overflow-hidden">
              <CandlestickChart
                candles={candles}
                symbol={selectedSymbol}
                timeframe={selectedTimeframe}
                indicators={indicators}
                isLoading={bundleLoading}
                livePrice={livePrice}
                signalType={currentSignal?.signal}
                tradeLevels={tradeLevels}
              />

              {connectionStatus === 'RECONNECTING' && candles.length === 0 && (
                <div className="absolute inset-0 bg-[#050816]/75 backdrop-blur-sm flex flex-col items-center justify-center gap-3 z-20">
                  <div className="h-9 w-9 rounded-full border-2 border-cyan-500/30 border-t-cyan-400 animate-spin" />
                  <span className="text-xs font-bold text-cyan-300 font-mono tracking-widest uppercase animate-pulse">RECONNECTING LIVE FEED...</span>
                </div>
              )}

              {connectionStatus === 'RECONNECTING' && candles.length > 0 && (
                <div className="absolute top-4 right-4 bg-[#0a0f1d]/90 border border-cyan-500/25 text-cyan-300 rounded-xl px-4 py-3 shadow-[0_4px_20px_rgba(6,182,212,0.15)] backdrop-blur-md max-w-xs flex gap-3 items-start z-20 animate-in fade-in slide-in-from-top-4 duration-300">
                  <div className="h-4 w-4 rounded-full border-2 border-cyan-500/30 border-t-cyan-400 animate-spin shrink-0 mt-0.5" />
                  <div className="flex flex-col gap-0.5 font-mono">
                    <span className="text-xs font-extrabold tracking-wider uppercase text-cyan-400">RECONNECTING STREAM</span>
                    <span className="text-[9px] text-slate-400 leading-normal">Using degraded API polling backup.</span>
                  </div>
                </div>
              )}

              {connectionStatus === 'FAILED' && (
                <div className="absolute top-4 right-4 bg-[#0a0f1d]/90 border border-rose-500/25 text-rose-300 rounded-xl px-4 py-3 shadow-[0_4px_20px_rgba(244,63,94,0.15)] backdrop-blur-md max-w-xs flex gap-3 items-start z-20 animate-in fade-in slide-in-from-top-4 duration-300">
                  <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                  <div className="flex flex-col gap-0.5 font-mono">
                    <span className="text-xs font-extrabold tracking-wider uppercase text-rose-400">LIVE STREAM DISCONNECTED</span>
                    <span className="text-[9px] text-slate-400 leading-normal">degraded API polling backup mode.</span>
                  </div>
                </div>
              )}
            </div>
          </div>

        </main>

        {/* AI Terminal Panel (17%) - Collapsed on Mobile fallback */}
        <aside className="w-[17%] h-full bg-[#080E1B] border-l border-white/5 flex flex-col min-w-[300px] overflow-hidden select-none hidden lg:flex shadow-[[-4px_0_20px_rgba(0,0,0,0.2)]">
          {/* Header */}
          <div className="h-[5vh] min-h-[38px] shrink-0 px-3 border-b border-white/5 bg-[#0C1324] flex items-center justify-between">
            <span className="text-[9px] uppercase font-bold tracking-[0.2em] text-slate-400 flex items-center gap-1.5 font-mono">
              <Layers className="h-3.5 w-3.5 text-cyan-300 animate-pulse" /> AI Terminal Intel
            </span>
            <span className="px-2 py-0.5 rounded border border-cyan-500/20 bg-cyan-500/5 text-[8px] font-mono text-cyan-300">
              LIVE
            </span>
          </div>

          {/* Scrolling Panel list */}
          <AiTerminalPanel livePrice={livePrice} />
        </aside>

      </div>

      {/* Status Footer */}
      <Bottombar livePrice={livePrice} />

    </div>
  );
}
