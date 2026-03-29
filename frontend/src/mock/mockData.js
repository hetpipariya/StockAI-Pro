export const mockSymbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'NIFTY50'];

export const mockPrices = {
  RELIANCE: { price: 2950.45, change: 1.24, changePct: 0.04 },
  TCS: { price: 3820.10, change: -15.40, changePct: -0.40 },
  INFY: { price: 1520.60, change: 2.10, changePct: 0.14 },
  HDFCBANK: { price: 1432.10, change: -1.10, changePct: -0.08 },
  NIFTY50: { price: 22450.00, change: 0.80, changePct: 0.003 },
};

export const generateMockSignal = (symbol) => {
  const signals = ['BUY', 'SELL', 'HOLD'];
  const basePrice = mockPrices[symbol]?.price || 1000;
  const signalType = signals[Math.floor(Math.random() * signals.length)];
  const confidence = Math.floor(Math.random() * (92 - 45 + 1)) + 45; 
  
  let target, stopLoss;
  if (signalType === 'BUY') {
    target = basePrice * (1 + (Math.random() * 0.05 + 0.01));
    stopLoss = basePrice * (1 - (Math.random() * 0.03 + 0.01));
  } else if (signalType === 'SELL') {
    target = basePrice * (1 - (Math.random() * 0.05 + 0.01));
    stopLoss = basePrice * (1 + (Math.random() * 0.03 + 0.01));
  } else {
    target = basePrice;
    stopLoss = basePrice;
  }

  return {
    symbol,
    signal: signalType,
    confidence,
    target: Number(target.toFixed(2)),
    stopLoss: Number(stopLoss.toFixed(2)),
    currentPrice: Number(basePrice.toFixed(2)),
    timestamp: new Date().toISOString(),
    indicators: { 
      rsi: Number((Math.random() * 60 + 20).toFixed(1)), 
      ema9: Number((basePrice * 0.99).toFixed(2)), 
      ema21: Number((basePrice * 0.98).toFixed(2)), 
      macd: Number((Math.random() * 20 - 10).toFixed(2)) 
    }
  };
};

export const generateMockCandles = (symbol, count = 30) => {
  const basePrice = mockPrices[symbol]?.price || 1000;
  const data = [];
  const now = new Date();
  let currentPrice = basePrice * 0.95; 
  
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setMinutes(d.getMinutes() - i * 5); 
    
    // random walk logic
    const volatility = currentPrice * 0.002;
    const open = currentPrice;
    const close = currentPrice + (Math.random() - 0.5) * volatility;
    const high = Math.max(open, close) + Math.random() * volatility;
    const low = Math.min(open, close) - Math.random() * volatility;
    
    data.push({
      time: Math.floor(d.getTime() / 1000), 
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2))
    });
    
    currentPrice = close;
  }
  return data;
};
