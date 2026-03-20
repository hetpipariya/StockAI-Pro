import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import MacroBar from '../components/MacroBar/MacroBar'
import DataStreamPanel from '../components/DataStreamPanel/DataStreamPanel'
import ChartToolbar from '../components/ChartToolbar/ChartToolbar'
import DecisionChartCanvas from '../components/DecisionChartCanvas/DecisionChartCanvas'
import DecisionTimeline from '../components/DecisionTimeline/DecisionTimeline'
import IntelligencePanel from '../components/IntelligencePanel/IntelligencePanel'
import FloatingOrderPanel from '../components/FloatingOrderPanel/FloatingOrderPanel'
import SectorHeatmap from '../components/SectorHeatmap/SectorHeatmap'
import CorrelationMatrix from '../components/CorrelationMatrix/CorrelationMatrix'
import MobileDrawer from '../components/MobileDrawer/MobileDrawer'
import OrderEntry from '../components/OrderEntry/OrderEntry'
import WatchlistPanel from '../components/WatchlistPanel/WatchlistPanel'
import MarketClosedBanner from '../components/MarketClosedPopup/MarketClosedPopup'
import SignalToast from '../components/SignalToast/SignalToast'
import ErrorBoundary from '../components/ErrorBoundary'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1d']

export default function MobileLayout({ engine, activeTab, setActiveTab, onLogout }) {
  const [focusMode, setFocusMode] = useState(false)
  const [showFloatingOrder, setShowFloatingOrder] = useState(false)
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showCorrelation, setShowCorrelation] = useState(false)

  const {
    symbol, setSymbol, timeframe, setTimeframe, ohlcv, snapshot, prediction,
    indicators, setIndicators, indicatorData, loading, errorMsg, isMockData,
    marketStatus, activeSignal, setActiveSignal
  } = engine

  const strongSignal = prediction && prediction.confidence >= 70 && prediction.signal !== 'HOLD'

  if (loading && (!ohlcv || ohlcv.length < 10)) {
    return (
      <div className="flex flex-col items-center justify-center h-screen w-screen bg-[#0b0f14]">
        <div className="w-8 h-8 border-2 border-teal-500/30 border-t-teal-500 rounded-full animate-spin mb-4" />
        <div className="text-teal-500/70 font-mono text-xs animate-pulse">Fetching market data...</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#0b0f14] text-slate-200">
      <MarketClosedBanner status={marketStatus} />
      <MacroBar onSectorClick={() => setShowHeatmap(true)} />

      {/* Mobile Compact Header (Appears universally as strict branding) */}
      <div className="shrink-0 flex items-center justify-between px-4 py-3 border-b border-white/5 bg-[#0B0F14]/80">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-teal-400 text-sm">{symbol}</span>
          {snapshot?.ltp && (
            <span className="font-mono text-xs text-slate-300">
              ₹{Number(snapshot.ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onLogout} className="px-3 py-2 rounded-lg text-slate-500 text-[10px] font-mono border border-white/5 touch-target bg-transparent hover:bg-white/5">Logout</button>
          <button onClick={() => setShowHeatmap(true)} className="p-2.5 rounded-lg text-slate-500 bg-white/5 active:bg-white/10 touch-target ml-1">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>
          </button>
          <button onClick={() => setShowFloatingOrder(true)} className="p-2.5 rounded-lg text-slate-500 bg-white/5 active:bg-white/10 touch-target">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8V7m0 10v1" /></svg>
          </button>
        </div>
      </div>

      <main className={`flex-1 w-full h-full min-h-0 overflow-hidden relative transition-all ${focusMode ? 'opacity-0 pointer-events-none' : ''}`}>
        
        {/* CENTER: Chart Tab */}
        {activeTab === 'chart' && (
          <section className="w-full h-full flex flex-col bg-[#0b0f14]">
            {/* Toolbar */}
            <div className="shrink-0 flex items-center justify-between gap-3 px-2 py-1 border-b border-white/5 bg-black/20">
              <div className="flex-1 min-w-0">
                <ChartToolbar timeframe={timeframe} setTimeframe={setTimeframe} indicators={indicators} setIndicators={setIndicators} />
              </div>
            </div>

            {errorMsg ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
                 <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mb-3">
                   <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                 </div>
                 <div className="text-red-400 font-mono text-sm">{errorMsg}</div>
                 <div className="text-slate-500 font-mono text-xs mt-2">Try switching directly to another symbol or wait for market sync.</div>
              </div>
            ) : (
                <div className="flex-1 min-h-[300px] w-full relative flex flex-col">
                  <ErrorBoundary>
                    <DecisionChartCanvas
                      ohlcv={ohlcv} symbol={symbol} snapshot={snapshot} isMockData={isMockData}
                      timeframe={timeframe} focusMode={focusMode} onFocusToggle={() => setFocusMode(!focusMode)}
                      indicators={indicators} indicatorData={indicatorData} prediction={prediction} onPaginateHistory={engine.loadMoreHistory} />
                  </ErrorBoundary>
                </div>
            )}

            <div className="shrink-0 w-full px-2 py-1">
              <DecisionTimeline prediction={prediction} />
            </div>
          </section>
        )}

        {/* Symbols Tab */}
        {activeTab === 'symbols' && (
          <div className="w-full h-full overflow-hidden" style={{ paddingBottom: '60px' }}>
            <DataStreamPanel
              selected={symbol} onSelect={(s) => { setSymbol(s); setActiveTab('chart') }}
              snapshot={snapshot} onQuickOrder={(s) => { setSymbol(s); setShowFloatingOrder(true); setActiveTab('chart') }} />
          </div>
        )}

        {activeTab === 'watchlist' && (
          <div className="w-full h-full overflow-hidden" style={{ paddingBottom: '60px' }}>
            <WatchlistPanel
              selected={symbol} onSelect={(s) => { setSymbol(s); setActiveTab('chart') }} snapshot={snapshot} />
          </div>
        )}

        {activeTab === 'signal' && (
          <div className="w-full h-full overflow-y-auto" style={{ paddingBottom: '60px', WebkitOverflowScrolling: 'touch' }}>
            <ErrorBoundary>
              <IntelligencePanel prediction={prediction} snapshot={snapshot} symbol={symbol} hideNews={true} />
            </ErrorBoundary>
          </div>
        )}
      </main>

      {/* Global Bottom Navigation Bar (Tabs) */}
      <nav className="mobile-bottom-nav z-[40]">
        <button className={activeTab === 'chart' ? 'active' : ''} onClick={() => setActiveTab('chart')}>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3v18h18" /></svg> Chart
        </button>
        <button className={activeTab === 'symbols' ? 'active' : ''} onClick={() => setActiveTab('symbols')}>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg> Symbols
        </button>
        <button className={activeTab === 'watchlist' ? 'active' : ''} onClick={() => setActiveTab('watchlist')}>
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" /></svg> Watchlist
        </button>
        <button className={activeTab === 'signal' ? 'active' : ''} onClick={() => setActiveTab('signal')}>
          <div className="relative">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
            {strongSignal && <span className={`absolute -top-1 -right-1 w-2 h-2 rounded-full ${prediction.signal === 'BUY' ? 'bg-emerald-400' : 'bg-red-400'} animate-pulse`} />}
          </div>
          Signal
        </button>
      </nav>

      {/* Modals and Overlays */}
      <AnimatePresence>
        {showHeatmap && (
            <motion.div
              initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }} transition={{ type: 'spring', damping: 28, stiffness: 280 }}
              className="modal-mobile-fullscreen"
            >
              <div className="modal-header">
                <h3 className="text-sm font-mono font-semibold text-slate-200">Sector Heatmap</h3>
                <button onClick={() => setShowHeatmap(false)} className="p-2 text-slate-400 touch-target"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg></button>
              </div>
              <div className="modal-body"><SectorHeatmap onSectorClick={() => setShowHeatmap(false)} /></div>
            </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showCorrelation && (
            <motion.div
              initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }} transition={{ type: 'spring', damping: 28, stiffness: 280 }}
              className="modal-mobile-fullscreen"
            >
              <div className="modal-header">
                <h3 className="text-sm font-mono font-semibold text-slate-200">Correlation Matrix</h3>
                <button onClick={() => setShowCorrelation(false)} className="p-2 text-slate-400 touch-target"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg></button>
              </div>
              <div className="modal-body"><CorrelationMatrix /></div>
            </motion.div>
        )}
      </AnimatePresence>

      {showFloatingOrder && (
         <MobileDrawer open={showFloatingOrder} onClose={() => setShowFloatingOrder(false)} title="Place Order">
            <OrderEntry symbol={symbol} snapshot={snapshot} />
         </MobileDrawer>
      )}

      <AnimatePresence>
        {activeSignal && (
          <SignalToast signal={activeSignal.signal} symbol={symbol} confidence={activeSignal.confidence} target={activeSignal.target} onClose={() => setActiveSignal(null)} />
        )}
      </AnimatePresence>
    </div>
  )
}
