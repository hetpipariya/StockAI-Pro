import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'SBIN', 'ICICIBANK', 'TATASTEEL', 'ITC', 'NIFTY 50']

const BASE_PRICES = { RELIANCE: 2500, TCS: 3800, INFY: 1550, HDFCBANK: 1680, SBIN: 780, ICICIBANK: 1180, TATASTEEL: 145, ITC: 465, 'NIFTY 50': 24000 }

function StockCard({ s, selected, onSelect, ltp, change }) {
  const base = BASE_PRICES[s] || 1000
  const price = ltp ?? base
  const pct = change ?? (Math.random() - 0.5) * 2
  const isUp = pct >= 0
  const sparkline = useMemo(() => Array.from({ length: 12 }, () => base * (1 + (Math.random() - 0.5) * 0.02)), [base])

  return (
    <motion.button
      onClick={() => onSelect(s)}
      whileHover={{ x: 2 }}
      whileTap={{ scale: 0.98 }}
      className={`w-full text-left px-4 py-3 rounded-xl transition-all border
        ${selected === s
          ? 'bg-teal-500/10 border-teal-500/40 shadow-[0_0_20px_rgba(20,184,166,0.15)]'
          : 'border-white/5 hover:border-white/10 hover:bg-white/[0.03]'
        }`}
    >
      <div className="flex justify-between items-start mb-1">
        <span className="font-mono font-semibold text-slate-200">{s}</span>
        <span className={`font-mono text-sm ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
          {isUp ? '+' : ''}{pct.toFixed(2)}%
        </span>
      </div>
      <div className="text-lg font-mono font-bold text-teal-400">
        ₹ {price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      <svg viewBox="0 0 120 24" className="h-6 w-full mt-2 opacity-60" preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke={isUp ? '#10b981' : '#ef4444'}
          strokeWidth="1"
          points={sparkline.map((v, i) => `${i * 10},${24 - ((v - Math.min(...sparkline)) / (Math.max(...sparkline) - Math.min(...sparkline) || 1)) * 20}`).join(' ')}
        />
      </svg>
    </motion.button>
  )
}

export default function Watchlist({ selected, onSelect, snapshot }) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(() => {
    if (!search.trim()) return SYMBOLS
    const q = search.toUpperCase()
    return SYMBOLS.filter((s) => s.includes(q))
  }, [search])

  return (
    <div className="p-4 flex flex-col h-full">
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">Watchlist</h3>
      <input
        type="text"
        placeholder="Search symbols..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-slate-200 placeholder-slate-500 font-mono text-sm mb-4 focus:outline-none focus:border-teal-500/50 focus:ring-1 focus:ring-teal-500/30"
      />
      <ul className="space-y-2 overflow-y-auto flex-1 pr-1">
        <AnimatePresence mode="popLayout">
          {filtered.map((s) => (
            <motion.li
              key={s}
              layout
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <StockCard
                s={s}
                selected={selected}
                onSelect={onSelect}
                ltp={selected === s ? snapshot?.ltp : null}
              />
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </div>
  )
}
