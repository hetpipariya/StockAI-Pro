const INDICATOR_OPTIONS = [
  { id: 'ema9', label: 'EMA 9' },
  { id: 'ema15', label: 'EMA 15' },
  { id: 'ema20', label: 'EMA 20' },
  { id: 'sma20', label: 'SMA 20' },
  { id: 'vwap', label: 'VWAP' },
  { id: 'rsi', label: 'RSI 9' },
  { id: 'macd', label: 'MACD' },
  { id: 'supertrend', label: 'SuperTrend' },
  { id: 'bb', label: 'Bollinger' },
  { id: 'atr', label: 'ATR' },
  { id: 'obv', label: 'OBV' },
  { id: 'adx', label: 'ADX' },
  { id: 'stoch', label: 'Stochastic' },
  { id: 'cci', label: 'CCI' },
  { id: 'roc', label: 'Momentum' },
  { id: 'zigzag', label: 'ZigZag' },
  { id: 'pivot', label: 'Pivots' },
]

export default function IndicatorsPanel({ indicators, setIndicators }) {
  const toggle = (id) => {
    setIndicators((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  return (
    <div className="px-4 py-3 border-t border-white/5 bg-black/20">
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2 font-mono">Indicators</h3>
      <div className="flex flex-wrap gap-2">
        {INDICATOR_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            onClick={() => toggle(opt.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono transition
              ${indicators.includes(opt.id)
                ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40'
                : 'border border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20'
              }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
