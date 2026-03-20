import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

// Real-time indicator calculations
const calculateRSI = (closes, period = 14) => {
  if (closes.length < period + 1) return 50
  let gains = 0, losses = 0
  for (let i = closes.length - period; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1]
    if (change > 0) gains += change
    else losses -= change
  }
  const avgGain = gains / period
  const avgLoss = losses / period
  if (avgLoss === 0) return 100
  const rs = avgGain / avgLoss
  return 100 - (100 / (1 + rs))
}

const calculateMACD = (closes) => {
  if (closes.length < 26) return { macd: 0, signal: 0, histogram: 0 }
  const ema12 = calculateEMA(closes, 12)
  const ema26 = calculateEMA(closes, 26)
  const macd = ema12 - ema26
  const signal = calculateEMA([macd], 9) // Simplified
  return { macd, signal, histogram: macd - signal }
}

const calculateEMA = (values, period) => {
  if (values.length < period) return values[values.length - 1] || 0
  const k = 2 / (period + 1)
  let ema = values.slice(0, period).reduce((a, b) => a + b) / period
  for (let i = period; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k)
  }
  return ema
}

const calculateVolumeProfile = (ohlcv) => {
  if (!ohlcv?.length) return { avg: 0, current: 0, ratio: 1 }
  const volumes = ohlcv.map(d => Number(d.volume) || 0)
  const avg = volumes.reduce((a, b) => a + b, 0) / volumes.length
  const current = volumes[volumes.length - 1] || 0
  return { avg, current, ratio: current / avg }
}

const calculateTrend = (closes) => {
  if (closes.length < 20) return { direction: 'Neutral', strength: 0 }
  const recent = closes.slice(-20)
  const ema9 = calculateEMA(recent, 9)
  const ema21 = calculateEMA(recent, 21)
  const direction = ema9 > ema21 ? 'UP' : ema9 < ema21 ? 'DOWN' : 'Neutral'
  const strength = Math.min(100, Math.abs(ema9 - ema21) / ema21 * 1000)
  return { direction, strength }
}

export default function FloatingIndicatorWidgets({ ohlcv, expandedWidget, onWidgetClick }) {
  const [indicators, setIndicators] = useState({
    rsi: 50,
    macd: { macd: 0, signal: 0, histogram: 0 },
    volume: { avg: 0, current: 0, ratio: 1 },
    trend: { direction: 'Neutral', strength: 0 },
  })

  // Calculate indicators from OHLCV data
  useEffect(() => {
    if (!ohlcv?.length) return

    const closes = ohlcv.map(d => Number(d.close))
    const volumes = ohlcv.map(d => Number(d.volume) || 0)

    const rsi = calculateRSI(closes)
    const macd = calculateMACD(closes)
    const volume = calculateVolumeProfile(ohlcv)
    const trend = calculateTrend(closes)

    setIndicators({ rsi, macd, volume, trend })
  }, [ohlcv])

  const widgets = [
    {
      id: 'rsi',
      label: 'RSI',
      value: indicators.rsi.toFixed(0),
      subValue: '%',
      signal: indicators.rsi > 70 ? 'Overbought' : indicators.rsi < 30 ? 'Oversold' : 'Neutral',
      color: indicators.rsi > 70 ? 'red' : indicators.rsi < 30 ? 'emerald' : 'amber',
      min: 0,
      max: 100,
      progress: indicators.rsi,
      sparkline: ohlcv?.slice(-20).map(d => Number(d.close)) || [],
    },
    {
      id: 'volume',
      label: 'Volume',
      value: (indicators.volume.current / 100000).toFixed(2),
      subValue: 'L',
      signal: indicators.volume.ratio > 1.5 ? 'High' : indicators.volume.ratio > 0.8 ? 'Normal' : 'Low',
      color: indicators.volume.ratio > 1.5 ? 'emerald' : indicators.volume.ratio > 0.8 ? 'teal' : 'amber',
      min: 0,
      max: 2,
      progress: Math.min(100, indicators.volume.ratio * 50),
      sparkline: ohlcv?.slice(-20).map(d => Number(d.volume) / 100000) || [],
    },
    {
      id: 'trend',
      label: 'Trend',
      value: indicators.trend.direction,
      subValue: `${indicators.trend.strength.toFixed(0)}%`,
      signal: indicators.trend.direction === 'UP' ? 'Bullish' : indicators.trend.direction === 'DOWN' ? 'Bearish' : 'Sideways',
      color: indicators.trend.direction === 'UP' ? 'emerald' : indicators.trend.direction === 'DOWN' ? 'red' : 'amber',
      min: 0,
      max: 100,
      progress: indicators.trend.strength,
      sparkline: ohlcv?.slice(-20).map(d => Number(d.close)) || [],
    },
  ]

  const getColorClasses = (color) => {
    switch (color) {
      case 'emerald':
        return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
      case 'red':
        return 'border-red-500/40 bg-red-500/10 text-red-400'
      case 'teal':
        return 'border-teal-500/40 bg-teal-500/10 text-teal-400'
      default:
        return 'border-amber-500/40 bg-amber-500/10 text-amber-400'
    }
  }

  const getBgColor = (color) => {
    switch (color) {
      case 'emerald': return 'bg-emerald-500'
      case 'red': return 'bg-red-500'
      case 'teal': return 'bg-teal-500'
      default: return 'bg-amber-500'
    }
  }

  return (
    <>
      {widgets.map((widget, index) => (
        <motion.div
          key={widget.id}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: index * 0.1, type: 'spring', stiffness: 200 }}
          style={{
            position: 'absolute',
            ...(widget.id === 'rsi' && { top: '80px', left: '12px' }),
            ...(widget.id === 'volume' && { bottom: '80px', left: '12px' }),
            ...(widget.id === 'trend' && { top: '80px', right: '12px' }),
          }}
          className={`z-10 w-16 h-16 rounded-xl border backdrop-blur-md cursor-pointer transition-all
            ${getColorClasses(widget.color)} ${expandedWidget === widget.id ? 'ring-2 ring-teal-500/60 scale-110' : ''}
            hover:scale-110 shadow-lg`}
          onClick={() => onWidgetClick(expandedWidget === widget.id ? null : widget.id)}
        >
          <div className="flex flex-col items-center justify-center h-full">
            <span className="text-[9px] font-mono uppercase opacity-70">{widget.label}</span>
            <span className="text-sm font-mono font-bold">{widget.value}</span>
            <span className="text-[9px] font-mono opacity-60">{widget.subValue}</span>
          </div>
        </motion.div>
      ))}

      {/* Expanded Widget Panel */}
      <AnimatePresence>
        {expandedWidget && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 10 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
            style={{
              position: 'absolute',
              bottom: '80px',
              right: '12px',
            }}
            className="z-20 w-72 rounded-2xl border border-white/10 bg-[#0b0f14]/95 backdrop-blur-xl p-4 shadow-2xl"
          >
            {(() => {
              const widget = widgets.find(w => w.id === expandedWidget)
              if (!widget) return null
              
              return (
                <div className="space-y-4">
                  {/* Header */}
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-mono font-bold text-slate-200">{widget.label}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${getColorClasses(widget.color)}`}>
                          {widget.signal}
                        </span>
                      </div>
                      <div className="flex items-baseline gap-1 mt-1">
                        <span className={`text-2xl font-mono font-bold ${widget.color === 'emerald' ? 'text-emerald-400' : widget.color === 'red' ? 'text-red-400' : 'text-teal-400'}`}>
                          {widget.value}
                        </span>
                        <span className="text-sm text-slate-500">{widget.subValue}</span>
                      </div>
                    </div>
                    <button 
                      onClick={() => onWidgetClick(null)}
                      className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/10 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>

                  {/* Progress Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] font-mono text-slate-500">
                      <span>0</span>
                      <span>{widget.max}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                      <motion.div
                        className={`h-full rounded-full ${getBgColor(widget.color)}`}
                        initial={{ width: 0 }}
                        animate={{ width: `${widget.progress}%` }}
                        transition={{ duration: 0.5, ease: 'easeOut' }}
                      />
                    </div>
                  </div>

                  {/* Mini Sparkline */}
                  {widget.sparkline.length > 0 && (
                    <div className="h-12 flex items-end gap-0.5">
                      {widget.sparkline.map((val, i) => {
                        const min = Math.min(...widget.sparkline)
                        const max = Math.max(...widget.sparkline)
                        const height = ((val - min) / (max - min || 1)) * 100
                        const isLast = i === widget.sparkline.length - 1
                        return (
                          <motion.div
                            key={i}
                            initial={{ height: 0 }}
                            animate={{ height: `${Math.max(4, height)}%` }}
                            transition={{ delay: i * 0.02, duration: 0.3 }}
                            className={`flex-1 rounded-sm ${isLast ? getBgColor(widget.color) : 'bg-slate-700'}`}
                          />
                        )
                      })}
                    </div>
                  )}

                  {/* MACD Details */}
                  {expandedWidget === 'rsi' && indicators.macd && (
                    <div className="grid grid-cols-3 gap-2 pt-2 border-t border-white/5">
                      <div className="text-center">
                        <span className="text-[10px] text-slate-500 font-mono">MACD</span>
                        <p className={`text-xs font-mono font-bold ${indicators.macd.macd >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {indicators.macd.macd.toFixed(2)}
                        </p>
                      </div>
                      <div className="text-center">
                        <span className="text-[10px] text-slate-500 font-mono">Signal</span>
                        <p className="text-xs font-mono font-bold text-teal-400">
                          {indicators.macd.signal.toFixed(2)}
                        </p>
                      </div>
                      <div className="text-center">
                        <span className="text-[10px] text-slate-500 font-mono">Hist</span>
                        <p className={`text-xs font-mono font-bold ${indicators.macd.histogram >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {indicators.macd.histogram.toFixed(2)}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )
            })()}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
