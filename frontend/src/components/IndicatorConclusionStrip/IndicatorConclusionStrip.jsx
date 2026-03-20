import { motion } from 'framer-motion'

const INDICATORS = [
  { id: 'rsi', label: 'RSI', icon: 'R', signal: 'Bullish', text: 'RSI 45, recovering from oversold', color: 'emerald' },
  { id: 'macd', label: 'MACD', icon: 'M', signal: 'Bullish', text: 'MACD crossover, momentum building', color: 'emerald' },
  { id: 'volume', label: 'Volume', icon: 'V', signal: 'Neutral', text: 'Volume below average', color: 'amber' },
  { id: 'trend', label: 'EMA / SuperTrend', icon: 'E', signal: 'Bullish', text: 'Price above EMA9 & EMA15', color: 'emerald' },
]

export default function IndicatorConclusionStrip({ conclusions }) {
  const data = conclusions || INDICATORS

  return (
    <div className="flex gap-3 px-4 py-3 border-t border-white/5 bg-black/30 backdrop-blur-sm">
      <h4 className="text-xs uppercase tracking-wider text-slate-500 font-mono self-center shrink-0">Insights</h4>
      <div className="flex flex-1 gap-3 overflow-x-auto scrollbar-hide">
        {data.map((item, i) => {
          const color = item.color || (item.signal === 'Bullish' ? 'emerald' : item.signal === 'Bearish' ? 'red' : 'amber')
          const bg = `bg-${color}-500/10`
          const border = `border-${color}-500/30`
          const text = `text-${color}-400`

          return (
            <motion.div
              key={item.id || i}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}
              className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border bg-white/[0.02] min-w-[200px]
                ${color === 'emerald' ? 'bg-emerald-500/5 border-emerald-500/20' : color === 'red' ? 'bg-red-500/5 border-red-500/20' : 'bg-amber-500/5 border-amber-500/20'}`}
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-mono font-bold text-sm
                ${color === 'emerald' ? 'bg-emerald-500/20 text-emerald-400' : color === 'red' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
                {item.icon || item.label?.[0]}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-slate-400">{item.label}</span>
                  <span className={`text-xs font-mono font-semibold
                    ${color === 'emerald' ? 'text-emerald-400' : color === 'red' ? 'text-red-400' : 'text-amber-400'}`}>
                    {item.signal}
                  </span>
                </div>
                <p className="text-xs text-slate-400 truncate mt-0.5">{item.text}</p>
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
