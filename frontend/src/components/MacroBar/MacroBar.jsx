import { motion } from 'framer-motion'
import { useState } from 'react'

const SECTORS = [
  { id: 'nifty', name: 'NIFTY', value: 24250, change: 0.82 },
  { id: 'bank', name: 'Bank', value: 52100, change: 1.2 },
  { id: 'it', name: 'IT', value: 38500, change: -0.3 },
  { id: 'auto', name: 'Auto', value: 18500, change: 0.5 },
  { id: 'pharma', name: 'Pharma', value: 24500, change: 1.1 },
  { id: 'fmg', name: 'FMCG', value: 15200, change: -0.2 },
  { id: 'nifty-dup', name: 'NIFTY', value: 24250, change: 0.82 },
  { id: 'bank-dup', name: 'Bank', value: 52100, change: 1.2 },
  { id: 'it-dup', name: 'IT', value: 38500, change: -0.3 },
  { id: 'auto-dup', name: 'Auto', value: 18500, change: 0.5 },
]

export default function MacroBar({ onSectorClick }) {
  const heat = (change) => Math.min(100, Math.abs(change) * 50 + 20)
  const [isHovered, setIsHovered] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      // Glass effect sampurna kadhi nakhyo! Khali solid dark color.
      className="flex items-center px-4 py-2 border-b border-white/10 bg-[#070a0e] z-10 relative"
    >
      <div className="flex items-center pr-4 shrink-0 bg-[#070a0e] z-20 h-full">
         <span className="text-xs font-mono text-slate-500 uppercase tracking-wider">Market</span>
      </div>
      
      <div 
        className="flex-1 overflow-hidden relative"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        style={{ maskImage: 'linear-gradient(to right, transparent, black 15px, black calc(100% - 15px), transparent)', WebkitMaskImage: 'linear-gradient(to right, transparent, black 15px, black calc(100% - 15px), transparent)' }}
      >
        <motion.div 
          className="flex gap-3 whitespace-nowrap pl-4"
          animate={{ x: isHovered ? undefined : ["0%", "-50%"] }}
          transition={{
            x: { repeat: Infinity, repeatType: "loop", duration: 30, ease: "linear" }
          }}
          style={{ width: "max-content" }}
        >
          {SECTORS.map((s, i) => (
            <motion.button
              key={`${s.id}-${i}`}
              onClick={() => onSectorClick?.(s)}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="flex items-center gap-2 px-4 py-1.5 rounded-xl bg-white/[0.02] border border-white/5 hover:border-teal-500/30 shrink-0"
            >
              <span className="text-sm font-mono text-slate-300">{s.name}</span>
              <span className={`text-xs font-mono font-bold ${s.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {s.change >= 0 ? '+' : ''}{s.change}%
              </span>
            </motion.button>
          ))}
        </motion.div>
      </div>

      <div className="flex items-center gap-2 shrink-0 bg-[#070a0e] pl-4 z-20 h-full">
        <span className="text-xs text-slate-500 font-mono">Sentiment</span>
        <motion.div className="w-16 h-1.5 rounded-full bg-slate-800 overflow-hidden">
          <motion.div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500" initial={{ width: 0 }} animate={{ width: '68%' }} transition={{ duration: 0.8 }} />
        </motion.div>
        <span className="text-[10px] font-mono text-emerald-400">Bullish</span>
      </div>
    </motion.div>
  )
}