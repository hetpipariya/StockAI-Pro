import React, { useState, useEffect } from 'react';

const MarketBackground = () => {
  const [marketData, setMarketData] = useState([]);
  const [tickers, setTickers] = useState([]);

  // Mock market symbols and data
  const symbols = [
    { symbol: 'NIFTY', basePrice: 24850, change: 0.82 },
    { symbol: 'BANKNIFTY', basePrice: 52430, change: -0.31 },
    { symbol: 'RELIANCE', basePrice: 2847.50, change: 1.24 },
    { symbol: 'TCS', basePrice: 3901.20, change: -0.67 },
    { symbol: 'INFY', basePrice: 2108.90, change: 0.45 },
    { symbol: 'WIPRO', basePrice: 484.35, change: -1.15 },
    { symbol: 'MARUTI', basePrice: 13042.50, change: 2.10 },
    { symbol: 'TATASTEEL', basePrice: 126.45, change: -0.92 },
    { symbol: 'ADANIENT', basePrice: 598.70, change: 1.88 },
    { symbol: 'HDFCBANK', basePrice: 1812.20, change: 0.51 },
    { symbol: 'ICICIBANK', basePrice: 1087.30, change: -0.28 },
    { symbol: 'SBIN', basePrice: 745.60, change: 1.42 },
    { symbol: 'LT', basePrice: 3240.15, change: -0.73 },
    { symbol: 'JSWSTEEL', basePrice: 915.80, change: 0.96 },
    { symbol: 'HINDALCO', basePrice: 673.25, change: -1.33 },
  ];

  useEffect(() => {
    // Create duplicates for continuous scrolling effect
    setTickers(symbols);
    
    // Simulate live price updates
    const interval = setInterval(() => {
      setMarketData(
        symbols.map((item) => ({
          ...item,
          price: (item.basePrice + (Math.random() - 0.5) * 10).toFixed(2),
          change: (item.change + (Math.random() - 0.5) * 0.5).toFixed(2),
        }))
      );
    }, 3000); // Update every 3 seconds

    return () => clearInterval(interval);
  }, []);

  const displayTickers = marketData.length > 0 ? marketData : symbols;

  return (
    <div className="market-background-container">
      <div className="market-ticker-wrapper">
        <div className="market-ticker">
          {/* First set */}
          {displayTickers.map((item, index) => (
            <div key={`ticker-1-${index}`} className="market-item">
              <span className="market-symbol">{item.symbol}</span>
              <span className="market-price">{item.price || item.basePrice.toFixed(2)}</span>
              <span
                className={`market-change ${
                  (parseFloat(item.change) || 0) >= 0 ? 'positive' : 'negative'
                }`}
              >
                {(parseFloat(item.change) || item.change) > 0 ? '+' : ''}
                {parseFloat(item.change) || item.change}%
              </span>
            </div>
          ))}
          
          {/* Duplicate set for seamless scroll */}
          {displayTickers.map((item, index) => (
            <div key={`ticker-2-${index}`} className="market-item">
              <span className="market-symbol">{item.symbol}</span>
              <span className="market-price">{item.price || item.basePrice.toFixed(2)}</span>
              <span
                className={`market-change ${
                  (parseFloat(item.change) || 0) >= 0 ? 'positive' : 'negative'
                }`}
              >
                {(parseFloat(item.change) || item.change) > 0 ? '+' : ''}
                {parseFloat(item.change) || item.change}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <style>{`
        .market-background-container {
          position: fixed;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          overflow: hidden;
          background: linear-gradient(to bottom,
            rgba(0, 0, 0, 0),
            rgba(0, 0, 0, 0.02),
            rgba(0, 0, 0, 0)
          );
        }

        .market-ticker-wrapper {
          position: absolute;
          inset: 0;
          overflow: hidden;
          opacity: 0.08;
          filter: blur(1.5px);
          -webkit-filter: blur(1.5px);
        }

        .market-ticker {
          display: flex;
          gap: 3rem;
          animation: scroll-left 120s linear infinite;
          width: max-content;
          padding: 2rem 0;
          font-family: 'Courier New', 'JetBrains Mono', monospace;
          font-size: 0.875rem;
          font-weight: 500;
          letter-spacing: 0.05em;
          text-transform: uppercase;
        }

        @keyframes scroll-left {
          0% {
            transform: translateX(0);
          }
          100% {
            transform: translateX(-50%);
          }
        }

        .market-item {
          display: inline-flex;
          gap: 0.75rem;
          white-space: nowrap;
          align-items: center;
          padding: 0.5rem 1rem;
          border: 1px solid rgba(255, 255, 255, 0.05);
          border-radius: 0.5rem;
          background: rgba(0, 0, 0, 0.3);
          backdrop-filter: blur(2px);
        }

        .market-symbol {
          color: rgba(226, 232, 240, 0.6);
          font-weight: 600;
          min-width: 4rem;
        }

        .market-price {
          color: rgba(148, 163, 184, 0.5);
          font-family: 'Courier New', monospace;
          min-width: 5rem;
          text-align: right;
        }

        .market-change {
          min-width: 3.5rem;
          text-align: right;
          font-weight: 600;
          font-size: 0.8em;
          animation: price-pulse 2s ease-in-out infinite;
        }

        .market-change.positive {
          color: rgba(16, 185, 129, 0.6);
          text-shadow: 0 0 8px rgba(16, 185, 129, 0.2);
        }

        .market-change.negative {
          color: rgba(239, 68, 68, 0.6);
          text-shadow: 0 0 8px rgba(239, 68, 68, 0.2);
        }

        @keyframes price-pulse {
          0%, 100% {
            opacity: 0.6;
          }
          50% {
            opacity: 0.9;
          }
        }

        /* Add vertical tickers for extra effect */
        .market-background-container::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 30%;
          background: linear-gradient(
            180deg,
            transparent 0%,
            rgba(34, 211, 238, 0.03) 50%,
            transparent 100%
          );
          pointer-events: none;
          z-index: 1;
        }

        .market-background-container::after {
          content: '';
          position: absolute;
          bottom: 0;
          left: 0;
          right: 0;
          height: 30%;
          background: linear-gradient(
            0deg,
            transparent 0%,
            rgba(16, 185, 129, 0.02) 50%,
            transparent 100%
          );
          pointer-events: none;
          z-index: 1;
        }

        @media (max-width: 768px) {
          .market-ticker-wrapper {
            opacity: 0.05;
            filter: blur(1px);
          }

          .market-ticker {
            gap: 1.5rem;
            font-size: 0.75rem;
            animation: scroll-left 80s linear infinite;
          }

          .market-item {
            padding: 0.375rem 0.75rem;
            gap: 0.5rem;
          }
        }
      `}</style>
    </div>
  );
};

export default MarketBackground;
