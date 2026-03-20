import { motion, AnimatePresence } from 'framer-motion'
import { useState, useRef, useEffect } from 'react'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1d']

// Map display name → backend indicator keys that get requested
const INDICATOR_CATALOG = [
  { id: 'scalp_pro', label: 'Scalp Pro', desc: 'Buy/Sell signals', color: '#22d3ee', keys: ['scalp_pro'] },
  { id: 'ema', label: 'EMA 9/15', desc: 'Exponential Moving Average', color: '#38bdf8', keys: ['ema9', 'ema15'] },
  { id: 'rsi9', label: 'RSI', desc: 'Relative Strength Index', color: '#a78bfa', keys: ['rsi9'] },
  { id: 'macd', label: 'MACD', desc: 'Moving Avg Convergence Divergence', color: '#34d399', keys: ['macd'] },
  { id: 'vwap', label: 'VWAP', desc: 'Volume Weighted Avg Price', color: '#fbbf24', keys: ['vwap'] },
  { id: 'supertrend', label: 'SuperTrend', desc: 'Trend following', color: '#fb923c', keys: ['supertrend'] },
  { id: 'bb', label: 'Bollinger', desc: 'Bollinger Bands', color: '#4ade80', keys: ['bb'] },
  { id: 'atr14', label: 'ATR', desc: 'Average True Range', color: '#94a3b8', keys: ['atr14'] },
  { id: 'obv', label: 'OBV', desc: 'On Balance Volume', color: '#818cf8', keys: ['obv'] },
  { id: 'adx14', label: 'ADX', desc: 'Avg Directional Index', color: '#f97316', keys: ['adx14'] },
  { id: 'stoch', label: 'Stochastic', desc: 'Stochastic Oscillator', color: '#ec4899', keys: ['stoch'] },
  { id: 'ichimoku', label: 'Ichimoku', desc: 'Ichimoku Cloud', color: '#06b6d4', keys: ['tenkan_sen'] },
]

export default function ChartToolbar({ timeframe, setTimeframe, indicators, setIndicators }) {
  const [showIndicators, setShowIndicators] = useState(false)
  const dropdownRef = useRef(null)

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowIndicators(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const toggleIndicator = (ind) => {
    setIndicators(prev => {
      if (prev.includes(ind.id)) {
        return prev.filter(x => x !== ind.id)
      }
      return [...prev, ind.id]
    })
  }

  const activeCount = indicators.length

  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide mobile-chips">
        {TIMEFRAMES.map(tf => (
          <motion.button
            key={tf}
            onClick={() => setTimeframe(tf)}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono transition flex-shrink-0
              ${timeframe === tf ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40 tf-active' : 'text-slate-500 hover:text-slate-300 border border-transparent'}`}
          >
            {tf === '1d' ? '1D' : tf}
          </motion.button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <div className="relative" ref={dropdownRef}>
          <motion.button
            onClick={() => setShowIndicators(!showIndicators)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition-all
              ${activeCount > 0 ? 'text-teal-400 border border-teal-500/30 bg-teal-500/10' : 'text-slate-400 border border-white/5 hover:text-teal-400 hover:border-teal-500/30'}`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" /></svg>
            Indicators
            {activeCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full bg-teal-500/30 text-teal-300 text-[10px] font-bold">{activeCount}</span>
            )}
          </motion.button>
          <AnimatePresence>
            {showIndicators && (
              <motion.div
                initial={{ opacity: 0, y: -5, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -5, scale: 0.97 }}
                transition={{ duration: 0.15 }}
                className="absolute top-full right-0 mt-2 w-[260px] rounded-[12px] border border-white/5 py-1 z-[1000] shadow-2xl flex flex-col"
                style={{
                  background: 'rgba(18, 24, 33, 0.75)',
                  backdropFilter: 'blur(12px)',
                  maxHeight: '400px'
                }}
              >
                <div className="px-3 py-2 text-[10px] uppercase tracking-wider text-slate-500 font-mono shrink-0">Select Indicators</div>
                <div className="flex-1 overflow-y-auto custom-scrollbar">
                {INDICATOR_CATALOG.map(ind => {
                  const isActive = indicators.includes(ind.id)
                  return (
                    <button
                      key={ind.id}
                      onClick={() => toggleIndicator(ind)}
                      className={`w-full px-3 py-2 text-left flex items-center justify-between gap-2 transition-all
                        ${isActive ? 'bg-white/5' : 'hover:bg-white/5'}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: isActive ? ind.color : '#334155' }} />
                        <div className="flex flex-col">
                          <span className={`text-xs font-mono ${isActive ? 'text-slate-200' : 'text-slate-400'}`}>{ind.label}</span>
                          <span className="text-[10px] text-slate-600">{ind.desc}</span>
                        </div>
                      </div>
                      {isActive && <span className="text-teal-500 text-sm">✓</span>}
                    </button>
                  )
                })}
                </div>
                {activeCount > 0 && (
                  <div className="border-t border-white/5 pt-1.5 px-3 pb-1.5 sticky bottom-0 shrink-0" style={{ background: 'rgba(18, 24, 33, 0.95)' }}>
                    <button
                      onClick={() => setIndicators([])}
                      className="w-full py-1.5 rounded-lg text-xs font-mono text-red-400 hover:text-red-300 hover:bg-white/5 text-center transition-colors"
                    >
                      Clear All
                    </button>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

// Export the catalog so App.jsx can resolve indicator keys for backend
export { INDICATOR_CATALOG }
