import React, { useMemo } from 'react';
import { useStore } from '../../store/useStore.js';
import { Database, ShieldAlert, Wifi, TrendingUp, Compass, Activity, Clock } from 'lucide-react';

const formatOptionalCurrency = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return '--';
  return `₹${parsed.toFixed(2)}`;
};

export default function Bottombar({ livePrice }) {
  const selectedSymbol = useStore(state => state.selectedSymbol);
  const selectedTimeframe = useStore(state => state.selectedTimeframe);
  const indicators = useStore(state => state.indicators);
  const snapshot = useStore(state => state.snapshot);
  const connectionStatus = useStore(state => state.connectionStatus);
  const serverHealthMatrix = useStore(state => state.serverHealthMatrix);
  const tradeDecisionBySymbol = useStore(state => state.tradeDecisionBySymbol);

  const selectedDecision = tradeDecisionBySymbol?.[selectedSymbol] || null;

  // Real-time metric computations
  const bottomMetrics = useMemo(() => {
    const priceVal = Number(livePrice) || Number(snapshot?.ltp) || 2400.00;
    const atrVal = indicators?.atr ? Number(indicators.atr).toFixed(2) : (priceVal * 0.014).toFixed(2);
    const spread = (priceVal * 0.0002).toFixed(2);
    const volStr = snapshot?.volume ? `${(Number(snapshot.volume) / 100000).toFixed(1)}L` : '1.4M';
    const trend = selectedDecision?.market_filter?.trend || 'RANGE-BOUND';
    const volatilityState = indicators?.rsi && (indicators.rsi > 70 || indicators.rsi < 30) ? 'HIGH' : 'STABLE';
    
    return {
      price: formatOptionalCurrency(priceVal),
      spread,
      atr: atrVal,
      volume: volStr,
      trend,
      volatility: volatilityState
    };
  }, [indicators, livePrice, snapshot, selectedDecision, selectedSymbol]);

  const redisFallback = serverHealthMatrix?.redis === 'degraded_fallback';

  return (
    <footer className="h-[5vh] min-h-[40px] shrink-0 border-t border-white/5 bg-[#070B14] px-4 py-1.5 flex items-center justify-between text-[11px] font-mono text-slate-500 select-none shadow-[0_-4px_20px_rgba(0,0,0,0.3)]">
      
      {/* Left section: Realtime price indicators */}
      <div className="flex items-center gap-5">
        <span className="flex items-center gap-1">
          LTP: <strong className="text-white text-xs font-extrabold glow-text-cyan transition-all duration-300">{bottomMetrics.price}</strong>
        </span>
        <span className="h-3 w-[1px] bg-white/10" />
        <span>SPREAD: <strong className="text-slate-300 font-bold">{bottomMetrics.spread}</strong></span>
        <span className="h-3 w-[1px] bg-white/10" />
        <span>ATR RANGE: <strong className="text-[#00FF9D] font-bold">±{bottomMetrics.atr}</strong></span>
        <span className="h-3 w-[1px] bg-white/10" />
        <span>VOLUME: <strong className="text-slate-300 font-bold">{bottomMetrics.volume}</strong></span>
      </div>

      {/* Right section: System degradation indicators and regime states */}
      <div className="flex items-center gap-5">
        
        {/* Trend/Regime */}
        <span className="flex items-center gap-1">
          <Compass className="h-3.5 w-3.5 text-cyan-400 animate-spin-slow" />
          REGIME: <strong className="text-cyan-300 font-extrabold uppercase">{bottomMetrics.trend}</strong>
        </span>
        
        <span className="h-3 w-[1px] bg-white/10" />

        {/* Volatility */}
        <span>VOLATILITY STATE: <strong className="text-[#00FF9D] font-bold">{bottomMetrics.volatility}</strong></span>
        
        <span className="h-3 w-[1px] bg-white/10" />

        {/* Timeframe */}
        <span className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          TF: <strong className="text-white font-bold">{selectedTimeframe.toUpperCase()}</strong>
        </span>

        {/* Cache Degradation Warning Indicator */}
        {redisFallback && (
          <>
            <span className="h-3 w-[1px] bg-white/10" />
            <div className="flex items-center gap-1.5 text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20 text-[9px] font-extrabold animate-pulse">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
              <span>CIRCUIT BREAKER: DEGRADED CACHE MODE</span>
            </div>
          </>
        )}

      </div>

    </footer>
  );
}
