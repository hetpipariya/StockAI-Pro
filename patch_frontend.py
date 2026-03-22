import sys

path = r'e:\Projects\stockai-pro\frontend\src\hooks\useTradingEngine.jsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target1 = """      const [hist, snap, pred, stat, ind] = await Promise.all([
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
      const histData = validateAndCleanOHLCV(rawHistData, timeframe)"""

replacement1 = """      const [histRaw, snapRaw, predRaw, statRaw, indRaw] = await Promise.all([
        parseJsonSafe(histRes, {}),
        parseJsonSafe(snapRes, {}),
        parseJsonSafe(predRes, {}),
        parseJsonSafe(statRes, {}),
        indRes ? parseJsonSafe(indRes, {}) : Promise.resolve({}),
      ])

      const hist = histRaw?.data || {}
      const snap = snapRaw?.data || {}
      const pred = predRaw?.data || {}
      const stat = statRaw?.data || {}
      const ind = indRaw?.data || {}

      const histError = histRaw?.status === 'error' || hist?.error;
      const snapError = snapRaw?.status === 'error' || snap?.error;
      const predError = predRaw?.status === 'error' || pred?.error;

      if (fetchToken !== activeFetchTokenRef.current) return

      if (histError) {
         setErrorMsg("No market data available")
      } else {
         setErrorMsg(null)
      }

      const rawHistData = Array.isArray(hist?.data) ? hist.data.filter((candle) => isPlainObject(candle)) : []
      const histData = validateAndCleanOHLCV(rawHistData, timeframe)"""


target2 = """      } else if (!hist?.error && fetchToken === 1) {
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
      previousPredictionRef.current = pred?.error ? null : pred"""

replacement2 = """      } else if (!histError && fetchToken === 1) {
        setOhlcv([])
      }
      
      setSnapshot(!snapError && isPlainObject(snap) ? snap : null)
      setPrediction(prev => {
        const newPred = pred;
        console.log('[PREDICTION UPDATE]', symbol, newPred);  // Debug log
        if (predError) {
          console.warn('[PREDICTION ERROR]', newPred?.error || 'Unknown error');
          return prev;
        }
        if (!isPlainObject(newPred)) return prev;
        if (!prev) return newPred;
        return { ...newPred, signal: prev.signal || newPred.signal };
      })
      setIndicatorData(Array.isArray(ind?.data) ? ind.data.filter((row) => isPlainObject(row)) : [])

      const predConfidence = toFiniteNumber(pred?.confidence) ?? 0
      if (!predError && pred?.signal && pred.signal !== 'HOLD' && predConfidence >= 70) {
        if (!previousPredictionRef.current || previousPredictionRef.current.signal !== pred.signal) {
          setActiveSignal(pred)
        }
      }
      previousPredictionRef.current = predError ? null : pred"""

target3 = """      console.info(`[Pagination] Loading history before ${toTime}`)
      const res = await fetch(`${API_BASE}/market/history?symbol=${symbol}&interval=${tf}&limit=500&to_time=${toTime}`)
      const hist = await parseJsonSafe(res, {})
      
      const rawNewCandles = Array.isArray(hist?.data) ? hist.data.filter((candle) => isPlainObject(candle)) : []"""

replacement3 = """      console.info(`[Pagination] Loading history before ${toTime}`)
      const res = await fetch(`${API_BASE}/market/history?symbol=${symbol}&interval=${tf}&limit=500&to_time=${toTime}`)
      const histRaw = await parseJsonSafe(res, {})
      const hist = histRaw?.data || {}
      
      const rawNewCandles = Array.isArray(hist?.data) ? hist.data.filter((candle) => isPlainObject(candle)) : []"""

for t, r in [(target1, replacement1), (target2, replacement2), (target3, replacement3)]:
    if t in content:
        content = content.replace(t, r)
    elif t.replace('\n', '\r\n') in content:
        content = content.replace(t.replace('\n', '\r\n'), r.replace('\n', '\r\n'))
    else:
        print(f"Target not found: {t[:50]}...")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied.")
