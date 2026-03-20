import React, { useEffect, useRef, useState, useCallback, memo } from 'react'
import { motion } from 'framer-motion'
import { createChart } from 'lightweight-charts'

const parseTime = (t) => {
  if (!t) return null
  const normalized = (typeof t === 'string' ? t.replace('+05:30', '').trim() : String(t))
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return null
  return Math.floor(d.getTime() / 1000)
}

const DecisionChartCanvas = memo(function DecisionChartCanvas({ ohlcv, symbol, snapshot, isMockData, timeframe, focusMode, onFocusToggle, indicators, indicatorData, prediction, onPaginateHistory }) {
  const containerRef = useRef(null)
  const chartInstance = useRef(null)
  const isUserInteracting = useRef(false)
  const initialFitDone = useRef(false)
  const prevOhlcvRef = useRef(null)
  const prevIndicatorRef = useRef(null)
  const prevSymbolRef = useRef(null)  // Track symbol to detect switches
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  // Parse OHLCV data
  const parseData = useCallback(() => {
    if (!ohlcv?.length) return { candles: [], volume: [] }

    // Deduplicate by timestamp — keep the last occurrence for each time
    // lightweight-charts requires strictly monotonically increasing timestamps
    const seen = new Map()
    ohlcv.forEach(d => {
      const t = parseTime(d.time)
      if (t != null && !isNaN(Number(d.open))) {
        seen.set(t, d)
      }
    })
    const uniqueData = Array.from(seen.values())
    uniqueData.sort((a, b) => parseTime(a.time) - parseTime(b.time))

    const candles = uniqueData.map((d) => ({
      time: parseTime(d.time),
      open: Number(d.open),
      high: Number(d.high),
      low: Number(d.low),
      close: Number(d.close),
    }))

    const volume = uniqueData.map((d) => ({
      time: parseTime(d.time),
      value: Number(d.volume) || 0,
      color: Number(d.close) >= Number(d.open) ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
    }))

    return { candles, volume }
  }, [ohlcv])

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const el = containerRef.current
    const { width, height } = el.getBoundingClientRect()

    try {
      const chart = createChart(el, {
        layout: { background: { color: 'transparent' }, textColor: '#64748b', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 },
        grid: { vertLines: { color: 'rgba(30, 41, 59, 0.5)' }, horzLines: { color: 'rgba(30, 41, 59, 0.5)' } },
        width,
        height,
        crosshair: { mode: 0, vertLine: { color: 'rgba(20, 184, 166, 0.3)', width: 1, style: 3 }, horzLine: { color: 'rgba(20, 184, 166, 0.3)', width: 1, style: 3 } },
        timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#1e293b', rightOffset: 5 },
        rightPriceScale: { autoScale: true, borderColor: '#1e293b', scaleMargins: { top: 0.05, bottom: 0.18 } },
      })

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      })

      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      })
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      })

      // Resize observer
      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries.length || !chartInstance.current?.chart) return
        const { width: w, height: h } = entries[0].contentRect
        if (w > 0 && h > 0) {
          chart.applyOptions({ width: w, height: h })
        }
      })
      resizeObserver.observe(el)

      chartInstance.current = {
        chart,
        candleSeries,
        volumeSeries,
        resizeObserver,
        overlaySeries: {},
        subPaneSeries: {},
      }

      // TOUCH & ZOOM FIX: Native event listeners to track physical touches
      let isUserTouching = false;
      const setTouchOn = () => { isUserTouching = true; }
      const setTouchOff = () => { isUserTouching = false; }
      
      el.addEventListener('touchstart', setTouchOn, { passive: true });
      el.addEventListener('touchmove', setTouchOn, { passive: true });
      el.addEventListener('touchend', setTouchOff, { passive: true });
      el.addEventListener('mousedown', setTouchOn, { passive: true });
      el.addEventListener('mousemove', (e) => { if (e.buttons > 0) setTouchOn(); }, { passive: true });
      el.addEventListener('mouseup', setTouchOff, { passive: true });

      // Track user zoom/pan interaction with Debounce
      let paginationDebounce = null;
      let prevLogicalRangeFrom = null;

      chart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        if (initialFitDone.current) {
          isUserInteracting.current = true
        }

        if (logicalRange !== null) {
          const isScrollingLeft = prevLogicalRangeFrom !== null && logicalRange.from < prevLogicalRangeFrom;
          
          if (isScrollingLeft && logicalRange.from < 10) {
            // INTERACTION STABILITY: Abort instantly if user is holding touch/drag
            if (isUserTouching) return; 

            // DEBOUNCE / LOCK FETCH (300ms)
            if (typeof onPaginateHistory === 'function') {
              if (paginationDebounce) clearTimeout(paginationDebounce);
              paginationDebounce = setTimeout(() => {
                if (!isUserTouching) onPaginateHistory();
              }, 300);
            }
          }
          prevLogicalRangeFrom = logicalRange.from;
        }
      })

      setLoading(false)
    } catch (err) {
      setError('Chart init error: ' + err.message)
      setLoading(false)
    }

    return () => {
      if (chartInstance.current) {
        chartInstance.current.resizeObserver?.disconnect?.()
        chartInstance.current.chart?.remove?.()
        chartInstance.current = null
      }
    }
  }, [])

  // Helper: ensure an overlay line series exists on the main price scale
  const getOverlaySeries = (key, color, lineWidth = 1, lineStyle = 0) => {
    const ci = chartInstance.current
    if (!ci) return null
    if (!ci.overlaySeries[key]) {
      ci.overlaySeries[key] = ci.chart.addLineSeries({
        color,
        lineWidth,
        lineStyle,
        title: '',
        priceScaleId: 'right',
        lastValueVisible: false,
        priceLineVisible: false,
      })
    }
    return ci.overlaySeries[key]
  }

  // Helper: ensure a sub-pane line series exists on a separate price scale
  const getSubPaneSeries = (key, color, lineWidth = 1, scaleId = key, scaleMargins = { top: 0.60, bottom: 0.02 }) => {
    const ci = chartInstance.current
    if (!ci) return null
    if (!ci.subPaneSeries[key]) {
      ci.subPaneSeries[key] = ci.chart.addLineSeries({
        color,
        lineWidth,
        title: '',
        priceScaleId: scaleId,
        lastValueVisible: false,
        priceLineVisible: false,
      })
      ci.subPaneSeries[key].priceScale().applyOptions({ scaleMargins })
    }
    return ci.subPaneSeries[key]
  }

  // Helper: ensure a histogram sub-pane series exists
  const getSubHistogramSeries = (key, scaleId, scaleMargins = { top: 0.60, bottom: 0.02 }) => {
    const ci = chartInstance.current
    if (!ci) return null
    if (!ci.subPaneSeries[key]) {
      ci.subPaneSeries[key] = ci.chart.addHistogramSeries({
        priceScaleId: scaleId,
        lastValueVisible: false,
        priceLineVisible: false,
      })
      ci.subPaneSeries[key].priceScale().applyOptions({ scaleMargins })
    }
    return ci.subPaneSeries[key]
  }

  // Format indicator data for lightweight-charts
  const formatInd = useCallback((data, key, candles) => {
    if (!data?.length || !candles?.length) return [];
    
    // Create a strict time dictionary mapping from base candles 
    const validTimes = new Set(candles.map(c => c.time));
    
    return data
      .map(d => ({ time: parseTime(d.time), value: Number(d[key]) }))
      .filter(d => d.time != null && !isNaN(d.value) && validTimes.has(d.time))
      .sort((a, b) => a.time - b.time); // ensure strictly monotonically increasing
  }, [])

  // Clear a series (set empty data)
  const clearSeries = (seriesMap, key) => {
    if (seriesMap[key]) {
      seriesMap[key].setData([])
    }
  }

  // Update data when ohlcv or indicators change
  useEffect(() => {
    const ci = chartInstance.current
    if (!ci) return

    const symbolChanged = prevSymbolRef.current !== null && prevSymbolRef.current !== symbol

    // CRITICAL: If symbol changed, clear chart IMMEDIATELY and wait for fresh data.
    // At this point ohlcv may still contain OLD symbol's candles (fetchData hasn't completed).
    // Rendering old data under the new symbol header = price mismatch bug.
    if (symbolChanged) {
      ci.candleSeries.setData([])
      ci.volumeSeries.setData([])
      // Clear all indicator overlays
      Object.values(ci.overlaySeries).forEach(s => { try { s.setData([]) } catch {} })
      Object.values(ci.subPaneSeries).forEach(s => { try { s.setData([]) } catch {} })
      ci.candleSeries.setMarkers([])
      prevSymbolRef.current = symbol
      prevOhlcvRef.current = null
      prevIndicatorRef.current = null
      isUserInteracting.current = false
      initialFitDone.current = false
      setLoading(true)
      setError(null)
      return  // Wait for correct data from fetchData
    }

    if (!ohlcv?.length) {
      if (ohlcv !== null && !loading) {
        setError('No data available')
      }
      return
    }

    setError(null)

    try {
      const { candles, volume } = parseData()

      if (candles.length === 0) return

      // Detect whether this is a full data refresh or just a tick update.
      const prevData = prevOhlcvRef.current
      const isFullRefresh = !prevData

      if (isFullRefresh) {
        // Full re-render: new timeframe or initial load
        setLoading(true)
        ci.candleSeries.setData(candles)
        ci.volumeSeries.setData(volume)

        // Auto-fit to show all candles with correct price scale
        if (!isUserInteracting.current) {
          ci.chart.timeScale().fitContent()
          setTimeout(() => { initialFitDone.current = true }, 100)
        }
        setLoading(false)
      } else {
        // Check if data grew strictly backwards (Historical pagination load)
        if (prevData && ohlcv.length > 0 && prevData.length > 0 && String(ohlcv[0]?.time) !== String(prevData[0]?.time)) {
            // New historical data was prepended. We must call `setData` to inject old candles,
            // but we DO NOT call `fitContent` so zoom state is perfectly preserved!
            ci.candleSeries.setData(candles)
            ci.volumeSeries.setData(volume)
        } else {
            // Incremental update: just update the last candle (smooth, no flicker)
            const lastCandle = candles[candles.length - 1]
            const lastVolume = volume[volume.length - 1]
            if (lastCandle) {
              ci.candleSeries.update(lastCandle)
              ci.volumeSeries.update(lastVolume)
            }
            // If a new live candle was appended (length grew by 1), do a full set implicitly without autofit
            if (prevData && ohlcv.length > prevData.length) {
              ci.candleSeries.setData(candles)
              ci.volumeSeries.setData(volume)
            }
        }
      }

      prevOhlcvRef.current = ohlcv
      if (!prevSymbolRef.current) prevSymbolRef.current = symbol

      // --- INDICATOR UPDATES ---
      // Only update indicators if the indicator data or selection changed
      const indKey = JSON.stringify(indicators) + ':' + (indicatorData?.length || 0)
      const prevIndKey = prevIndicatorRef.current
      const indChanged = indKey !== prevIndKey

      if (indChanged) {
        prevIndicatorRef.current = indKey
        const hasInd = indicatorData && indicatorData.length > 0

        // Dynamically adjust scale margins if at least one sub-pane indicator is active
        const SUB_PANE_INDICATORS = ['rsi9', 'macd', 'atr14', 'adx14', 'obv', 'stoch', 'scalp_pro'];
        const hasSubPane = indicators.some(ind => SUB_PANE_INDICATORS.includes(ind));

        if (hasSubPane) {
          ci.chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.42 } });
          ci.volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.48, bottom: 0.42 } });
        } else {
          ci.chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.18 } });
          ci.volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
        }

        // --- OVERLAY INDICATORS (on main price scale) ---

        // EMA 9
        if (indicators.includes('ema') && hasInd) {
          getOverlaySeries('ema9', '#38bdf8', 1)?.setData(formatInd(indicatorData, 'ema9', candles))
          getOverlaySeries('ema15', '#818cf8', 1)?.setData(formatInd(indicatorData, 'ema15', candles))
        } else {
          clearSeries(ci.overlaySeries, 'ema9')
          clearSeries(ci.overlaySeries, 'ema15')
        }

        // VWAP
        if (indicators.includes('vwap') && hasInd) {
          getOverlaySeries('vwap', '#fbbf24', 1)?.setData(formatInd(indicatorData, 'vwap', candles))
        } else {
          clearSeries(ci.overlaySeries, 'vwap')
        }

        // Bollinger Bands
        if (indicators.includes('bb') && hasInd) {
          getOverlaySeries('bb_upper', '#4ade80', 1, 2)?.setData(formatInd(indicatorData, 'bb_upper', candles))
          getOverlaySeries('bb_lower', '#f87171', 1, 2)?.setData(formatInd(indicatorData, 'bb_lower', candles))
        } else {
          clearSeries(ci.overlaySeries, 'bb_upper')
          clearSeries(ci.overlaySeries, 'bb_lower')
        }

        // SuperTrend
        if (indicators.includes('supertrend') && hasInd) {
          getOverlaySeries('supertrend', '#fb923c', 2)?.setData(formatInd(indicatorData, 'supertrend', candles))
        } else {
          clearSeries(ci.overlaySeries, 'supertrend')
        }

        // Ichimoku (Tenkan-Sen)
        if (indicators.includes('ichimoku') && hasInd) {
          getOverlaySeries('tenkan_sen', '#06b6d4', 1)?.setData(formatInd(indicatorData, 'tenkan_sen', candles))
        } else {
          clearSeries(ci.overlaySeries, 'tenkan_sen')
        }

        // SMA20 (part of Bollinger)
        if (indicators.includes('bb') && hasInd) {
          getOverlaySeries('sma20', '#94a3b8', 1, 1)?.setData(formatInd(indicatorData, 'sma20', candles))
        } else {
          clearSeries(ci.overlaySeries, 'sma20')
        }

        // --- SUB-PANE INDICATORS ---

        // RSI (0-100 range)
        if (indicators.includes('rsi9') && hasInd) {
          getSubPaneSeries('rsi9', '#a78bfa', 1, 'rsi')?.setData(formatInd(indicatorData, 'rsi9', candles))
        } else {
          clearSeries(ci.subPaneSeries, 'rsi9')
        }

        // MACD 
        if (indicators.includes('macd') && hasInd) {
          getSubPaneSeries('macd', '#34d399', 1, 'macd_scale')?.setData(formatInd(indicatorData, 'macd', candles))
          getSubPaneSeries('macd_signal', '#fbbf24', 1, 'macd_scale')?.setData(formatInd(indicatorData, 'macd_signal', candles))
          // MACD Histogram
          const validTimes = new Set(candles.map(c => c.time));
          const histData = indicatorData
            .map(d => ({
              time: parseTime(d.time),
              value: Number(d.macd_hist),
              color: Number(d.macd_hist) >= 0 ? 'rgba(16, 185, 129, 0.6)' : 'rgba(239, 68, 68, 0.6)',
            }))
            .filter(d => d.time != null && !isNaN(d.value) && validTimes.has(d.time))
            .sort((a,b) => a.time - b.time)
          getSubHistogramSeries('macd_hist', 'macd_scale')?.setData(histData)
        } else {
          clearSeries(ci.subPaneSeries, 'macd')
          clearSeries(ci.subPaneSeries, 'macd_signal')
          clearSeries(ci.subPaneSeries, 'macd_hist')
        }

        // ATR
        if (indicators.includes('atr14') && hasInd) {
          getSubPaneSeries('atr14', '#94a3b8', 1, 'atr_scale')?.setData(formatInd(indicatorData, 'atr14', candles))
        } else {
          clearSeries(ci.subPaneSeries, 'atr14')
        }

        // ADX
        if (indicators.includes('adx14') && hasInd) {
          getSubPaneSeries('adx14', '#f97316', 1, 'adx_scale')?.setData(formatInd(indicatorData, 'adx14', candles))
        } else {
          clearSeries(ci.subPaneSeries, 'adx14')
        }

        // OBV
        if (indicators.includes('obv') && hasInd) {
          getSubPaneSeries('obv', '#818cf8', 1, 'obv_scale')?.setData(formatInd(indicatorData, 'obv', candles))
        } else {
          clearSeries(ci.subPaneSeries, 'obv')
        }

        // Stochastic
        if (indicators.includes('stoch') && hasInd) {
          getSubPaneSeries('stoch_k', '#ec4899', 1, 'stoch_scale')?.setData(formatInd(indicatorData, 'stoch_k', candles))
          getSubPaneSeries('stoch_d', '#f97316', 1, 'stoch_scale')?.setData(formatInd(indicatorData, 'stoch_d', candles))
        } else {
          clearSeries(ci.subPaneSeries, 'stoch_k')
          clearSeries(ci.subPaneSeries, 'stoch_d')
        }

        // --- SCALP PRO --- (sub-pane + buy/sell markers on main chart)
        if (indicators.includes('scalp_pro') && hasInd) {
          getSubPaneSeries('scalp_macd', '#22d3ee', 2, 'scalp_scale')?.setData(formatInd(indicatorData, 'scalp_macd', candles))
          getSubPaneSeries('scalp_signal', '#fbbf24', 1, 'scalp_scale')?.setData(formatInd(indicatorData, 'scalp_signal', candles))

          const markers = []
          indicatorData.forEach(d => {
            const t = parseTime(d.time)
            if (!t) return
            if (Number(d.scalp_buy) === 1) {
              markers.push({ time: t, position: 'belowBar', color: '#10b981', shape: 'arrowUp', text: 'Buy' })
            }
            if (Number(d.scalp_sell) === 1) {
              markers.push({ time: t, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'Sell' })
            }
          })
          markers.sort((a, b) => a.time - b.time)
          ci.candleSeries.setMarkers(markers)
        } else {
          clearSeries(ci.subPaneSeries, 'scalp_macd')
          clearSeries(ci.subPaneSeries, 'scalp_signal')
          if (!prediction?.signal || !indicators.includes('scalp_pro')) {
            ci.candleSeries.setMarkers(
              prediction?.prediction && candles.length > 0
                ? [{
                  time: candles[candles.length - 1].time,
                  position: prediction.signal === 'BUY' ? 'belowBar' : 'aboveBar',
                  color: prediction.signal === 'BUY' ? '#10b981' : '#ef4444',
                  shape: prediction.signal === 'BUY' ? 'arrowUp' : 'arrowDown',
                  text: prediction.signal,
                }]
                : []
            )
          }
        }
      }

      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [ohlcv, symbol, parseData, indicatorData, indicators, prediction])

  // Reset ALL chart tracking state when symbol changes
  useEffect(() => {
    isUserInteracting.current = false
    initialFitDone.current = false
    prevOhlcvRef.current = null      // Force full setData on next render
    prevIndicatorRef.current = null   // Force indicator redraw
  }, [symbol])

  // Real-time price update — apply live snapshots
  useEffect(() => {
    if (!snapshot?.ltp || !chartInstance.current?.candleSeries || loading) return

    const { candles } = parseData()
    const lastCandle = candles[candles.length - 1]
    if (!lastCandle) return

    // Sanity check: only update if LTP is within 20% of last candle's close
    // This prevents stale mock/mismatched prices from distorting the chart scale
    const ltp = Number(snapshot.ltp)
    const lastClose = lastCandle.close
    if (Math.abs(ltp - lastClose) / lastClose > 0.2) return

    chartInstance.current.candleSeries.update({
      ...lastCandle,
      close: ltp,
      high: Math.max(lastCandle.high, ltp),
      low: Math.min(lastCandle.low, ltp),
    })
  }, [snapshot?.ltp, loading, parseData])

  return (
    <div className="relative w-full h-full flex flex-col overflow-hidden">
      {/* Symbol + LTP Header — minimal, inside chart area */}
      <div className="shrink-0 flex items-center justify-between px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono font-bold text-slate-300">{symbol}</span>
          {(() => {
            const displayLtp = snapshot?.ltp || (ohlcv?.length > 0 ? ohlcv[ohlcv.length - 1].close : null)
            return displayLtp ? (
              <motion.span
                key={displayLtp}
                initial={{ scale: 1.04 }}
                animate={{ scale: 1 }}
                className="text-sm font-mono font-bold text-teal-400"
              >
                ₹{Number(displayLtp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </motion.span>
            ) : null
          })()}
          {/* Active indicator labels */}
          {indicators.length > 0 && (
            <div className="flex items-center gap-1 ml-2">
              {indicators.slice(0, 4).map(id => (
                <span key={id} className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-white/5 text-slate-500 border border-white/5">
                  {id.toUpperCase().replace('_', ' ')}
                </span>
              ))}
              {indicators.length > 4 && (
                <span className="text-[9px] text-slate-600 font-mono">+{indicators.length - 4}</span>
              )}
            </div>
          )}
        </div>
        <motion.button
          onClick={onFocusToggle}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          className="p-1.5 rounded-lg bg-white/5 border border-white/5 text-slate-500 hover:text-teal-400"
          title="Focus mode"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>
        </motion.button>
      </div>

      {/* Chart fills remaining space */}
      <div className="flex-1 w-full relative min-h-[300px]">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0b0f14]/80 z-10">
            <div className="w-6 h-6 border-2 border-teal-500/30 border-t-teal-500 rounded-full animate-spin" />
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <span className="text-red-400/70 font-mono text-xs">{error}</span>
          </div>
        )}
        <div ref={containerRef} className="absolute inset-0" />
      </div>
    </div>
  )
})

export default DecisionChartCanvas
