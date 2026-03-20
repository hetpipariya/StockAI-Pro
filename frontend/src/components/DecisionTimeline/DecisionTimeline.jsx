import { motion } from 'framer-motion'

export default function DecisionTimeline({ prediction }) {
  const signal = prediction?.signal || 'HOLD'
  const conf = prediction?.confidence || 0
  const isBuy = signal === 'BUY'
  const isSell = signal === 'SELL'

  const biasText = isBuy
    ? 'Indicators confirm bullish bias'
    : isSell
      ? 'Indicators confirm bearish bias'
      : 'Indicators show neutral stance'

  const biasColor = isBuy ? 'emerald' : isSell ? 'red' : 'amber'

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-4 px-4 py-2 bg-black/30 backdrop-blur-sm border-t border-white/5 rounded-xl"
    >
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg bg-${biasColor}-500/10 border border-${biasColor}-500/20`}>
        <svg className={`w-4 h-4 text-${biasColor}-400`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <span className={`text-xs font-mono font-semibold text-${biasColor}-400`}>
          {biasText}
        </span>
      </div>

      {conf > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-slate-500">Confidence</span>
          <div className="w-20 h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <motion.div
              className={`h-full rounded-full bg-${biasColor}-500`}
              initial={{ width: 0 }}
              animate={{ width: `${conf}%` }}
              transition={{ duration: 0.8 }}
            />
          </div>
          <span className={`text-[10px] font-mono font-bold text-${biasColor}-400`}>{conf}%</span>
        </div>
      )}
    </motion.div>
  )
}
