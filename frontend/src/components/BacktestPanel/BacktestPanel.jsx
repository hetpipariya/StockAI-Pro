import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'
import {
  createChart,
  CrosshairMode,
  ColorType,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1` : '/api/v1'

export default function BacktestPanel({ symbol, onSelect }) {
  const { token } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  
  // Config
  const [config, setConfig] = useState({
    symbol: symbol,
    start_date: '2023-01-01',
    end_date: '2023-12-31',
    capital: 100000
  })

  // Results
  const [results, setResults] = useState(null)
  
  // Chart Reference
  const chartContainerRef = useRef(null)
  const chartInstance = useRef(null)
  const seriesRef = useRef(null)

  // Quick sync symbol prop to config when parent changes it
  useEffect(() => {
    setConfig(c => ({...c, symbol}))
  }, [symbol])

  const runBacktest = async (e) => {
    e.preventDefault()
    if (!config.symbol || !config.start_date || !config.end_date) return
    
    setLoading(true)
    setError(null)
    setResults(null)
    
    try {
      const res = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(config)
      })

      if (!res.ok) {
        let errStr = 'Simulation failed'
        try { const j = await res.json(); errStr = j.detail || errStr } catch {}
        throw new Error(errStr)
      }

      const data = await res.json()
      setResults(data)
      onSelect(config.symbol) // globally switch to this symbol if not already

    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Draw Equity Curve when results arrive
  useEffect(() => {
    if (!results || !results.equity_curve || !chartContainerRef.current) return

    if (!chartInstance.current) {
      chartInstance.current = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#cbd5e1',
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
        },
        crosshair: { mode: CrosshairMode.Normal },
        timeScale: {
          borderColor: 'rgba(255, 255, 255, 0.1)',
          timeVisible: true,
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.1)',
        },
        autoSize: true,
      })

      seriesRef.current = chartInstance.current.addAreaSeries({
        lineColor: '#10b981', // emerald-500
        topColor: 'rgba(16, 185, 129, 0.4)',
        bottomColor: 'rgba(16, 185, 129, 0.0)',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
      })
    }

    const formattedData = results.equity_curve.map(pt => {
      // lightweight-charts needs time as string 'YYYY-MM-DD' or unix timestamp
      // Assuming pt.time is 'YYYY-MM-DD HH:MM:SS' or similar. 
      // If it's pure date, we can just pass it as string.
      const d = new Date(pt.time)
      const timestamp = Math.floor(d.getTime() / 1000)
      return { time: timestamp, value: pt.value }
    }).sort((a,b) => a.time - b.time)

    // Deduplicate exact timestamps if any
    const deduped = []
    let lastTime = 0
    formattedData.forEach(p => {
      if (p.time > lastTime) {
        deduped.push(p)
        lastTime = p.time
      }
    })

    try {
      seriesRef.current.setData(deduped)
      chartInstance.current.timeScale().fitContent()
    } catch(e) {
      console.warn("Chart error:", e)
    }

    return () => {}
  }, [results])


  return (
    <div className="flex flex-col h-full bg-[#0b0f14] overflow-hidden">
      {/* ─── Control Header ─── */}
      <div className="shrink-0 p-4 border-b border-white/5 bg-black/20">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-bold text-slate-200">Strategy Backtester</h2>
          <span className="text-[10px] uppercase font-mono text-purple-400 bg-purple-400/10 px-2 py-0.5 rounded">XGBoost ML</span>
        </div>

        <form onSubmit={runBacktest} className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <label className="block text-[10px] text-slate-500 uppercase font-mono mb-1">Symbol</label>
            <input 
              type="text" 
              value={config.symbol} 
              onChange={e => setConfig({...config, symbol: e.target.value.toUpperCase()})}
              className="w-full bg-black/40 border border-white/10 rounded px-2 py-1.5 text-xs text-slate-200 focus:border-purple-500 outline-none"
              placeholder="RELIANCE"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 uppercase font-mono mb-1">Capital (₹)</label>
            <input 
              type="number" 
              value={config.capital} 
              onChange={e => setConfig({...config, capital: Number(e.target.value)})}
              className="w-full bg-black/40 border border-white/10 rounded px-2 py-1.5 text-xs text-slate-200 focus:border-purple-500 outline-none"
              min="1000"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 uppercase font-mono mb-1">Start Date</label>
            <input 
              type="date" 
              value={config.start_date} 
              onChange={e => setConfig({...config, start_date: e.target.value})}
              className="w-full bg-black/40 border border-white/10 rounded px-2 py-1.5 text-[11px] text-slate-200 focus:border-purple-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 uppercase font-mono mb-1">End Date</label>
            <input 
              type="date" 
              value={config.end_date} 
              onChange={e => setConfig({...config, end_date: e.target.value})}
              className="w-full bg-black/40 border border-white/10 rounded px-2 py-1.5 text-[11px] text-slate-200 focus:border-purple-500 outline-none"
            />
          </div>
          
          <div className="col-span-2 lg:col-span-4 mt-2">
            <button 
              type="submit" 
              disabled={loading}
              className="w-full bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/50 text-purple-400 font-mono text-xs py-2 rounded transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Running Simulation...
                </>
              ) : 'Run Simulation'}
            </button>
            {error && <div className="mt-2 text-[10px] text-red-400 text-center">{error}</div>}
          </div>
        </form>
      </div>

      {/* ─── Results Area ─── */}
      <div className="flex-1 overflow-y-auto custom-scrollbar relative">
        {!results && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 p-6 text-center">
            <svg className="w-12 h-12 mb-3 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
            <p className="text-sm">Configure parameters and run simulation to view historical performance against ML models.</p>
          </div>
        )}

        {results && (
          <div className="p-4 space-y-6">
            
            {/* KPI Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-lg p-3">
                <div className="text-[10px] text-slate-400 uppercase font-mono">Net Return</div>
                <div className={`text-lg font-mono mt-1 ${results.roi_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {results.roi_pct >= 0 ? '+' : ''}{results.roi_pct.toFixed(2)}%
                </div>
              </div>
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-lg p-3">
                <div className="text-[10px] text-slate-400 uppercase font-mono">Final Capital</div>
                <div className="text-lg font-mono text-slate-200 mt-1">₹{results.final_capital.toLocaleString('en-IN')}</div>
              </div>
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-lg p-3">
                <div className="text-[10px] text-slate-400 uppercase font-mono">Win Rate</div>
                <div className="text-lg font-mono text-blue-400 mt-1">{results.win_rate}%</div>
              </div>
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-lg p-3">
                <div className="text-[10px] text-slate-400 uppercase font-mono">Max Drawdown</div>
                <div className="text-lg font-mono text-red-400 mt-1">-{results.max_drawdown_pct}%</div>
              </div>
            </div>

            {/* Equity Curve Chart */}
            <div className="space-y-2">
              <h3 className="text-xs font-bold text-slate-300">Equity Curve</h3>
              <div className="h-64 w-full bg-black/20 rounded-lg border border-white/5 overflow-hidden" ref={chartContainerRef} />
            </div>

            {/* Trade Log */}
            <div className="space-y-2 pb-8">
              <h3 className="text-xs font-bold text-slate-300">Trade Log ({results.total_trades} trades)</h3>
              <div className="bg-black/20 border border-white/5 rounded-lg overflow-hidden">
                <div className="grid grid-cols-5 text-[10px] font-mono text-slate-500 uppercase bg-white/[0.02] p-2 border-b border-white/5">
                  <div>Type</div>
                  <div>Entry/Exit</div>
                  <div className="text-right">Price</div>
                  <div className="text-right">PnL %</div>
                  <div className="text-right">PnL ₹</div>
                </div>
                <div className="divide-y divide-white/5 max-h-64 overflow-y-auto custom-scrollbar">
                  {results.trades.map((t, i) => (
                    <div key={i} className="grid grid-cols-5 text-xs p-2 items-center hover:bg-white/[0.02] transition-colors">
                      <div className={`font-mono font-bold ${t.direction === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {t.direction}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        <div>{new Date(t.entry_time).toLocaleDateString()}</div>
                        <div>{new Date(t.exit_time).toLocaleDateString()}</div>
                      </div>
                      <div className="text-right font-mono">
                        <div className="text-slate-300">{t.entry_price}</div>
                        <div className="text-slate-500">{t.exit_price}</div>
                      </div>
                      <div className={`text-right font-mono ${t.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct}%
                      </div>
                      <div className={`text-right font-mono ${t.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {t.pnl >= 0 ? '+' : ''}₹{t.pnl}
                      </div>
                    </div>
                  ))}
                  {results.trades.length === 0 && (
                    <div className="text-center p-4 text-xs text-slate-500 font-mono">No trades executed in this period.</div>
                  )}
                </div>
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  )
}
