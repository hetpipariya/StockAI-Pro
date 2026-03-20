import { motion } from 'framer-motion'

export default function PredictionCard({ prediction, snapshot, symbol }) {
  if (!prediction && !snapshot) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm p-4">
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">AI Prediction</h3>
        <p className="text-slate-500 text-sm">Select a symbol for prediction</p>
      </div>
    )
  }

  const isBuy = prediction?.signal === 'BUY'
  const isSell = prediction?.signal === 'SELL'
  const predPrice = prediction?.prediction ?? snapshot?.ltp ?? 0
  const ltp = snapshot?.ltp ?? predPrice
  const conf = prediction?.confidence ?? 0
  const pctChange = ltp ? (((predPrice - ltp) / ltp) * 100).toFixed(2) : '0.00'
  const regime = prediction?.regime || 'Trending'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl border backdrop-blur-sm p-4
        ${isBuy ? 'border-emerald-500/30 bg-emerald-500/5' : isSell ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-white/[0.02]'}`}
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">AI Prediction</h3>
      <div className="space-y-4">
        <div>
          <p className="text-slate-500 text-sm mb-1">15m target</p>
          <p className={`text-4xl font-mono font-extrabold ${isBuy ? 'text-emerald-400' : isSell ? 'text-red-400' : 'text-slate-300'}`}>
            ₹ {Number(predPrice).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </p>
          <p className={`text-sm font-mono mt-1 ${Number(pctChange) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {Number(pctChange) >= 0 ? '+' : ''}{pctChange}% expected
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-3 py-1.5 rounded-lg text-sm font-mono font-semibold
            ${isBuy ? 'bg-emerald-500/20 text-emerald-400' : isSell ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
            {prediction?.signal || 'HOLD'}
          </span>
          <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-white/5 text-slate-400">{regime}</span>
        </div>
        <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
          <motion.div
            className={`h-full rounded-full ${isBuy ? 'bg-emerald-500' : isSell ? 'bg-red-500' : 'bg-amber-500'}`}
            initial={{ width: 0 }}
            animate={{ width: `${conf}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
        <p className="text-xs text-slate-500">Confidence: {conf}%</p>
        {(prediction?.stop || prediction?.target) && (
          <div className="flex gap-6 text-sm pt-2 border-t border-white/5">
            <div>
              <span className="text-slate-500">Stop Loss</span>
              <p className="font-mono text-red-400">₹ {prediction.stop?.toFixed(2)}</p>
            </div>
            <div>
              <span className="text-slate-500">Target</span>
              <p className="font-mono text-emerald-400">₹ {prediction.target?.toFixed(2)}</p>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
