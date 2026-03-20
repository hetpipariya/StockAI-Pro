import React from 'react';
import DecisionChartCanvas from '../components/DecisionChartCanvas/DecisionChartCanvas';
import ErrorBoundary from '../components/ErrorBoundary';
import ChartToolbar from '../components/ChartToolbar/ChartToolbar';

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1D'];

export default function ChartSection({ 
  symbol, timeframe, setTimeframe, ohlcv, snapshot, prediction, 
  indicators, setIndicators, indicatorData, loading, errorMsg, isMockData, engine 
}) {
  return (
    <section className="flex-1 min-w-0 flex flex-col relative h-full bg-[#0B0F14]">
      
      {/* 12px padding INSIDE chart container only, rounded corners, subtle border */}
      <div className="flex-1 flex flex-col overflow-hidden relative border-x border-[#1E293B]/50 bg-[#06090E]" style={{ padding: '12px' }}>
        
        <div className="flex-1 bg-[#0A0D14] rounded-[16px] border border-[#1E293B] flex flex-col overflow-visible relative shadow-[0_8px_32px_rgba(0,0,0,0.8)]">

          {/* TOP CONTROLS */}
          <div className="shrink-0 flex items-center justify-between px-5 py-2.5 border-b border-[#1E293B] bg-[#0B0F14]/90 backdrop-blur-md rounded-t-[16px] z-30">
            <div className="flex items-center gap-3">
              <div className="font-mono text-lg font-bold text-white flex items-center gap-2">
                {symbol}
                <span className="text-[9px] uppercase font-bold text-slate-400 border border-[#1E293B] px-1.5 py-0.5 rounded bg-white/5">NSE</span>
              </div>
              {snapshot?.ltp && (
                <div className={`font-mono font-bold ml-1 text-sm ${snapshot.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  ₹{Number(snapshot.ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                </div>
              )}
            </div>
            
            <div className="flex items-center bg-[#06090E]/50 p-1 rounded-xl border border-white/5">
              <ChartToolbar 
                timeframe={timeframe} 
                setTimeframe={setTimeframe} 
                indicators={indicators} 
                setIndicators={setIndicators} 
              />
            </div>
          </div>

          {/* CHART AREA */}
          <div className="flex-1 min-h-0 w-full relative bg-[#0A0D14] overflow-hidden">
            {errorMsg ? (
               <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center bg-black/20">
                 <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mb-3 border border-red-500/20">
                   <svg className="w-6 h-6 text-red-500/80" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                 </div>
                 <div className="text-red-400 font-mono text-sm font-bold tracking-wide">{errorMsg}</div>
               </div>
            ) : loading ? (
               <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10 bg-[#0B0F14]/50 backdrop-blur-sm">
                 <div className="w-8 h-8 border-2 border-[#1E293B] border-t-teal-500 rounded-full animate-spin shadow-[0_0_15px_rgba(20,184,166,0.2)]" />
                 <span className="text-teal-400 font-mono text-[10px] mt-4 tracking-widest uppercase bg-[#121821] px-3 py-1.5 rounded-lg border border-[#1E293B] shadow-lg">Loading...</span>
               </div>
            ) : (
                <ErrorBoundary>
                  <DecisionChartCanvas ohlcv={ohlcv} symbol={symbol} snapshot={snapshot} isMockData={isMockData} timeframe={timeframe} focusMode={false} indicators={indicators} indicatorData={indicatorData} prediction={prediction} onPaginateHistory={engine?.loadMoreHistory} />
                </ErrorBoundary>
            )}
          </div>

          {/* BOTTOM INFO BAR */}
          {prediction && (
            <div className="shrink-0 flex items-center justify-between px-5 py-2.5 bg-[#0B0F14]/90 backdrop-blur-md rounded-b-[16px] border-t border-[#1E293B] z-20">
              <div className={`text-[11px] font-mono font-bold flex items-center gap-2 ${prediction.signal === 'BUY' ? 'text-emerald-400' : prediction.signal === 'SELL' ? 'text-red-400' : 'text-slate-400'}`}>
                <div className={`w-2 h-2 rounded-full ${prediction.signal === 'BUY' ? 'bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]' : prediction.signal === 'SELL' ? 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.5)]' : 'bg-slate-500'} animate-pulse`}></div>
                Indicators confirm {prediction.signal === 'BUY' ? 'bullish' : prediction.signal === 'SELL' ? 'bearish' : 'neutral'} bias on {timeframe}
              </div>
              <div className="flex items-center gap-2 w-32">
                <span className="text-[9px] uppercase font-mono text-slate-500">Confidence</span>
                <div className="flex-1 bg-[#121821] rounded-full h-1 border border-[#1E293B] overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all duration-1000 ${prediction.signal === 'SELL' ? 'bg-gradient-to-r from-red-600 to-red-400' : 'bg-gradient-to-r from-teal-600 to-emerald-400'}`}
                    style={{ width: `${Math.round(prediction.confidence || 0)}%` }}
                  ></div>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </section>
  );
}
