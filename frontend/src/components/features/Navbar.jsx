import React, { useState, useEffect } from 'react';
import { useAppContext } from '../../context/AppContext';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../ui/Toast';

export const Navbar = () => {
  const [time, setTime] = useState(new Date());
  const {
    selectedSymbol,
    selectedTimeframe,
    watchlistSymbols,
    isLoading,
    wsStatus,
    selectSymbol,
    selectTimeframe,
    refreshBundle,
  } = useAppContext();
  const { user, logout } = useAuth();
  const { showToast } = useToast();

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const istString = time.toLocaleTimeString('en-US', { timeZone: 'Asia/Kolkata', hour12: false });
  const [hours, minutes] = istString.split(':').map(Number);
  
  const isMarketOpen = (hours > 9 || (hours === 9 && minutes >= 15)) && 
                       (hours < 15 || (hours === 15 && minutes <= 30));

  let dotColor = '#FF4C4C';
  if (wsStatus === 'open') dotColor = '#00FF9F';
  else if (wsStatus === 'connecting' || wsStatus === 'reconnecting') dotColor = '#FFB347';
  else if (wsStatus === 'unauthenticated') dotColor = '#8b9bb2';

  const onLogout = async () => {
    await logout();
    showToast('Session cleared', 'info');
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '12px 24px',
      background: 'var(--card, #0C1118)',
      borderBottom: '1px solid var(--border, #1A2332)'
    }}>
      <div style={{ fontSize: '18px', fontWeight: 'bold', fontFamily: 'var(--font-family-base)' }}>
        Stock <span style={{ color: 'var(--primary, #00FF9F)' }}>AI</span> Pro
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <select
          value={selectedSymbol}
          onChange={(e) => selectSymbol(e.target.value)}
          style={{
            background: 'var(--bg-interactive)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            padding: '6px 10px',
          }}
        >
          {watchlistSymbols.map((symbol) => (
            <option key={symbol} value={symbol}>{symbol}</option>
          ))}
        </select>

        <select
          value={selectedTimeframe}
          onChange={(e) => selectTimeframe(e.target.value)}
          style={{
            background: 'var(--bg-interactive)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            padding: '6px 10px',
          }}
        >
          {['1m', '5m', '15m', '30m', '1h', '1d'].map((tf) => (
            <option key={tf} value={tf}>{tf.toUpperCase()}</option>
          ))}
        </select>
        
        <div style={{ 
          fontSize: '13px', 
          fontWeight: 'bold',
          color: 'var(--primary)',
          borderRight: '1px solid var(--border)',
          paddingRight: '16px',
          cursor: 'pointer'
        }} onClick={refreshBundle} className="touch-target">
          {isLoading ? 'SYNCING...' : `REFRESH ${selectedSymbol}`}
        </div>

        <div style={{ fontFamily: 'var(--font-family-mono, monospace)', fontSize: '14px', color: 'var(--text-secondary)' }}>
          {istString} IST
        </div>
        
        <div style={{
          background: isMarketOpen ? 'rgba(0, 255, 159, 0.1)' : 'rgba(255, 76, 76, 0.1)',
          color: isMarketOpen ? '#00FF9F' : '#FF4C4C',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '11px',
          fontWeight: 'bold',
          letterSpacing: '0.05em',
          fontFamily: 'var(--font-family-base)'
        }}>
          MARKET {isMarketOpen ? 'OPEN' : 'CLOSED'}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'var(--font-family-base)' }}>
          <div style={{ 
            width: '8px', 
            height: '8px', 
            borderRadius: '50%', 
            background: dotColor, 
            boxShadow: `0 0 8px ${dotColor}`,
            transition: 'background 0.3s ease'
          }} />
          <span>{wsStatus.toUpperCase()}</span>
        </div>

        <div style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
          {user?.username || 'anonymous'}
        </div>

        <button
          onClick={onLogout}
          style={{
            border: '1px solid var(--border-subtle)',
            background: 'transparent',
            color: 'var(--text-primary)',
            borderRadius: '6px',
            padding: '6px 10px',
            cursor: 'pointer',
          }}
        >
          Logout
        </button>
      </div>
    </div>
  );
};

export default Navbar;
