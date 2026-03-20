import { motion } from 'framer-motion'

export default function SignalPanel({ prediction, snapshot, symbol }) {
  if (!prediction) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm p-4 text-center">
        <p className="text-slate-500 font-mono text-xs">No Data Available</p>
      </motion.div>
    )
  }

  const signal = prediction?.signal ?? 'No Signal'
  const conf = prediction?.confidence ?? '--'
  const regime = prediction?.regime ?? '--'
  const isBuy = signal === 'BUY'
  const isSell = signal === 'SELL'
  const predPrice = prediction?.prediction ?? snapshot?.ltp ?? 0

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl border backdrop-blur-sm p-4
        ${isBuy ? 'border-emerald-500/30 bg-emerald-500/5' : isSell ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-white/[0.02]'}`}
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">Signal</h3>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <span className={`px-4 py-2 rounded-xl text-lg font-mono font-bold
            ${isBuy ? 'bg-emerald-500/20 text-emerald-400' : isSell ? 'bg-red-500/20 text-red-400' : 'bg-slate-500/20 text-slate-400'}`}>
            {signal}
          </span>
          <span className="px-2.5 py-1 rounded-lg text-xs font-mono bg-white/5 text-slate-400">{regime}</span>
        </div>
        <div>
          <div className="flex justify-between items-center mb-1">
            <p className="text-xs text-slate-500">Confidence</p>
            {conf !== '--' && conf < 10 && <span className="text-[10px] text-amber-500/90 font-mono">Low Confidence</span>}
          </div>
          <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
            <motion.div
              className={`h-full rounded-full ${isBuy ? 'bg-emerald-500' : isSell ? 'bg-red-500' : 'bg-slate-500'}`}
              initial={{ width: 0 }}
              animate={{ width: conf === '--' ? 0 : `${conf}%` }}
              transition={{ duration: 0.6 }}
            />
          </div>
          <p className="text-xs text-slate-500 mt-1">{conf === '--' ? '--' : `${conf}%`}</p>
        </div>
        {prediction?.stop && (
          <div className="pt-3 border-t border-white/5 flex justify-between items-center text-xs">
            <p className="text-amber-500/90">Risk: Stop ₹{prediction.stop.toFixed(2)}</p>
            {prediction?.target && <p className="text-emerald-500/90">Target: ₹{prediction.target.toFixed(2)}</p>}
          </div>
        )}
      </div>
    </motion.div>
  )
}
