import { useState } from 'react'
import { motion } from 'framer-motion'

const SECTORS = [
  { id: 'nifty', name: 'NIFTY', change: 0.82 },
  { id: 'bank', name: 'Bank', change: 1.2 },
  { id: 'it', name: 'IT', change: -0.3 },
  { id: 'auto', name: 'Auto', change: 0.5 },
  { id: 'pharma', name: 'Pharma', change: 1.1 },
  { id: 'fmg', name: 'FMCG', change: -0.2 },
  { id: 'metal', name: 'Metal', change: 0.9 },
  { id: 'energy', name: 'Energy', change: -0.5 },
]

export default function SectorHeatmap({ onSectorClick }) {
  const [hovered, setHovered] = useState(null)

  const getColor = (change) => {
    const intensity = Math.min(1, Math.abs(change) / 2)
    if (change >= 0) return `rgba(16, 185, 129, ${0.3 + intensity * 0.6})`
    return `rgba(239, 68, 68, ${0.3 + intensity * 0.6})`
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-2xl border border-white/5 bg-black/30 backdrop-blur-xl p-4"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 font-mono mb-3">Sector Heatmap</h3>
      <div className="grid grid-cols-4 gap-2">
        {SECTORS.map((s, i) => (
          <motion.button
            key={s.id}
            onClick={() => onSectorClick?.(s)}
            onMouseEnter={() => setHovered(s.id)}
            onMouseLeave={() => setHovered(null)}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.98 }}
            className="rounded-xl p-3 border border-white/5 text-center transition-all"
            style={{
              background: getColor(s.change),
              boxShadow: hovered === s.id ? `0 0 20px ${getColor(s.change)}` : 'none',
            }}
          >
            <span className="text-xs font-mono text-slate-200 block">{s.name}</span>
            <span className={`text-sm font-mono font-bold ${s.change >= 0 ? 'text-emerald-100' : 'text-red-100'}`}>
              {s.change >= 0 ? '+' : ''}{s.change}%
            </span>
          </motion.button>
        ))}
      </div>
    </motion.div>
  )
}
