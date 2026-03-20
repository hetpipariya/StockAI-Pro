import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'

const MOVERS = [
  { symbol: 'NIFTY 50', base: 24000 },
  { symbol: 'BANKNIFTY', base: 52000 },
  { symbol: 'RELIANCE', base: 2500 },
  { symbol: 'TCS', base: 3800 },
  { symbol: 'INFY', base: 1550 },
  { symbol: 'HDFCBANK', base: 1680 },
  { symbol: 'SBIN', base: 780 },
  { symbol: 'ICICIBANK', base: 1180 },
  { symbol: 'TATASTEEL', base: 145 },
  { symbol: 'ITC', base: 465 },
]

function MoverCard({ item, ltp, onChange, onSelect }) {
  const base = item.base
  const price = ltp ?? base
  const pct = ((price - base) / base) * 100
  const isUp = pct >= 0
  const sparkline = Array.from({ length: 8 }, (_, i) => base * (1 + (Math.random() - 0.5) * 0.02))

  return (
    <motion.button
      onClick={() => onSelect(item.symbol)}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      className="flex-shrink-0 w-28 rounded-xl bg-white/[0.03] border border-white/5 hover:border-teal-500/30 px-3 py-2.5 transition-all"
    >
      <span className="text-xs font-mono text-slate-400 block truncate">{item.symbol}</span>
      <span className="text-sm font-mono font-bold text-teal-400">₹ {(price / 1000).toFixed(1)}k</span>
      <span className={`text-xs font-mono ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
        {isUp ? '+' : ''}{pct.toFixed(2)}%
      </span>
      <svg viewBox="0 0 64 16" className="h-4 w-full mt-1 opacity-60" preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke={isUp ? '#10b981' : '#ef4444'}
          strokeWidth="1"
          points={sparkline.map((v, i) => `${i * 8},${16 - ((v - Math.min(...sparkline)) / (Math.max(...sparkline) - Math.min(...sparkline) || 1)) * 12}`).join(' ')}
        />
      </svg>
    </motion.button>
  )
}

export default function MarketMoversRail({ snapshot, onSelect }) {
  const railRef = useRef(null)
  const [position, setPosition] = useState(0)

  return (
    <div className="relative overflow-hidden border-b border-white/5 bg-black/20">
      <motion.div
        ref={railRef}
        className="flex gap-3 py-3 px-4 overflow-x-auto scrollbar-hide"
        animate={{ x: position }}
        transition={{ duration: 0.5 }}
      >
        {MOVERS.map((item) => (
          <MoverCard key={item.symbol} item={item} onSelect={onSelect} />
        ))}
      </motion.div>
    </div>
  )
}
