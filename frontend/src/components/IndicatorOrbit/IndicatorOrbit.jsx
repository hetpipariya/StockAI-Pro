import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const WIDGETS = [
  { id: 'rsi', label: 'RSI', value: 52, signal: 'Neutral', color: 'amber' },
  { id: 'macd', label: 'MACD', value: 1.2, signal: 'Bullish', color: 'emerald' },
  { id: 'vol', label: 'Vol', value: 85, signal: 'High', color: 'teal' },
  { id: 'trend', label: 'Trend', value: 'UP', signal: 'Bullish', color: 'emerald' },
]

// Adjust positions so they stay at corners of the chart without blocking the view
const positions = [
  { top: '10px', left: '10px' },
  { top: '10px', right: '10px' },
  { bottom: '10px', left: '10px' },
  { bottom: '10px', right: '10px' },
]

export default function IndicatorOrbit({ expandedId, onExpand }) {
  const [hoverId, setHoverId] = useState(null)

  const getColor = (c) => {
    if (c === 'emerald') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
    if (c === 'red') return 'border-red-500/40 bg-red-500/10 text-red-400'
    if (c === 'teal') return 'border-teal-500/40 bg-teal-500/10 text-teal-400'
    return 'border-amber-500/40 bg-amber-500/10 text-amber-400'
  }

  return (
    <>
      {WIDGETS.map((w, i) => (
        <motion.div
          key={w.id}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: i * 0.1, type: 'spring', stiffness: 200 }}
          style={positions[i]}
          className={`absolute z-10 w-12 h-12 sm:w-14 sm:h-14 rounded-xl border backdrop-blur-md cursor-pointer
            ${getColor(w.color)} flex flex-col items-center justify-center
            ${expandedId === w.id ? 'ring-2 ring-teal-500/60 scale-110' : ''}
            hover:scale-110 transition-transform shadow-lg`}
          onClick={() => onExpand(expandedId === w.id ? null : w.id)}
          onMouseEnter={() => setHoverId(w.id)}
          onMouseLeave={() => setHoverId(null)}
        >
          <span className="text-[10px] font-mono text-slate-400">{w.label}</span>
          <span className="text-xs font-mono font-bold">{typeof w.value === 'number' ? w.value : w.value}</span>
        </motion.div>
      ))}
      <AnimatePresence>
        {expandedId && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            // Popup ne center-bottom ma graph ni exactly upar aavse
            className="absolute bottom-16 left-1/2 -translate-x-1/2 z-30 w-64 rounded-xl border border-white/10 bg-slate-900/95 backdrop-blur-xl p-4 shadow-2xl"
          >
            <div className="flex justify-between items-center mb-3">
              <span className="text-sm font-mono font-semibold text-slate-200">{WIDGETS.find(w => w.id === expandedId)?.label} Details</span>
              <button onClick={() => onExpand(null)} className="text-slate-500 hover:text-white">×</button>
            </div>
            <p className="text-xs text-slate-400">Signal: {WIDGETS.find(w => w.id === expandedId)?.signal}</p>
            <p className="text-xs text-slate-400 mt-1">Real-time indicator data will appear here.</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}