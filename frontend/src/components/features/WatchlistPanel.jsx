import React, { memo } from 'react';
import { useAppContext } from '../../context/AppContext';
import { SkeletonText } from '../ui/Skeleton';

const WatchlistRow = memo(({ symbol, isActive, onSelect }) => {
  const { prices, isLoading } = useAppContext();
  const baseItem = prices[symbol];

  const currentPrice = baseItem?.price;
  const currentChange = baseItem?.change;
  
  if (!baseItem || isLoading) {
    return (
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <SkeletonText width="100%" />
      </div>
    )
  }
  
  const isUp = currentChange >= 0;

  return (
    <div
      onClick={() => onSelect(symbol)}
      className="touch-target"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '16px',
        cursor: 'pointer',
        background: isActive ? 'rgba(0, 255, 159, 0.05)' : 'transparent',
        borderLeft: isActive ? '4px solid var(--primary)' : '4px solid transparent',
        borderBottom: '1px solid var(--border-subtle, var(--border))',
        transition: 'background 0.2s ease',
        fontFamily: 'var(--font-family-base)',
      }}
    >
      <div style={{ fontWeight: isActive ? 'bold' : 'normal', color: isActive ? '#fff' : 'var(--text-secondary)' }}>
        {symbol}
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: '#fff', fontFamily: 'var(--font-family-mono)', fontWeight: 'bold' }}>
          {currentPrice != null ? `₹${currentPrice.toFixed(2)}` : '—'}
        </div>
        <div style={{ color: isUp ? 'var(--primary, #00FF9F)' : '#FF4C4C', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '4px' }}>
          {currentChange != null ? (isUp ? '▲' : '▼') : '•'} {currentChange != null ? Math.abs(currentChange).toFixed(2) : 'no data'}
        </div>
      </div>
    </div>
  );
});

export const WatchlistPanel = () => {
  const { selectedSymbol, selectSymbol, watchlistSymbols } = useAppContext();
  const symbols = watchlistSymbols;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'transparent' }}>
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border-subtle, var(--border))' }}>
        <h2 style={{ fontSize: '14px', color: 'var(--text-secondary)', margin: 0, textTransform: 'uppercase', fontFamily: 'var(--font-family-base)' }}>Watchlist</h2>
      </div>
      
      <div style={{ overflowY: 'auto', flex: 1, paddingBottom: "20px" }}>
        {symbols.map((symbol) => (
          <WatchlistRow 
            key={symbol} 
            symbol={symbol} 
            isActive={selectedSymbol === symbol} 
            onSelect={selectSymbol} 
          />
        ))}
      </div>
    </div>
  );
};

export default WatchlistPanel;
