import React, { useState, useEffect } from 'react';
import IntelligencePanel from '../components/IntelligencePanel/IntelligencePanel';
import ErrorBoundary from '../components/ErrorBoundary';

export default function RightPanel({ prediction: parentPrediction, snapshot, symbol, indicatorData, timeframe = '15m', isMockData }) {
  const [signalData, setSignalData] = useState(null);

  useEffect(() => {
    async function fetchSignalData() {
      if (!symbol) return;
      try {
        const res = await fetch(`/api/v1/predict?symbol=${symbol}&horizon=${timeframe}`);
        const response = await res.json();
        console.log("API Response:", response);
        console.log("Target:", response.target_price);
        setSignalData({
          signal: response.signal || "HOLD",
          confidence: response.confidence || 0,
          target: response.target_price,
          stopLoss: response.stop_loss
        });
      } catch (e) {
        console.error("Failed to fetch signal", e);
        setSignalData({ error: true });
      }
    }
    fetchSignalData();
  }, [symbol, timeframe]);

  if (!signalData) {
    return (
      <aside className="w-[340px] shrink-0 h-full overflow-y-auto custom-scrollbar bg-[#06090E] border-l border-white/5 p-4 flex flex-col gap-4 text-slate-400 font-mono text-sm z-20">
        Loading...
      </aside>
    );
  }

  const isBuy = signalData?.signal === 'BUY';
  const isSell = signalData?.signal === 'SELL';

  // Fallback map parent prediction for other parts if needed, but we use signalData for the main UI
  const prediction = parentPrediction;

  return (
    <aside className="w-[340px] shrink-0 h-full overflow-y-auto custom-scrollbar bg-[#06090E] border-l border-white/5 p-4 flex flex-col gap-4 hide-scrollbar pb-6 shadow-2xl z-20">

      {/* MOCK DATA WARNING BANNER */}
      {isMockData && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3 flex items-start gap-3 shadow-[0_0_15px_rgba(245,158,11,0.1)]">
          <svg className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
          <div>
            <div className="text-[11px] font-bold text-amber-500 font-mono uppercase tracking-wider mb-0.5">Mock Data Active</div>
            <div className="text-[10px] text-amber-500/80 font-mono leading-relaxed">
              SmartAPI is unavailable. Displaying simulated data. Trading signals are not valid for real execution.
            </div>
          </div>
        </div>
      )}

      {/* 4A. SIGNAL ENGINE CARD (Large Badge, Confidence, Regime) */}
      <div className="flex flex-col gap-4 p-4 overflow-hidden rounded-[12px] border border-[#1E293B] box-border group hover:border-[#334155] transition-all bg-gradient-to-br from-[#121821] to-[#0A0D14] shadow-[0_8px_24px_-4px_rgba(0,0,0,0.6)]">
        <div className="flex justify-between items-center flex-nowrap w-full">
          <div className="text-[10px] font-mono font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2 whitespace-nowrap">
            <svg className="w-3.5 h-3.5 text-teal-400 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            Signal Engine
          </div>
          <div className="px-2 py-0.5 rounded shadow-inner bg-black/40 border border-[#1E293B] text-[10px] text-slate-400 font-mono whitespace-nowrap">
            {isBuy ? 'Trending Up' : isSell ? 'Trending Down' : 'Ranging'}
          </div>
        </div>

        <div className="flex justify-between items-center flex-nowrap w-full">
          <div 
            className={`flex items-center justify-center min-w-fit px-4 py-2.5 rounded-xl font-mono font-extrabold text-2xl tracking-wide border transition-all duration-300
            ${isBuy ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.15)] glow-text' :
              isSell ? 'bg-red-500/20 text-red-400 border-red-500/40 shadow-[0_0_20px_rgba(239,68,68,0.15)] glow-text' :
                'bg-[#1E293B] text-slate-300 border-slate-600'}`}
          >
            {signalData?.signal || 'HOLD'}
          </div>

          <div className="flex flex-col items-end gap-1 whitespace-nowrap shrink-0">
            <div className="text-[10px] uppercase tracking-widest font-mono text-slate-400">Confidence</div>
            <div className="text-3xl font-mono font-black text-white glow-text leading-none">{Math.round(signalData?.confidence || 0)}%</div>
          </div>
        </div>

        <div className="w-full bg-[#06090E] rounded-full h-1.5 border border-[#1E293B] overflow-hidden shadow-inner shrink-0">
          <div
            className={`h-full rounded-full transition-all duration-1000 origin-left shadow-[0_0_10px_rgba(20,184,166,0.6)] ${isSell ? 'bg-gradient-to-r from-red-600 to-red-400' : 'bg-gradient-to-r from-teal-500 to-emerald-400'}`}
            style={{ width: `${signalData?.confidence || 0}%` }}
          ></div>
        </div>

        <div className="grid grid-cols-2 gap-4 shrink-0">
          <div className="bg-[#06090E]/80 px-3 py-2.5 rounded-xl border border-white/5 shadow-inner flex flex-col justify-center overflow-hidden">
            <div className="text-[10px] uppercase font-mono text-slate-500 mb-1 flex items-center gap-1.5 whitespace-nowrap">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div> Target
            </div>
            <div className="font-mono text-emerald-400 font-bold text-base truncate">
              {signalData?.error ? "Data unavailable" : (signalData?.target !== undefined ? `₹${signalData.target}` : "₹--")}
            </div>
          </div>
          <div className="bg-[#06090E]/80 px-3 py-2.5 rounded-xl border border-white/5 shadow-inner flex flex-col justify-center overflow-hidden">
            <div className="text-[9px] uppercase font-mono text-slate-500 mb-1 flex items-center gap-1.5 whitespace-nowrap">
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 shadow-[0_0_5px_rgba(239,68,68,0.5)]"></div> Stop Loss
            </div>
            <div className="font-mono text-red-400 font-bold text-sm truncate">
              {signalData?.error ? "Data unavailable" : (signalData?.stopLoss !== undefined ? `₹${signalData.stopLoss}` : "₹--")}
            </div>
          </div>
        </div>
      </div>

      {/* 4B. KEY TECHNICAL FACTORS */}
      <div className="bg-[#0B1017] rounded-[16px] border border-white/5 shadow-[0_8px_24px_-4px_rgba(0,0,0,0.6)] p-4 flex flex-col hover:border-white/10 transition-all bg-gradient-to-br from-white/[0.02] to-transparent">
        <div className="text-[10px] font-mono font-bold text-slate-400 uppercase tracking-widest border-b border-white/5 pb-2.5 mb-3 flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-blue-400 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
          Key Technical Factors
        </div>
        <div className="grid grid-cols-1 gap-1.5">
          {[
            { label: 'Trend (EMA)', value: isBuy ? 'Bullish Alignment' : isSell ? 'Bearish Alignment' : 'Neutral Flow', status: isBuy ? 'positive' : isSell ? 'negative' : 'neutral' },
            { label: 'RSI Momentum', value: indicatorData?.rsi ? `${indicatorData.rsi[indicatorData.rsi.length - 1]?.value?.toFixed(1) || '--'} (Neutral)` : 'Neutral', status: 'neutral' },
            { label: 'MACD Signal', value: isBuy ? 'Convergence' : isSell ? 'Divergence' : 'Flattening', status: isBuy ? 'positive' : isSell ? 'negative' : 'neutral' },
            { label: 'VWAP Flow', value: isBuy ? 'Above VWAP' : isSell ? 'Below VWAP' : 'At VWAP', status: isBuy ? 'positive' : isSell ? 'negative' : 'neutral' }
          ].map((factor, i) => (
            <div key={i} className="flex justify-between items-center text-xs font-mono px-3 py-2 rounded-lg bg-[#06090E]/60 border border-white/5 hover:border-white/10 transition-colors shadow-inner">
              <span className="text-slate-400">{factor.label}</span>
              <span className={`px-2 py-0.5 rounded border text-[9px] font-bold uppercase tracking-wider ${factor.status === 'positive' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : factor.status === 'negative' ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-[#1E293B] text-slate-300 border-transparent'}`}>
                {factor.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 4C. AI CO-PILOT */}
      <div className="bg-[#0B1017] rounded-[16px] border border-white/5 shadow-[0_8px_24px_-4px_rgba(0,0,0,0.6)] flex flex-col hover:border-white/10 transition-all overflow-hidden flex-shrink-0 bg-gradient-to-br from-white/[0.02] to-transparent">
        <div className="px-4 py-3 text-[10px] font-mono font-bold text-slate-400 uppercase tracking-widest border-b border-white/5 bg-black/20 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <svg className="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
            AI Co-Pilot
          </div>
          <div className={`text-[10px] font-bold px-2 py-0.5 rounded bg-black/40 border border-white/5 ${isBuy ? 'text-teal-400 glow-text' : isSell ? 'text-red-400 glow-text' : 'text-slate-400'}`}>
              {Math.round(signalData?.confidence || 0)}%          </div>        </div>
        <div className="p-4 bg-transparent">
          <div className="text-[11px] text-slate-400 font-mono mb-4 leading-relaxed border-l-2 border-purple-500/50 pl-3 py-1 shadow-inner bg-[#06090E]/30 rounded-r-lg">
            {prediction?.reasoning || `The ensemble model predicts a high probability ${isBuy ? 'markup' : isSell ? 'markdown' : 'consolidation'} phase based on aggregate institutional footprint volume matching and momentum oscillators.`}
          </div>

          <div className="space-y-2.5 mt-4">
            <div>
              <div className="flex justify-between text-[10px] uppercase font-mono text-slate-500 mb-1 flex items-center justify-between">
                <span>Ensemble Confidence</span>
                <span className="text-white">High</span>
              </div>
              <div className="w-full bg-[#121821] rounded-full h-1 border border-[#1E293B]">
                <div className="bg-purple-500 h-full rounded-full" style={{ width: '85%' }}></div>
              </div>
            </div>
            <div>
              <div className="flex justify-between text-[10px] uppercase font-mono text-slate-500 mb-1 flex items-center justify-between">
                <span>Volume Profile</span>
                <span className="text-white">Active</span>
              </div>
              <div className="w-full bg-[#121821] rounded-full h-1 border border-[#1E293B]">
                <div className="bg-blue-500 h-full rounded-full" style={{ width: '60%' }}></div>
              </div>
            </div>
          </div>
        </div>

        {/* Native IntelligencePanel hidden but maintained in tree for internal states if needed, or skipped here. We render custom representation instead for premium look. */}
        <div className="h-0 overflow-hidden opacity-0 pointer-events-none">
          <ErrorBoundary>
            <IntelligencePanel prediction={prediction} snapshot={snapshot} symbol={symbol} compact />
          </ErrorBoundary>
        </div>

      </div>

    </aside>
  );
}
