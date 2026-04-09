import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useWebsocket } from './useWebsocket'
import { WS_URL } from '../utils/env'
import { apiGetWithRetry } from '../utils/api'

const isPlainObject = (value) => !!value && typeof value === 'object' && !Array.isArray(value)
export const toFiniteNumber = (value) => {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

const normalizeConfidencePct = (value, fallback = 0) => {
  const raw = toFiniteNumber(value)
  if (raw == null) return fallback
  const pct = raw <= 1 ? raw * 100 : raw
  return Math.max(0, Math.min(100, pct))
}

const MAX_CANDLES = 100
const HISTORY_LIMIT = 100
const WS_BATCH_MS = 32

const useDebouncedValue = (value, delayMs) => {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return debounced
}

const TIMEFRAME_TO_MS = {
  '1m': 60 * 1000,
  '3m': 3 * 60 * 1000,
  '5m': 5 * 60 * 1000,
  '15m': 15 * 60 * 1000,
  '30m': 30 * 60 * 1000,
  '1h': 60 * 60 * 1000,
  '1d': 24 * 60 * 60 * 1000,
}

const validateAndCleanOHLCV = (rawData, timeframe) => {
  if (!Array.isArray(rawData)) return []
  
  const tfMs = TIMEFRAME_TO_MS[timeframe] || 60000
  const validData = []
  
  let prevClose = null
  let prevTime = null
  let rangeCount = 0
  let sumRange = 0
  
  const seen = new Map()
  rawData.forEach(d => {
    const t = d.time || d.timestamp
    if (t) {
      const ms = new Date(t).getTime()
      if (!isNaN(ms)) {
        seen.set(ms, d)
      }
    }
  })
  
  const sortedRaw = Array.from(seen.entries())
    .sort((a, b) => a[0] - b[0])
    .map(e => e[1])

  for (let i = 0; i < sortedRaw.length; i++) {
    const raw = sortedRaw[i]
    if (!isPlainObject(raw)) continue

    let open = toFiniteNumber(raw.open)
    let high = toFiniteNumber(raw.high)
    let low = toFiniteNumber(raw.low)
    let close = toFiniteNumber(raw.close)
    const volume = toFiniteNumber(raw.volume) || 0
    let timeRaw = raw.time || raw.timestamp
    
    if (open == null || high == null || low == null) {
      continue
    }
    if (close == null) close = open
    if (!timeRaw) continue

    const currTime = new Date(timeRaw).getTime()

    if (prevTime !== null && currTime > prevTime + tfMs) {
       const actualGapMs = (currTime - prevTime) - tfMs
       const missingCandles = Math.round(actualGapMs / tfMs)
       
       if (missingCandles > 0 && missingCandles <= 10 && prevClose !== null) {
          let fillTime = prevTime + tfMs
          while (fillTime < currTime) {
            validData.push({
              time: new Date(fillTime).toISOString(),
              open: prevClose, high: prevClose, low: prevClose, close: prevClose, volume: 0
            })
            fillTime += tfMs
          }
       }
    }

    if (prevClose !== null) {
      const changePct = Math.abs(close - prevClose) / (prevClose || 1)
      const currentRange = Math.abs(high - low)
      const avgRange = rangeCount > 0 ? (sumRange / rangeCount) : currentRange

      if (changePct > 0.03 || (rangeCount > 5 && currentRange > avgRange * 3)) {
        open = prevClose; close = prevClose; high = prevClose; low = prevClose;
      }
    }

    sumRange += Math.abs(high - low)
    rangeCount++
    if (rangeCount > 20) {
      sumRange -= (sumRange / rangeCount)
      rangeCount = 20
    }

    if (high < Math.max(open, close)) high = Math.max(open, close)
    if (low > Math.min(open, close)) low = Math.min(open, close)

    validData.push({ time: new Date(currTime).toISOString(), open, high, low, close, volume })
    
    prevClose = close
    prevTime = currTime
  }

  return validData
}

const mergeCandles = (prevCandles, nextCandles) => {
  if (!Array.isArray(nextCandles) || nextCandles.length === 0) return prevCandles || []
  const map = new Map()
  ;(prevCandles || []).forEach((c) => map.set(c.time, c))
  nextCandles.forEach((c) => map.set(c.time, c))
  return Array.from(map.values())
    .sort((a, b) => new Date(a.time) - new Date(b.time))
    .slice(-MAX_CANDLES)
}

const timeframeKey = (symbol, tf, indicatorKey = '') => `${symbol}|${tf}|${indicatorKey}`

export function useTradingEngine() {
  const [symbol, setSymbol] = useState('RELIANCE')
  const [timeframe, setTimeframe] = useState('1m')
  const [ohlcv, setOhlcv] = useState([])
  const [snapshot, setSnapshot] = useState(null)
  const [prediction, setPrediction] = useState(null)
  const [indicators, setIndicators] = useState([])
  const [indicatorData, setIndicatorData] = useState([])
  
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState(null)
  const [isUnavailableData, setIsUnavailableData] = useState(false)
  const [marketStatus, setMarketStatus] = useState(null)
  const [activeSignal, setActiveSignal] = useState(null)
  
  const previousPredictionRef = useRef(null)
  const isPaginatingRef = useRef(false)
  const requestIdRef = useRef(0)
  const activeFetchAbortRef = useRef(null)
  const paginationAbortRef = useRef(null)
  const historyCacheRef = useRef(new Map())
  const symbolRef = useRef(symbol)
  const timeframeRef = useRef(timeframe)
  const indicatorKeyRef = useRef('')
  const wsBatchTimerRef = useRef(null)
  const pendingTickRef = useRef(null)
  const lastPriceRef = useRef(null)
  const prevSymbolRef = useRef(symbol)

  const debouncedTimeframe = useDebouncedValue(timeframe, 180)
  const indicatorKey = useMemo(
    () => [...new Set(indicators)].sort().join(','),
    [indicators]
  )
  const ws = useWebsocket(WS_URL)
  const { latestMessage, isConnected, isReconnecting, subscribe, unsubscribe, isSubscribed } = ws

  useEffect(() => {
    symbolRef.current = symbol
    timeframeRef.current = timeframe
    indicatorKeyRef.current = indicatorKey
  }, [symbol, timeframe, indicatorKey])

  const fetchBundle = useCallback(async ({ reqId, targetSymbol, targetTimeframe, targetIndicatorKey, signal }) => {
    const tf = targetTimeframe === '1d' ? '1d' : targetTimeframe
    const bundleRaw = await apiGetWithRetry(`/bundle/${encodeURIComponent(targetSymbol)}`, {
      signal,
      params: { interval: tf, limit: HISTORY_LIMIT, horizon: '15m' },
      retries: 2,
      retryDelayMs: 700,
      cacheTtlMs: 30_000,
    })

    if (signal.aborted || reqId !== requestIdRef.current) return
    if (symbolRef.current !== targetSymbol || timeframeRef.current !== targetTimeframe || indicatorKeyRef.current !== targetIndicatorKey) {
      return
    }

    const bundleData = isPlainObject(bundleRaw?.data) ? bundleRaw.data : null
    const historyRows = Array.isArray(bundleData?.history?.candles)
      ? bundleData.history.candles.filter((candle) => isPlainObject(candle))
      : []
    const cleanedHistory = validateAndCleanOHLCV(historyRows, targetTimeframe)

    const nextSnapshot = isPlainObject(bundleData?.snapshot) ? bundleData.snapshot : null
    const nextPrediction = isPlainObject(bundleData?.prediction) ? bundleData.prediction : null
    const nextStatus = isPlainObject(bundleData?.status) ? bundleData.status : null
    const nextIndicators = isPlainObject(bundleData?.indicators) ? [bundleData.indicators] : []

    historyCacheRef.current.set(timeframeKey(targetSymbol, targetTimeframe, targetIndicatorKey), cleanedHistory)

    setOhlcv(cleanedHistory)
    setSnapshot(nextSnapshot)
    setIndicatorData(nextIndicators)
    setMarketStatus(nextStatus)
    setIsUnavailableData(
      Boolean(nextSnapshot?.unavailable) ||
        String(nextSnapshot?.data_source || '').toUpperCase() === 'UNAVAILABLE'
    )
    setErrorMsg(cleanedHistory.length ? null : 'No market data available')
    setLoading(false)

    if (nextPrediction) {
      const normalizedPrediction = {
        ...nextPrediction,
        confidence: normalizeConfidencePct(
          nextPrediction?.confidence,
          toFiniteNumber(nextPrediction?.confidence_pct) ?? 0
        ),
      }
      setPrediction(normalizedPrediction)
      const predConfidence = normalizedPrediction.confidence
      if (nextPrediction?.signal && nextPrediction.signal !== 'HOLD' && predConfidence >= 70) {
        if (!previousPredictionRef.current || previousPredictionRef.current.signal !== nextPrediction.signal) {
          setActiveSignal(normalizedPrediction)
        }
      }
      previousPredictionRef.current = normalizedPrediction
    }
  }, [])

  const runLatestFetch = useCallback(async ({ targetSymbol, targetTimeframe, targetIndicatorKey }) => {
    if (activeFetchAbortRef.current) {
      activeFetchAbortRef.current.abort()
    }

    const controller = new AbortController()
    activeFetchAbortRef.current = controller
    const reqId = ++requestIdRef.current

    try {
      await fetchBundle({
        reqId,
        targetSymbol,
        targetTimeframe,
        targetIndicatorKey,
        signal: controller.signal,
      })
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (reqId !== requestIdRef.current) return
      if (symbolRef.current !== targetSymbol || timeframeRef.current !== targetTimeframe) return
      setLoading(false)
      setErrorMsg('No market data available')
    }
  }, [fetchBundle])

  useEffect(() => {
    const symbolChanged = prevSymbolRef.current !== symbol
    if (symbolChanged) {
      prevSymbolRef.current = symbol
      if (activeFetchAbortRef.current) activeFetchAbortRef.current.abort()
      if (paginationAbortRef.current) paginationAbortRef.current.abort()
      pendingTickRef.current = null
      lastPriceRef.current = null
      setOhlcv([])
      setSnapshot(null)
      setPrediction(null)
      setIndicatorData([])
      setIsUnavailableData(false)
      setErrorMsg(null)
      setLoading(true)
    }
  }, [symbol])

  useEffect(() => {
    const targetSymbol = symbol
    const targetTimeframe = debouncedTimeframe
    const targetIndicatorKey = indicatorKey

    const cached = historyCacheRef.current.get(timeframeKey(targetSymbol, targetTimeframe, targetIndicatorKey))
    if (Array.isArray(cached) && cached.length > 0) {
      setOhlcv(cached)
      setLoading(false)
      setErrorMsg(null)
    } else {
      setLoading(true)
    }

    runLatestFetch({ targetSymbol, targetTimeframe, targetIndicatorKey })

    const pollId = setInterval(() => {
      runLatestFetch({ targetSymbol, targetTimeframe, targetIndicatorKey })
    }, 15_000)

    return () => {
      clearInterval(pollId)
    }
  }, [symbol, debouncedTimeframe, indicatorKey, runLatestFetch])

  const flushPendingTick = useCallback(() => {
    wsBatchTimerRef.current = null
    const tick = pendingTickRef.current
    pendingTickRef.current = null
    if (!tick) return

    if (tick.symbol && tick.symbol !== symbolRef.current) return

    const ltp = toFiniteNumber(tick.ltp)
    if (ltp == null) return

    setSnapshot((prev) => ({
      ...(isPlainObject(prev) ? prev : {}),
      ltp,
      bid: toFiniteNumber(tick.bid) ?? ltp,
      ask: toFiniteNumber(tick.ask) ?? ltp,
      volume: toFiniteNumber(tick.volume) ?? 0,
    }))
    setIsUnavailableData(Boolean(tick.unavailable))

    setOhlcv((prev) => {
      if (!Array.isArray(prev) || prev.length === 0) {
        const now = new Date().toISOString()
        return [{ time: now, open: ltp, high: ltp, low: ltp, close: ltp, volume: 0 }]
      }

      const next = [...prev]
      const lastIdx = next.length - 1
      const last = { ...next[lastIdx] }
      const changePct = Math.abs(ltp - Number(last.close)) / (Number(last.close) || 1)
      if (changePct > 0.03) return prev

      last.close = ltp
      last.high = Math.max(Number(last.high), ltp)
      last.low = Math.min(Number(last.low), ltp)
      next[lastIdx] = last
      return next
    })
  }, [])

  const loadMoreHistory = useCallback(async () => {
    // Bundle API Deprecation Note (2026-04-01):
    // The old /market/history endpoint with pagination (to_time) is deprecated.
    // The new /bundle endpoint returns up to 100 candles per request.
    // Client-side history expansion is handled via WebSocket candle updates + local state.
    // This function is retained as a no-op for backward compatibility.
    if (isPaginatingRef.current || ohlcv.length === 0) return
    
    // Pagination is now handled by:
    // 1. Initial bundle API fetch (100 candles)
    // 2. Real-time WebSocket updates appending new candles
    // 3. Local state merging older → newer
    // No additional historical pagination needed.
    return
  }, [ohlcv])

  const prevWsSymbolRef = useRef(null)

  useEffect(() => {
    if (isConnected) {
      if (prevWsSymbolRef.current && prevWsSymbolRef.current !== symbol) {
        unsubscribe([prevWsSymbolRef.current])
        lastPriceRef.current = null
        pendingTickRef.current = null
      }
      
      if (!isSubscribed(symbol)) {
        subscribe([symbol])
      }
      prevWsSymbolRef.current = symbol
    }
    return () => {
      if (wsBatchTimerRef.current) {
        clearTimeout(wsBatchTimerRef.current)
        wsBatchTimerRef.current = null
      }
    }
  }, [isConnected, isSubscribed, subscribe, symbol, unsubscribe])

  useEffect(() => {
    if (!latestMessage || !isPlainObject(latestMessage)) return
    
    const msg = latestMessage
    
    if (msg.symbol !== symbolRef.current && msg.type !== 'status') return

    if (msg.type === 'tick') {
      pendingTickRef.current = msg
      const ltp = toFiniteNumber(msg.ltp)
      const lastPrice = lastPriceRef.current

      if (lastPrice && lastPrice > 0) {
        const changePct = Math.abs(ltp - lastPrice) / (ltp || 1)
        if (changePct > 0.30) return
      }
      if (ltp != null) {
        lastPriceRef.current = ltp
      }
      if (!wsBatchTimerRef.current) {
        wsBatchTimerRef.current = setTimeout(flushPendingTick, WS_BATCH_MS)
      }
      return
    }

    if (msg.type === 'candle_update') {
      const targetSymbol = symbolRef.current
      const targetTimeframe = timeframeRef.current
      const targetIndicatorKey = indicatorKeyRef.current
      const candleTime = typeof msg.timestamp === 'string' ? msg.timestamp : null
      const interval = typeof msg.interval === 'string' ? msg.interval : targetTimeframe
      if (!candleTime || interval !== targetTimeframe) return
      if (msg.symbol && msg.symbol !== targetSymbol) return

      const incoming = {
        time: candleTime,
        open: toFiniteNumber(msg.open),
        high: toFiniteNumber(msg.high),
        low: toFiniteNumber(msg.low),
        close: toFiniteNumber(msg.close),
        volume: toFiniteNumber(msg.volume) ?? 0,
      }
      if (incoming.open == null || incoming.high == null || incoming.low == null) return
      if (incoming.close == null) incoming.close = incoming.open

      setOhlcv(prev => {
        const merged = mergeCandles(prev, [incoming])
        const key = timeframeKey(targetSymbol, targetTimeframe, targetIndicatorKey)
        historyCacheRef.current.set(key, merged)
        return merged
      })
    }
  }, [latestMessage, flushPendingTick])

  useEffect(() => {
    return () => {
      if (activeFetchAbortRef.current) activeFetchAbortRef.current.abort()
      if (paginationAbortRef.current) paginationAbortRef.current.abort()
    }
  }, [])

  return {
    symbol, setSymbol,
    timeframe, setTimeframe,
    ohlcv, snapshot, prediction, indicators, setIndicators, indicatorData,
    loading,
    errorMsg,
    isUnavailableData,
    isMockData: isUnavailableData,
    marketStatus,
    activeSignal,
    setActiveSignal,
    wsConnected: isConnected,
    wsReconnecting: isReconnecting,
    loadMoreHistory
  }
}


