/**
 * Generate mock OHLCV candle data for chart display when SmartAPI is unavailable.
 * Uses symbol name for deterministic but varied price ranges.
 */
export function generateMockOhlcv(symbol, interval = '1m', count = 200) {
  const base = getBasePrice(symbol)
  const volatility = base * 0.002
  const data = []
  const now = Date.now()
  const msPerCandle = getMsPerCandle(interval)

  let open = base
  for (let i = count - 1; i >= 0; i--) {
    const t = new Date(now - i * msPerCandle)
    const change = (Math.random() - 0.48) * volatility
    const close = Math.max(base * 0.8, Math.min(base * 1.2, open + change))
    const high = Math.max(open, close) + Math.random() * volatility * 0.5
    const low = Math.min(open, close) - Math.random() * volatility * 0.5
    const volume = Math.floor(10000 + Math.random() * 500000)

    data.push({
      time: t.toISOString().slice(0, 19).replace('T', ' '),
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
      volume,
    })
    open = close
  }
  return data
}

function getBasePrice(symbol) {
  const prices = {
    RELIANCE: 2500, TCS: 3800, INFY: 1550, HDFCBANK: 1680, SBIN: 780,
    ICICIBANK: 1180, TATASTEEL: 145, ITC: 465, AXISBANK: 1180, KOTAKBANK: 1780,
    'NIFTY 50': 24000, BANKNIFTY: 52000,
  }
  return prices[symbol?.toUpperCase()] || 1000
}

function getMsPerCandle(interval) {
  const map = { '1m': 60e3, '3m': 180e3, '5m': 300e3, '15m': 900e3, '30m': 1800e3, '1h': 3600e3, '1d': 86400e3 }
  return map[interval] || 60e3
}
