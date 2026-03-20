import { useEffect, useRef, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { createChart, CrosshairMode } from 'lightweight-charts'

const parseTime = (t) => {
  if (!t) return null
  const normalized = (typeof t === 'string' ? t.replace('+05:30', '').trim() : String(t))
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return null
  return Math.floor(d.getTime() / 1000)
}

export default function TradingChart({ 
  ohlcv, 
  symbol, 
  snapshot, 
  isMockData, 
  timeframe, 
  focusMode, 
  onFocusToggle,
  indicators = [],
  onCrosshairChange
}) {
  const containerRef = useRef(null)
  const chartInstance = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tooltip, setTooltip] = useState(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })

  // Parse OHLCV data
  const data = useCallback(() => {
    if (!ohlcv?.length) return { candles: [], volume: [] }
    
    const candles = ohlcv
      .map((d) => ({
        time: parseTime(d.time),
        open: Number(d.open),
        high: Number(d.high),
        low: Number(d.low),
        close: Number(d.close),
      }))
      .filter((d) => d.time != null && !isNaN(d.open))
    
    const volume = ohlcv
      .map((d) => ({
        time: parseTime(d.time),
        value: Number(d.volume) || 0,
        color: Number(d.close) >= Number(d.open) ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
      }))
      .filter((d) => d.time != null)
    
    return { candles, volume }
  }, [ohlcv])

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const { width, height } = containerRef.current.getBoundingClientRect()
    setDimensions({ width, height })

    const chart = createChart(containerRef.current, {
      layout: { 
        background: { color: 'transparent' }, 
        textColor: '#64748b',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: { 
        vertLines: { color: 'rgba(30, 41, 59, 0.5)' }, 
        horzLines: { color: 'rgba(30, 41, 59, 0.5)' } 
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(20, 184, 166, 0.6)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#0b0f14',
        },
        horzLine: {
          color: 'rgba(20, 184, 166, 0.6)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#0b0f14',
        },
      },
      timeScale: { 
        timeVisible: true, 
        secondsVisible: false, 
        borderColor: 'rgba(51, 65, 85, 0.5)',
        tickMarkFormatter: (time) => {
          const date = new Date(time * 1000)
          return timeframe === '1d' 
            ? date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
            : date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
        },
      },
      rightPriceScale: { 
        borderColor: 'rgba(51, 65, 85, 0.5)', 
        scaleMargins: { top: 0.1, bottom: 0.2 } 
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      handleScroll: {
        vertTouchDrag: true,
        horzTouchDrag: true,
      },
      width,
      height: Math.max(height, 400),
    })

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    })
    candleSeriesRef.current = candleSeries

    // Volume histogram
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    })
    volumeSeriesRef.current = volumeSeries

    // Crosshair handler
    chart.subscribeCrosshairMove((param) => {
      const ohlc = param.seriesData.get(candleSeries)?.[0]
      const vol = param.seriesData.get(volumeSeries)
      if (ohlc) {
        const tooltipData = {
          ...ohlc,
          volume: vol?.value || 0,
          time: param.time,
        }
        setTooltip(tooltipData)
        onCrosshairChange?.(tooltipData)
      } else {
        setTooltip(null)
      }
    })

    // Resize observer
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries.length) return
      const { width: w, height: h } = entries[0].contentRect
      chart.applyOptions({ width: w, height: Math.max(h, 400) })
      setDimensions({ width: w, height: h })
    })
    resizeObserver.observe(containerRef.current)

    chartInstance.current = { chart, resizeObserver }

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [])

  // Update data
  useEffect(() => {
    if (!chartInstance.current || !ohlcv?.length) return

    setLoading(true)
    try {
      const { candles, volume } = data()
      
      if (candles.length > 0) {
        candleSeriesRef.current?.setData(candles)
        volumeSeriesRef.current?.setData(volume)
        chartInstance.current?.chart.timeScale().fitContent()
        setError(null)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [ohlcv, data])

  // Real-time price update animation
  useEffect(() => {
    if (!snapshot?.ltp || !candleSeriesRef.current || loading) return

    const lastCandle = data().candles[data().candles.length - 1]
    if (!lastCandle) return

    // Update last candle with new price
    candleSeriesRef.current.update({
      ...lastCandle,
      close: Number(snapshot.ltp),
      high: Math.max(lastCandle.high, Number(snapshot.ltp)),
      low: Math.min(lastCandle.low, Number(snapshot.ltp)),
    })
  }, [snapshot?.ltp, loading, data])

  return (
    <motion.div
      layout
      className={`relative flex flex-col rounded-2xl border border-white/5 bg-black/30 backdrop-blur-xl overflow-hidden transition-all
        ${focusMode ? 'fixed inset-4 z-50 shadow-2xl' : 'flex-1 min-h-[420px]'}`}
    >
      {/* Header with symbol and price */}
      <div className="absolute top-4 left-4 right-4 z-20 flex items-center justify-between pointer-events-none">
        <div className="flex items-center gap-4 pointer-events-auto">
          <div className="flex flex-col">
            <span className="text-lg font-mono font-bold text-slate-200">{symbol}</span>
            <span className="text-xs text-slate-500 font-mono">{timeframe.toUpperCase()} • Live</span>
          </div>
          {snapshot && (
            <motion.div 
              key={snapshot.ltp}
              initial={{ scale: 1.05 }}
              animate={{ scale: 1 }}
              className="flex flex-col"
            >
              <span className="text-2xl font-mono font-bold text-teal-400">
                ₹ {Number(snapshot.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
              {snapshot.change !== undefined && (
                <span className={`text-xs font-mono font-bold ${Number(snapshot.change) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {Number(snapshot.change) >= 0 ? '+' : ''}{Number(snapshot.change).toFixed(2)}%
                </span>
              )}
            </motion.div>
          )}
        </div>

        {/* OHLC Tooltip */}
        <AnimatePresence mode="wait">
          {tooltip && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex gap-4 text-xs font-mono bg-[#0b0f14]/90 backdrop-blur-md rounded-xl px-4 py-2.5 border border-white/10 shadow-xl"
            >
              <div className="flex flex-col">
                <span className="text-slate-500">O</span>
                <span className="text-slate-200">{tooltip.open?.toFixed(2)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-slate-500">H</span>
                <span className="text-emerald-400">{tooltip.high?.toFixed(2)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-slate-500">L</span>
                <span className="text-red-400">{tooltip.low?.toFixed(2)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-slate-500">C</span>
                <span className={tooltip.close >= tooltip.open ? 'text-emerald-400' : 'text-red-400'}>
                  {tooltip.close?.toFixed(2)}
                </span>
              </div>
              <div className="flex flex-col border-l border-white/10 pl-4">
                <span className="text-slate-500">Vol</span>
                <span className="text-teal-400">{(tooltip.volume / 100000).toFixed(2)}L</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Focus toggle */}
        <div className="pointer-events-auto">
          <motion.button
            onClick={onFocusToggle}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="p-2 rounded-xl bg-white/5 border border-white/10 text-slate-400 hover:text-teal-400 hover:border-teal-500/30 transition-all"
            title="Focus mode"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </motion.button>
        </div>
      </div>

      {/* Chart container */}
      <div className="flex-1 relative min-h-[400px] pt-16">
        {/* Loading overlay */}
        <AnimatePresence>
          {loading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex items-center justify-center bg-[#0b0f14]/80 z-10"
            >
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-teal-500/30 border-t-teal-500 rounded-full animate-spin" />
                <span className="text-teal-400 font-mono text-sm">Loading chart...</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error state */}
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <svg className="w-12 h-12 text-red-500/50 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <span className="text-red-400 font-mono text-sm">{error}</span>
            </div>
          </div>
        )}

        {/* Chart */}
        <div ref={containerRef} className="w-full h-full min-h-[400px]" />

        {/* Prediction marker */}
        {!error && !loading && data().candles.length > 0 && (
          <div className="absolute top-20 right-8 flex items-center gap-2 pointer-events-none">
            <div className="px-3 py-1.5 rounded-lg bg-teal-500/10 border border-teal-500/30">
              <span className="text-xs font-mono text-teal-400">Prediction Zone</span>
            </div>
            <motion.div
              animate={{ opacity: [0.3, 0.8, 0.3] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="w-16 h-0.5 rounded-full bg-gradient-to-r from-transparent via-teal-500 to-transparent"
            />
          </div>
        )}
      </div>
    </motion.div>
  )
}
