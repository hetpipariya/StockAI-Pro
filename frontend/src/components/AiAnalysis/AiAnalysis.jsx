import { motion } from 'framer-motion'

export default function AiAnalysis({ prediction, snapshot, symbol }) {
  if (!prediction && !snapshot) return null

  const signal = prediction?.signal || 'HOLD'
  const isBullish = signal === 'BUY'
  const isBearish = signal === 'SELL'
  const ltp = snapshot?.ltp || 0
  const predPrice = prediction?.prediction || ltp
  const conf = prediction?.confidence || 0
  const factors = prediction?.factors || [
    'RSI trending towards neutral zone',
    'Volume below average',
    'Price consolidating near support',
  ].slice(0, 3)

  const sentiment = isBullish ? 'Bullish' : isBearish ? 'Bearish' : 'Neutral'
  const sentimentColor = isBullish ? 'text-emerald-400' : isBearish ? 'text-red-400' : 'text-amber-400'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm p-4"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">AI Analysis</h3>
      <p className="text-sm text-slate-300 mb-4 leading-relaxed">
        {prediction?.explanation || `Analysis for ${symbol}: Market shows ${sentiment.toLowerCase()} signals.`}
      </p>
      <div className="flex items-center gap-3 mb-3">
        <span className={`text-sm font-semibold ${sentimentColor}`}>{sentiment}</span>
        <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
          <motion.div
            className={`h-full rounded-full ${isBullish ? 'bg-emerald-500' : isBearish ? 'bg-red-500' : 'bg-amber-500'}`}
            initial={{ width: 0 }}
            animate={{ width: `${conf}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
        <span className="text-xs font-mono text-slate-400">{conf}%</span>
      </div>
      <ul className="space-y-1.5 text-xs text-slate-400">
        {factors.map((f, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-teal-500/60" />
            {f}
          </li>
        ))}
      </ul>
    </motion.div>
  )
}
