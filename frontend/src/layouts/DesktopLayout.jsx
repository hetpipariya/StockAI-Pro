import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import MacroBar from '../components/MacroBar/MacroBar'
import FloatingOrderPanel from '../components/FloatingOrderPanel/FloatingOrderPanel'
import SectorHeatmap from '../components/SectorHeatmap/SectorHeatmap'
import CorrelationMatrix from '../components/CorrelationMatrix/CorrelationMatrix'
import MarketClosedBanner from '../components/MarketClosedPopup/MarketClosedPopup'
import SignalToast from '../components/SignalToast/SignalToast'

// New Split Components
import LeftPanel from './LeftPanel'
import ChartSection from './ChartSection'
import RightPanel from './RightPanel'

export default function DesktopLayout({ engine, onLogout }) {
  const [showFloatingOrder, setShowFloatingOrder] = useState(false)
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showCorrelation, setShowCorrelation] = useState(false)

  const {
    symbol, setSymbol, timeframe, setTimeframe, ohlcv, snapshot, prediction,
    indicators, setIndicators, indicatorData, loading, errorMsg, isMockData,
    marketStatus, activeSignal, setActiveSignal
  } = engine

  const strongSignal = prediction && prediction.confidence >= 70 && prediction.signal !== 'HOLD'

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#0B0F14] text-slate-200 selection:bg-teal-500/30">
      <MarketClosedBanner status={marketStatus} />
      
      {/* 5. TOP GLOBAL BAR */}
      <nav className="shrink-0 flex items-center justify-between px-6 py-2 border-b border-white/5 bg-[#06090E] sticky top-0 z-[60] shadow-[0_4px_30px_rgba(0,0,0,0.6)]">
        <div className="flex items-center gap-6 overflow-hidden max-w-[50%]">
          <div className="font-extrabold text-lg text-transparent bg-clip-text bg-gradient-to-r from-teal-400 to-emerald-500 font-mono tracking-tighter cursor-pointer shrink-0 hover:scale-105 transition-transform">
            STOCKAI PRO
          </div>
          <div className="hidden lg:block w-px h-5 bg-[#1E293B] shrink-0" />
          <div className="flex-1 overflow-x-auto hide-scrollbar custom-scrollbar pr-2">
            <MacroBar compact onSectorClick={() => setShowHeatmap(true)} />
          </div>
        </div>
        <div className="flex items-center justify-end gap-4 shrink-0">
          <div className="text-right mr-4 border-r border-[#1E293B] pr-4 hidden lg:block">
            <div className={`text-[10px] font-mono uppercase tracking-wider mb-0.5 ${marketStatus === 'OPEN' ? 'text-emerald-500' : 'text-slate-500'}`}>
              {marketStatus === 'OPEN' ? '🟢 Market Open' : '🔴 Market Closed'}
            </div>
            {snapshot?.ltp && (
              <div className="font-mono text-sm font-bold text-teal-400 hover:text-teal-300 transition-colors cursor-default">
                {symbol} ₹{Number(snapshot.ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowCorrelation(true)} className="px-3 py-1.5 rounded-lg border border-[#1E293B] bg-[#121821] hover:bg-[#1a2332] text-xs font-mono text-slate-300 transition-all hover:border-teal-500/30">Correlations</button>
            <button onClick={() => setShowHeatmap(true)} className="px-3 py-1.5 rounded-lg border border-[#1E293B] bg-[#121821] hover:bg-[#1a2332] text-xs font-mono text-slate-300 transition-all hover:border-teal-500/30">Heatmap</button>
            {strongSignal && (
              <button 
                onClick={() => setShowFloatingOrder(true)} 
                className="px-4 py-1.5 rounded-lg font-mono text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/30 hover:shadow-[0_0_15px_rgba(16,185,129,0.2)] transition-all animate-pulse"
              >
                Action Order
              </button>
            )}
            <button onClick={onLogout} className="px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400/80 hover:bg-red-500/10 text-xs font-mono transition-all ml-2">Logout</button>
          </div>
        </div>
      </nav>

      {/* 1. MAIN LAYOUT */}
      <main className="flex-1 min-h-0 flex w-full relative overflow-hidden bg-[#0A0D14]/90 shadow-inner">
        
        <LeftPanel 
          symbol={symbol} 
          setSymbol={setSymbol} 
          snapshot={snapshot} 
          onQuickOrder={(s) => { setSymbol(s); setShowFloatingOrder(true) }} 
        />

        <ChartSection 
          symbol={symbol} 
          timeframe={timeframe} 
          setTimeframe={setTimeframe} 
          ohlcv={ohlcv} 
          snapshot={snapshot} 
          prediction={prediction}
          indicators={indicators} 
          setIndicators={setIndicators}
          indicatorData={indicatorData} 
          loading={loading} 
          errorMsg={errorMsg} 
          isMockData={isMockData}
          engine={engine}
        />

        <RightPanel 
          prediction={prediction} 
          snapshot={snapshot} 
          symbol={symbol}
          indicatorData={indicatorData}
        />

      </main>

      {/* Floating Modal Layers */}
      {showFloatingOrder && (
        <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="relative pointer-events-auto transform transition-all animate-in fade-in zoom-in duration-200">
             <FloatingOrderPanel symbol={symbol} snapshot={snapshot} visible={true} onClose={() => setShowFloatingOrder(false)} />
          </div>
        </div>
      )}

      {/* Modals */}
      <AnimatePresence>
        {showHeatmap && (
           <div className="fixed inset-0 bg-[#0B0F14]/90 backdrop-blur-md z-[100] flex items-center justify-center p-4" onClick={() => setShowHeatmap(false)}>
             <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="max-w-6xl w-full relative z-[101]" onClick={e => e.stopPropagation()}>
               <button onClick={() => setShowHeatmap(false)} className="absolute -top-4 -right-4 w-10 h-10 rounded-full bg-[#121821] border border-[#1E293B] text-slate-400 hover:text-white hover:bg-red-500/20 hover:border-red-500/50 hover:shadow-[0_0_15px_rgba(239,68,68,0.2)] z-10 transition-all flex items-center justify-center">
                 <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
               </button>
               <SectorHeatmap onSectorClick={() => setShowHeatmap(false)} />
             </motion.div>
           </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showCorrelation && (
           <div className="fixed inset-0 bg-[#0B0F14]/90 backdrop-blur-md z-[100] flex items-center justify-center p-4" onClick={() => setShowCorrelation(false)}>
             <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="max-w-6xl w-full relative z-[101]" onClick={e => e.stopPropagation()}>
               <button onClick={() => setShowCorrelation(false)} className="absolute -top-4 -right-4 w-10 h-10 rounded-full bg-[#121821] border border-[#1E293B] text-slate-400 hover:text-white hover:bg-red-500/20 hover:border-red-500/50 hover:shadow-[0_0_15px_rgba(239,68,68,0.2)] z-10 transition-all flex items-center justify-center">
                 <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
               </button>
               <CorrelationMatrix />
             </motion.div>
           </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {activeSignal && (
          <SignalToast signal={activeSignal.signal} symbol={symbol} confidence={activeSignal.confidence} target={activeSignal.target} onClose={() => setActiveSignal(null)} />
        )}
      </AnimatePresence>

    </div>
  )
}
