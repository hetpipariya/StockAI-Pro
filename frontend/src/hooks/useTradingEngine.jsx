import { useState, useEffect, useRef } from 'react'
import { useWebsocket } from './useWebsocket'
import { INDICATOR_CATALOG } from '../components/ChartToolbar/ChartToolbar'

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1` : '/api/v1'

const isPlainObject = (value) => !!value && typeof value === 'object' && !Array.isArray(value)
export const toFiniteNumber = (value) => {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}
const parseJsonSafe = async (response, fallback = null) => {
  if (!response?.ok) {
    console.warn(`[API HTTP Error] ${response?.status} ${response?.statusText}`)
    return fallback
  }
  try {
    return await response.json()
  } catch {
    
    return fallback
  }
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
  let gapsDetected = 0
  let missingCandlesCount = 0
  let duplicatesCleaned = 0
  let spikeSuppressed = 0
  
  // Track continuous range strictly to prevent crazy wicks
  let sumRange = 0
  let rangeCount = 0

  // 1. Enforce strict alignment and deduplicate unconditionally
  const seen = new Map()
  rawData.forEach(d => {
    const t = d.time || d.timestamp
    if (t) {
      const ms = new Date(t).getTime()
      if (!isNaN(ms)) {
        if (seen.has(ms)) duplicatesCleaned++
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
      console.warn(`[Chart Data] Rejected malformed candle at ${timeRaw}: missing OHLC numbers.`)
      continue
    }
    if (close == null) close = open
    if (!timeRaw) continue

    const currTime = new Date(timeRaw).getTime()

    // 2. STRICT INTERVAL ENFORCEMENT: Check continuous timestamp alignment
    if (prevTime !== null && currTime > prevTime + tfMs) {
       const gapMs = currTime - prevTime
       const expectedInterval = tfMs
       const actualGapMs = gapMs - expectedInterval
       const missingCandles = Math.round(actualGapMs / tfMs)
       
       // Only natively fill micro-gaps up to 10 contiguous missing candles (market still open)
       if (missingCandles > 0 && missingCandles <= 10 && prevClose !== null) {
          gapsDetected++
          missingCandlesCount += missingCandles
          console.debug(`[Chart Validation] Gap detected: ${missingCandles} missing candles, Time: ${new Date(prevTime).toISOString()} → ${new Date(currTime).toISOString()}`, {gap: gapMs, expected: expectedInterval})
          
          let fillTime = prevTime + tfMs
          while (fillTime < currTime) {
            validData.push({
              time: new Date(fillTime).toISOString(),
              open: prevClose, high: prevClose, low: prevClose, close: prevClose, volume: 0
            })
            fillTime += tfMs
          }
       } else if (missingCandles > 10) {
          // Large gap: likely market closure or data error
          console.warn(`[Chart Validation] Large gap (${missingCandles} candles) detected at ${new Date(currTime).toISOString()} - possible market closure or data error`)
       }
    }

    // 3. Spike detection (> 3% change OR extreme wick/range)
    if (prevClose !== null) {
      const changePct = Math.abs(close - prevClose) / (prevClose || 1)
      const currentRange = Math.abs(high - low)
      const avgRange = rangeCount > 0 ? (sumRange / rangeCount) : currentRange

      if (changePct > 0.03 || (rangeCount > 5 && currentRange > avgRange * 3)) {
        spikeSuppressed++
        console.warn(`[Chart Data] Suppressed abnormal spike at ${timeRaw}. Change: ${(changePct*100).toFixed(2)}%, Range: ${currentRange} (Avg: ${avgRange.toFixed(2)})`)
        open = prevClose; close = prevClose; high = prevClose; low = prevClose;
      }
    }

    sumRange += Math.abs(high - low)
    rangeCount++
    if (rangeCount > 20) {
      sumRange -= (sumRange / rangeCount)
      rangeCount = 20
    }

    // 4. Structural mathematical validation
    if (high < Math.max(open, close)) high = Math.max(open, close)
    if (low > Math.min(open, close)) low = Math.min(open, close)

    validData.push({ time: new Date(currTime).toISOString(), open, high, low, close, volume })
    
    prevClose = close
    prevTime = currTime
  }

  // 5. FINAL DEBUG SUMMARY
  if (duplicatesCleaned > 0 || gapsDetected > 0 || spikeSuppressed > 0) {
    console.info(`[Chart Validation Summary] Timeframe: ${timeframe}, Duplicates: ${duplicatesCleaned}, Gaps: ${gapsDetected} (${missingCandlesCount} candles), Spikes: ${spikeSuppressed}, Final Count: ${validData.length}/${rawData.length}`)
  }

  return validData
}

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
  const [isMockData, setIsMockData] = useState(false)
  const [marketStatus, setMarketStatus] = useState(null)
  const [activeSignal, setActiveSignal] = useState(null)
  
  const previousPredictionRef = useRef(null)
  const lastProcessedMsgIdx = useRef(0)
  const activeFetchTokenRef = useRef(0)
  const isPaginatingRef = useRef(false)

// Dynamically connect WS safely matching environment
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.port === '5173'
    
    // We must read the target domain from environment variables first to allow cross-domain frontend->backend bridging (like Cloudflare Pages -> Railway)
    let wsUrl = ''
    if (import.meta.env.VITE_WS_URL) {
      wsUrl = import.meta.env.VITE_WS_URL
    } else {
      const wsProtocol = isLocal ? 'ws:' : 'wss:'
      // Fallback only if no env variable exists, though this is heavily flawed for cross-domain production.
      const wsHost = isLocal ? '127.0.0.1:8000' : window.location.host
      wsUrl = `${wsProtocol}//${wsHost}/live`
    }

  const ws = useWebsocket(wsUrl)

  const fetchData = async (fetchToken) => {
    try {
      const tf = timeframe === '1d' ? '1d' : timeframe
      const backendKeys = indicators.flatMap(id => {
        const cat = INDICATOR_CATALOG.find(c => c.id === id)
        return cat ? cat.keys : [id]
      })
      const indKeysStr = backendKeys.length > 0 ? backendKeys.join(',') : ''

      const fetches = [
        fetch(`${API_BASE}/market/history?symbol=${symbol}&interval=${tf}&limit=500`).catch(e => { console.error('History fetch error', e); return null; }),
        fetch(`${API_BASE}/market/snapshot?symbol=${symbol}`).catch(e => { console.error('Snapshot fetch error', e); return null; }),
        fetch(`${API_BASE}/predict?symbol=${symbol}&horizon=15m`).catch(e => { console.error('Predict fetch error', e); return null; }),
        fetch(`${API_BASE}/market/status`).catch(e => { console.error('Status fetch error', e); return null; }),
      ]
      if (indKeysStr) {
        fetches.push(fetch(`${API_BASE}/indicators?symbol=${symbol}&interval=${tf}&indicators=${indKeysStr}`).catch(e => { console.error('Indicators fetch error', e); return null; }))
      }
      
      const [histRes, snapRes, predRes, statRes, indRes] = await Promise.all(fetches)
      const [hist, snap, pred, stat, ind] = await Promise.all([
        parseJsonSafe(histRes, {}),
        parseJsonSafe(snapRes, {}),
        parseJsonSafe(predRes, {}),
        parseJsonSafe(statRes, {}),
        indRes ? parseJsonSafe(indRes, {}) : Promise.resolve({}),
      ])

      if (fetchToken !== activeFetchTokenRef.current) return

      if (hist?.error) {
         setErrorMsg("No market data available")
      } else {
         setErrorMsg(null)
      }

      const rawHistData = Array.isArray(hist?.data) ? hist.data.filter((candle) => isPlainObject(candle)) : []
      const histData = validateAndCleanOHLCV(rawHistData, timeframe)
      
      // API DATA COMPLETENESS CHECK
      if (rawHistData.length > 0 && histData.length < 50) {
        console.warn(`[API Data] Warning: Historical data too sparse. Raw: ${rawHistData.length} → Clean: ${histData.length}. May cause chart gaps.`)
      }
      if (histData.length === 0 && rawHistData.length === 0) {
        console.error(`[API Data] No candle data returned from API for ${symbol} ${timeframe}`)
      } else {
        console.info(`[API Data] Fetch successful: ${rawHistData.length}/${histData.length} candles for ${symbol}/${timeframe}`)
      }
      
      if (histData.length > 0) {
        setOhlcv(prev => {
          if (prev.length === 0 || fetchToken === 1) return histData;
          // Safe temporal merge keeping deep history
          const map = new Map();
          prev.forEach(c => map.set(c.time, c));
          histData.forEach(c => map.set(c.time, c));
          return Array.from(map.values()).sort((a, b) => new Date(a.time) - new Date(b.time));
        })
        setIsMockData(false)
      } else if (!hist?.error && fetchToken === 1) {
        setOhlcv([])
      }
      
      setSnapshot(!snap?.error && isPlainObject(snap) ? snap : null)
      setPrediction(prev => {
        const newPred = pred;
        console.log('[PREDICTION UPDATE]', symbol, newPred);  // Debug log
        if (newPred?.error) {
          console.warn('[PREDICTION ERROR]', newPred.error);
          return prev;
        }
        if (!isPlainObject(newPred)) return prev;
        if (!prev) return newPred;
        return { ...newPred, signal: prev.signal || newPred.signal };
      })
      setIndicatorData(Array.isArray(ind?.data) ? ind.data.filter((row) => isPlainObject(row)) : [])

      const predConfidence = toFiniteNumber(pred?.confidence) ?? 0
      if (!pred?.error && pred?.signal && pred.signal !== 'HOLD' && predConfidence >= 70) {
        if (!previousPredictionRef.current || previousPredictionRef.current.signal !== pred.signal) {
          setActiveSignal(pred)
        }
      }
      previousPredictionRef.current = pred?.error ? null : pred

      setMarketStatus(isPlainObject(stat) ? stat : null)
      setLoading(false)
    } catch (e) {
      if (fetchToken !== activeFetchTokenRef.current) return
      setLoading(false)
      setErrorMsg("No market data available")
    }
  }

  const loadMoreHistory = async () => {
    if (isPaginatingRef.current || ohlcv.length === 0) return
    isPaginatingRef.current = true
    
    try {
      const oldestCandle = ohlcv[0]
      const tf = timeframe === '1d' ? '1d' : timeframe
      // Format to explicit ISO format cleanly without ms
      const d = new Date(oldestCandle.time)
      const toTime = d.toISOString()
      
      console.info(`[Pagination] Loading history before ${toTime}`)
      const res = await fetch(`${API_BASE}/market/history?symbol=${symbol}&interval=${tf}&limit=500&to_time=${toTime}`)
      const hist = await parseJsonSafe(res, {})
      
      const rawNewCandles = Array.isArray(hist?.data) ? hist.data.filter((candle) => isPlainObject(candle)) : []
      const newCandles = validateAndCleanOHLCV(rawNewCandles, timeframe)
      
      if (newCandles.length > 0) {
        console.info(`[Pagination] Retrieved ${newCandles.length} candles, merging...`)
        setOhlcv(prev => {
           const map = new Map()
           newCandles.forEach(c => map.set(c.time, c))
           prev.forEach(c => map.set(c.time, c))
           const merged = Array.from(map.values()).sort((a, b) => new Date(a.time) - new Date(b.time))
           console.info(`[Pagination] Merge complete: ${merged.length} total candles (prev: ${prev.length}, new: ${newCandles.length})`)
           return merged
        })
      } else {
        console.warn(`[Pagination] No new candles found before ${toTime}`)
      }
    } catch (e) {
      console.error('Pagination fail', e)
    } finally {
      // Cooldown slightly
      setTimeout(() => { isPaginatingRef.current = false }, 500)
    }
  }

  // Refetch on timeframe change or symbol change
  useEffect(() => {
    activeFetchTokenRef.current += 1
    const initialFetchToken = activeFetchTokenRef.current

    console.info(`[Symbol/TF Change] Switching to ${symbol}/${timeframe}. Clearing previous data.`)
    setOhlcv([])
    setSnapshot(null)
    setPrediction(null)
    setIndicatorData([])
    setIsMockData(false)
    setLoading(true)
    setErrorMsg(null)
    lastProcessedMsgIdx.current = 0

    fetchData(initialFetchToken)
    const id = setInterval(() => {
      activeFetchTokenRef.current += 1
      fetchData(activeFetchTokenRef.current)
    }, 15000)
    return () => {
      clearInterval(id)
      activeFetchTokenRef.current += 1
    }
  // Use indicators.join() instead of indicators array to avoid reference equality triggering unnecessary refetch
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe, indicators.join(',')])

  const prevWsSymbolRef = useRef(null)
  useEffect(() => {
    if (ws.isConnected) {
      if (prevWsSymbolRef.current && prevWsSymbolRef.current !== symbol) {
        ws.unsubscribe([prevWsSymbolRef.current])
      }
      ws.subscribe([symbol])
      prevWsSymbolRef.current = symbol
    }
  }, [symbol, ws.isConnected])

  useEffect(() => {
    if (ws.messages.length === 0 || ws.messages.length <= lastProcessedMsgIdx.current) return

    const newMessages = ws.messages.slice(lastProcessedMsgIdx.current)
    lastProcessedMsgIdx.current = ws.messages.length

    let tickUpdate = null
    let candleUpdates = []

    // 1. Accumulate latest relevant updates to minimize redundant render cycles
    for (const latest of newMessages) {
      if (!isPlainObject(latest)) continue
      if (latest.symbol !== symbol) continue

      if (latest.type === 'tick') {
        tickUpdate = latest // We only care about the most recent tick in this batch
        console.log("WS DATA:", latest)
        
        if (latest.signal) {
           console.log("UPDATED SIGNAL:", latest.signal)
           setPrediction(prev => ({ ...(prev || {}), signal: latest.signal }))
        }
      } else if (latest.type === 'candle_update') {
        candleUpdates.push(latest) // Keep all candle updates to maintain structural integrity
      }
    }

    // 2. Perform batched Snapshot state update
    if (tickUpdate) {
      const ltp = toFiniteNumber(tickUpdate.ltp)
      const bid = toFiniteNumber(tickUpdate.bid)
      const ask = toFiniteNumber(tickUpdate.ask)
      const volume = toFiniteNumber(tickUpdate.volume)

      if (ltp != null) {
        setSnapshot(prev => ({
          ...(isPlainObject(prev) ? prev : {}),
          ltp,
          bid: bid ?? ltp,
          ask: ask ?? ltp,
          volume: volume ?? 0,
        }))
        setIsMockData(false)
      }
    }

    // 3. Perform single batched OHLCV state update combining candles and final tick
    if (candleUpdates.length > 0 || tickUpdate) {
      setOhlcv(prev => {
        if (!Array.isArray(prev) || prev.length === 0) {
          // If empty and we have a candle, initialize it
          if (candleUpdates.length > 0) {
            const first = candleUpdates[0]
            const open = toFiniteNumber(first.open)
            const close = toFiniteNumber(first.close)
            if (open != null && close != null) {
                return [{ time: first.timestamp, open, high: toFiniteNumber(first.high) || Math.max(open, close), low: toFiniteNumber(first.low) || Math.min(open, close), close, volume: toFiniteNumber(first.volume) || 0 }]
            }
          }
          return prev
        }

        const newOhlcv = [...prev]
        const tfMs = TIMEFRAME_TO_MS[timeframe] || 60000
        let modified = false

        // Process all candle completions
        for (const latest of candleUpdates) {
          let open = toFiniteNumber(latest.open)
          let high = toFiniteNumber(latest.high)
          let low = toFiniteNumber(latest.low)
          let close = toFiniteNumber(latest.close)
          const volume = toFiniteNumber(latest.volume) ?? 0
          const timestamp = typeof latest.timestamp === 'string' && latest.timestamp ? latest.timestamp : null

          if (open == null || high == null || low == null || !timestamp) continue
          if (latest.interval && latest.interval !== timeframe) {
            console.warn(`[WS Candle] Rejected mismatched timeframe block. Expected ${timeframe}`)
            continue
          }

          const previousClose = newOhlcv[newOhlcv.length - 1].close
          if (close == null) close = previousClose
          if (open == null) open = previousClose

          const changePct = Math.abs(close - previousClose) / (previousClose || 1)
          if (changePct > 0.03) {
             console.warn(`[WS Candle] Suppressed abnormal >3% spike: ${previousClose} -> ${close}`)
             open = previousClose; close = previousClose; high = previousClose; low = previousClose;
          }

          high = Math.max(high, open, close)
          low = Math.min(low, open, close)

          const newCandle = { time: timestamp, open, high, low, close, volume }
          const lastIdx = newOhlcv.length - 1
          
          const currMs = new Date(timestamp).getTime()
          const prevMs = new Date(newOhlcv[lastIdx].time).getTime()
          const timeDiffMs = currMs - prevMs

          if (lastIdx >= 0 && newOhlcv[lastIdx]?.time === timestamp) {
            newOhlcv[lastIdx] = newCandle
          } else if (currMs >= prevMs + tfMs || currMs < prevMs) {
            if (timeDiffMs >= tfMs * 2) {
              console.warn(`[WS Merge] Potential gap detected: ${new Date(prevMs).toISOString()} → ${new Date(currMs).toISOString()}`)
            }
            newOhlcv.push(newCandle)
          } else {
            const last = newOhlcv[lastIdx]
            last.close = close
            last.high = Math.max(last.high, high)
            last.low = Math.min(last.low, low)
            last.volume += volume
          }
          modified = true
        }

        // Apply final tick to the current active candle wick
        if (tickUpdate) {
          const ltp = toFiniteNumber(tickUpdate.ltp)
          if (ltp != null) {
            const last = { ...newOhlcv[newOhlcv.length - 1] }
            const changePct = Math.abs(ltp - last.close) / (last.close || 1)
            if (changePct <= 0.03) {
              const lastHigh = toFiniteNumber(last.high) ?? ltp
              const lastLow = toFiniteNumber(last.low) ?? ltp
              last.close = ltp
              last.high = Math.max(lastHigh, ltp)
              last.low = Math.min(lastLow, ltp)
              newOhlcv[newOhlcv.length - 1] = last
              modified = true
            } else {
              console.warn(`[WS Tick] Ignored abnormal >3% spike: ${last.close} -> ${ltp}`)
            }
          }
        }

        if (modified) {
          if (newOhlcv.length > 500) newOhlcv.shift()
          return newOhlcv
        }
        return prev
      })
    }
  }, [ws.messages, symbol, timeframe])

  return {
    symbol, setSymbol,
    timeframe, setTimeframe,
    ohlcv, snapshot, prediction, indicators, setIndicators, indicatorData,
    loading, errorMsg, isMockData, marketStatus, activeSignal, setActiveSignal,
    loadMoreHistory
  }
}
