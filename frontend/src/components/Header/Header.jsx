import { motion } from 'framer-motion'

const TIMEFRAMES = [
  { id: '1m', label: '1m' },
  { id: '3m', label: '3m' },
  { id: '5m', label: '5m' },
  { id: '15m', label: '15m' },
  { id: '30m', label: '30m' },
  { id: '1h', label: '1h' },
]

export default function Header({ timeframe, setTimeframe }) {
  return (
    <header className="h-14 border-b border-white/5 bg-[#0b0f14]/95 backdrop-blur-sm flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-4">
        <span className="text-xl font-bold text-teal-400 font-mono tracking-tight">StockAI Pro</span>
        <span className="text-slate-500 text-sm font-mono">AngelOne SmartAPI</span>
      </div>
      <nav className="flex gap-1">
        {TIMEFRAMES.map((tf) => (
          <motion.button
            key={tf.id}
            onClick={() => setTimeframe(tf.id)}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className={`px-4 py-2 rounded-lg text-sm font-mono transition-all
              ${timeframe === tf.id
                ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40 shadow-[0_0_12px_rgba(20,184,166,0.15)]'
                : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
              }`}
          >
            {tf.label}
          </motion.button>
        ))}
      </nav>
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500 font-mono">Paper</span>
        <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
      </div>
    </header>
  )
}
