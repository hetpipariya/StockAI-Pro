import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'

const parseTime = (t) => {
  if (!t) return null
  const normalized = (typeof t === 'string' ? t.replace('+05:30', '').trim() : String(t))
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return null
  return Math.floor(d.getTime() / 1000)
}

export default function Chart({ ohlcv, symbol, indicators, snapshot, isMockData }) {
  const chartRef = useRef(null)
  const chartInstance = useRef(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!ohlcv?.length) {
      setError('No data available')
      return
    }

    setError(null)
    setLoading(true)

    const data = ohlcv
      .map((d) => ({
        time: parseTime(d.time),
        open: Number(d.open),
        high: Number(d.high),
        low: Number(d.low),
        close: Number(d.close),
      }))
      .filter((d) => d.time != null && !isNaN(d.open) && !isNaN(d.high) && !isNaN(d.low) && !isNaN(d.close))

    if (data.length === 0) {
      setError('No valid data to display')
      setLoading(false)
      return
    }

    const el = chartRef.current
    if (!el) {
      setLoading(false)
      return
    }

    if (chartInstance.current) {
      chartInstance.current.chart.remove()
      chartInstance.current = null
    }

    try {
      const chart = createChart(el, {
        layout: {
          background: { color: '#0b0f14' },
          textColor: '#94a3b8',
        },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        width: el.clientWidth,
        height: el.clientHeight || 420,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderColor: '#334155',
        },
        rightPriceScale: {
          borderColor: '#334155',
          scaleMargins: { top: 0.1, bottom: 0.2 },
        },
      })

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      })

      candleSeries.setData(data)
      chart.timeScale().fitContent()

      const handleResize = () => {
        if (chartInstance.current?.chart && el) {
          chartInstance.current.chart.applyOptions({ width: el.clientWidth })
        }
      }
      const ro = new ResizeObserver(handleResize)
      ro.observe(el)

      chartInstance.current = { chart, candleSeries, ro }
      setLoading(false)
    } catch (err) {
      setError('Error creating chart: ' + err.message)
      setLoading(false)
    }

    return () => {
      if (chartInstance.current) {
        chartInstance.current.ro?.disconnect?.()
        chartInstance.current.chart.remove()
        chartInstance.current = null
      }
    }
  }, [ohlcv, symbol])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-2">
        <h2 className="text-lg font-mono font-semibold text-slate-200">{symbol}</h2>
        {snapshot && (
          <span className="text-2xl font-mono font-bold text-teal-400">
            ₹ {Number(snapshot.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        )}
      </div>
      <div className="flex-1 min-h-[420px] relative px-4 pb-2">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 rounded-xl z-10">
            <span className="text-teal-400 font-mono">Loading chart...</span>
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-800/50">
            <span className="text-red-400">{error}</span>
          </div>
        )}
        <div ref={chartRef} className="w-full h-full min-h-[400px] rounded-xl overflow-hidden" />
      </div>
    </div>
  )
}
