import { useEffect, useMemo, useRef, useState } from 'react';
import ChartPanel from '../components/features/ChartPanel';
import SignalPage from '../components/features/SignalPage';
import { useAppContext } from '../context/AppContext';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/ui/Toast';

const TABS = [
  { id: 'chart', label: 'Chart', icon: '📈' },
  { id: 'signal', label: 'Signal', icon: '🧠' },
  { id: 'watchlist', label: 'Watch', icon: '⭐' },
];

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '1d'];

const toNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const compactPrice = (value) => {
  const num = toNumber(value, null);
  if (num == null) return '--';
  return num.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
};

const getSignalTheme = (signal) => {
  if (signal === 'BUY') {
    return {
      glow: 'rgba(34, 197, 94, 0.38)',
      border: 'rgba(34, 197, 94, 0.48)',
      text: '#4ade80',
      gradient: 'linear-gradient(140deg, rgba(15, 118, 110, 0.34), rgba(16, 185, 129, 0.14) 45%, rgba(5, 10, 14, 0.96) 100%)',
      confidence: 'linear-gradient(90deg, #10b981 0%, #34d399 55%, #86efac 100%)',
    };
  }
  if (signal === 'SELL') {
    return {
      glow: 'rgba(248, 113, 113, 0.38)',
      border: 'rgba(248, 113, 113, 0.48)',
      text: '#f87171',
      gradient: 'linear-gradient(140deg, rgba(127, 29, 29, 0.38), rgba(239, 68, 68, 0.14) 45%, rgba(5, 10, 14, 0.96) 100%)',
      confidence: 'linear-gradient(90deg, #ef4444 0%, #f87171 55%, #fca5a5 100%)',
    };
  }
  return {
    glow: 'rgba(148, 163, 184, 0.28)',
    border: 'rgba(148, 163, 184, 0.4)',
    text: '#e2e8f0',
    gradient: 'linear-gradient(140deg, rgba(30, 41, 59, 0.6), rgba(71, 85, 105, 0.12) 40%, rgba(5, 10, 14, 0.96) 100%)',
    confidence: 'linear-gradient(90deg, #64748b 0%, #94a3b8 100%)',
  };
};

export default function MobileLayout() {
  const {
    selectedSymbol,
    selectedTimeframe,
    selectSymbol,
    selectTimeframe,
    watchlistSymbols,
    prices,
    indicators,
    currentSignal,
    isSignalLoading,
    signalError,
    refreshSignal,
    wsStatus,
  } = useAppContext();
  const { logout } = useAuth();
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState('chart');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showIndicators, setShowIndicators] = useState(true);
  const [useLightTheme, setUseLightTheme] = useState(false);
  const [sheetExpanded, setSheetExpanded] = useState(false);
  const [showSignal, setShowSignal] = useState(false);
  const [dragStartY, setDragStartY] = useState(null);
  const hideSignalTimerRef = useRef(null);

  const signal = currentSignal?.signal || 'HOLD';
  const confidence = Math.max(0, Math.min(100, Math.round(toNumber(currentSignal?.confidence, 0) || 0)));
  const signalTheme = getSignalTheme(signal);
  const price = compactPrice(currentSignal?.currentPrice);
  const target = compactPrice(currentSignal?.target);
  const stopLoss = compactPrice(currentSignal?.stopLoss);
  const signalEventKey = useMemo(() => {
    if (!currentSignal) return '';
    return [
      selectedSymbol,
      currentSignal?.signal,
      Math.round(toNumber(currentSignal?.confidence, 0) || 0),
      toNumber(currentSignal?.target, 0),
      toNumber(currentSignal?.stopLoss, 0),
      currentSignal?.regime || '',
      currentSignal?.explanation || '',
    ].join('|');
  }, [
    currentSignal,
    selectedSymbol,
  ]);

  const indicatorPills = useMemo(() => {
    const ema = toNumber(indicators?.ema9 ?? indicators?.ema_9 ?? indicators?.ema15 ?? indicators?.ema, null);
    const rsi = toNumber(indicators?.rsi9 ?? indicators?.rsi_14 ?? indicators?.rsi, null);
    const macd = toNumber(indicators?.macd ?? indicators?.macd_hist, null);
    return [
      { key: 'ema', label: 'EMA', value: ema == null ? '--' : ema.toFixed(2) },
      { key: 'rsi', label: 'RSI', value: rsi == null ? '--' : rsi.toFixed(1) },
      { key: 'macd', label: 'MACD', value: macd == null ? '--' : macd.toFixed(2) },
    ];
  }, [indicators]);

  const surfaceVars = useLightTheme
    ? {
      '--bg-app': '#f2f5fb',
      '--bg-panel': '#ffffff',
      '--bg-interactive': '#eef2f9',
      '--bg-interactive-hover': '#e4eaf6',
      '--text-primary': '#0f172a',
      '--text-secondary': '#475569',
      '--text-muted': '#64748b',
      '--border-subtle': '#dbe4f3',
      '--border-focus': '#c4d2ec',
    }
    : undefined;

  useEffect(() => {
    if (hideSignalTimerRef.current) {
      clearTimeout(hideSignalTimerRef.current);
      hideSignalTimerRef.current = null;
    }

    if (!currentSignal || !signalEventKey || activeTab !== 'chart') {
      setShowSignal(false);
      return;
    }

    setSheetExpanded(false);
    setShowSignal(true);

    hideSignalTimerRef.current = setTimeout(() => {
      setShowSignal(false);
      hideSignalTimerRef.current = null;
    }, 2000);

    return () => {
      if (hideSignalTimerRef.current) {
        clearTimeout(hideSignalTimerRef.current);
        hideSignalTimerRef.current = null;
      }
    };
  }, [activeTab, currentSignal, signalEventKey]);

  const closeDrawer = () => {
    setDrawerOpen(false);
    if (activeTab === 'watchlist') {
      setActiveTab('chart');
    }
  };

  const getClientY = (event) => {
    if (typeof event?.touches?.[0]?.clientY === 'number') return event.touches[0].clientY;
    if (typeof event?.changedTouches?.[0]?.clientY === 'number') return event.changedTouches[0].clientY;
    return event?.clientY;
  };

  const onSheetDragStart = (event) => {
    setDragStartY(getClientY(event));
  };

  const onSheetDragEnd = (event) => {
    const endY = getClientY(event);
    if (dragStartY == null || endY == null) {
      setDragStartY(null);
      return;
    }
    const delta = endY - dragStartY;
    if (delta < -44) setSheetExpanded(true);
    if (delta > 44) setSheetExpanded(false);
    setDragStartY(null);
  };

  const onTabSelect = (tabId) => {
    setActiveTab(tabId);
    setMenuOpen(false);

    if (tabId === 'watchlist') {
      setDrawerOpen(true);
      setSheetExpanded(false);
      return;
    }

    setDrawerOpen(false);
    setSheetExpanded(false);
    if (tabId === 'signal') {
      setShowSignal(false);
    }
  };

  const onMenuAction = async (action) => {
    setMenuOpen(false);
    if (action === 'settings') {
      showToast('Settings screen coming soon', 'info');
      return;
    }
    if (action === 'logout') {
      await logout();
      showToast('Logged out', 'info');
    }
  };

  const contentHeight = showIndicators ? 'calc(100dvh - 168px)' : 'calc(100dvh - 132px)';

  return (
    <div className="mobile-premium-root" style={surfaceVars}>
      <header className="mobile-premium-header">
        <button
          type="button"
          className="mobile-icon-btn"
          onClick={() => {
            setDrawerOpen(true);
            setActiveTab('watchlist');
            setMenuOpen(false);
          }}
          aria-label="Open watchlist"
        >
          ☰
        </button>

        <div className="mobile-brand-pill" aria-label="StockAI Pro">SA</div>

        <select
          className="mobile-select"
          value={selectedSymbol}
          onChange={(event) => selectSymbol(event.target.value)}
          aria-label="Select symbol"
        >
          {watchlistSymbols.map((symbolName) => (
            <option key={symbolName} value={symbolName}>{symbolName}</option>
          ))}
        </select>

        <select
          className="mobile-select mobile-select-timeframe"
          value={selectedTimeframe}
          onChange={(event) => selectTimeframe(event.target.value)}
          aria-label="Select timeframe"
        >
          {TIMEFRAMES.map((tf) => (
            <option key={tf} value={tf}>{tf.toUpperCase()}</option>
          ))}
        </select>

        <div className="mobile-menu-wrap">
          <button
            type="button"
            className="mobile-icon-btn"
            onClick={() => setMenuOpen((prev) => !prev)}
            aria-label="More options"
          >
            ⋮
          </button>

          {menuOpen && (
            <div className="mobile-more-menu" role="menu">
              <button type="button" onClick={() => setShowIndicators((prev) => !prev)}>
                Indicators: {showIndicators ? 'On' : 'Off'}
              </button>
              <button type="button" onClick={() => setUseLightTheme((prev) => !prev)}>
                Theme: {useLightTheme ? 'Light' : 'Dark'}
              </button>
              <button type="button" onClick={() => onMenuAction('settings')}>Settings</button>
              <button type="button" onClick={() => onMenuAction('logout')}>Logout</button>
            </div>
          )}
        </div>
      </header>

      {showIndicators && (
        <div className="mobile-indicator-row" aria-label="Indicators">
          {indicatorPills.map((pill) => (
            <div key={pill.key} className="mobile-indicator-pill">
              <span>{pill.label}</span>
              <strong>{pill.value}</strong>
            </div>
          ))}
        </div>
      )}

      <main className="mobile-premium-main" style={{ height: contentHeight }}>
        {activeTab === 'signal' ? (
          isSignalLoading ? (
            <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-secondary)' }}>
              Loading live signal...
            </div>
          ) : signalError ? (
            <div style={{ height: '100%', display: 'grid', placeItems: 'center', padding: '18px' }}>
              <div style={{ maxWidth: '320px', width: '100%', textAlign: 'center', border: '1px solid var(--border-subtle)', borderRadius: '14px', background: 'rgba(15, 23, 42, 0.55)', padding: '16px' }}>
                <p style={{ margin: 0, color: '#fda4af', fontWeight: 600 }}>Live signal unavailable</p>
                <p style={{ margin: '8px 0 0', color: 'var(--text-secondary)', fontSize: '13px' }}>{signalError}</p>
                <button
                  type="button"
                  onClick={refreshSignal}
                  style={{ marginTop: '12px', borderRadius: '10px', border: '1px solid var(--border-focus)', background: 'var(--bg-interactive)', color: 'var(--text-primary)', padding: '8px 12px' }}
                >
                  Retry
                </button>
              </div>
            </div>
          ) : (
            <SignalPage
              signal={signal}
              confidence={confidence}
              currentPrice={currentSignal?.currentPrice}
              target={currentSignal?.target}
              stopLoss={currentSignal?.stopLoss}
              regime={currentSignal?.regime}
              explanation={currentSignal?.explanation}
              symbol={selectedSymbol}
            />
          )
        ) : (
          <div className="mobile-premium-chart-shell">
            <ChartPanel hideHeader chartPadding="0" />
          </div>
        )}
      </main>

      <div className={`mobile-watchlist-backdrop ${drawerOpen ? 'open' : ''}`} onClick={closeDrawer} />
      <aside className={`mobile-watchlist-drawer ${drawerOpen ? 'open' : ''}`} aria-label="Watchlist drawer">
        <div className="mobile-watchlist-drawer-head">
          <h3>Watchlist</h3>
          <button type="button" onClick={closeDrawer} aria-label="Close watchlist">✕</button>
        </div>

        <div className="mobile-watchlist-list">
          {watchlistSymbols.map((symbolName) => {
            const item = prices[symbolName] || {};
            const change = toNumber(item.change, 0);
            const isUp = change >= 0;
            return (
              <button
                type="button"
                key={symbolName}
                className={`mobile-watchlist-item ${selectedSymbol === symbolName ? 'active' : ''}`}
                onClick={() => {
                  selectSymbol(symbolName);
                  setActiveTab('chart');
                  closeDrawer();
                }}
              >
                <span className="name">{symbolName}</span>
                <span className="price">₹{compactPrice(item.price)}</span>
                <span className={`change ${isUp ? 'up' : 'down'}`}>{isUp ? '▲' : '▼'} {Math.abs(change).toFixed(2)}</span>
              </button>
            );
          })}
        </div>
      </aside>

      {activeTab === 'chart' && (
        <section
          className={`mobile-signal-sheet ${sheetExpanded ? 'expanded' : 'peek'} ${showSignal ? 'visible' : 'hidden'}`}
          style={{
            background: signalTheme.gradient,
            borderColor: signalTheme.border,
            boxShadow: `0 -12px 34px ${signalTheme.glow}`,
          }}
          aria-hidden={!showSignal}
        >
          <button
            type="button"
            className="mobile-sheet-handle"
            onPointerDown={onSheetDragStart}
            onPointerUp={onSheetDragEnd}
            onTouchStart={onSheetDragStart}
            onTouchEnd={onSheetDragEnd}
            onClick={() => setSheetExpanded((prev) => !prev)}
            aria-label="Expand signal panel"
          >
            <span />
          </button>

          <div className="mobile-sheet-head">
            <div>
              <p>{selectedSymbol}</p>
              <h3 style={{ color: signalTheme.text }}>{signal}</h3>
            </div>
            <div className="mobile-sheet-confidence">
              <span>Confidence</span>
              <strong>{confidence}%</strong>
            </div>
          </div>

          <div className="mobile-sheet-confidence-track">
            <div className="mobile-sheet-confidence-fill" style={{ width: `${confidence}%`, background: signalTheme.confidence }} />
          </div>

          <div className="mobile-sheet-grid">
            <div>
              <label>Entry</label>
              <strong>₹{price}</strong>
            </div>
            <div>
              <label>Target</label>
              <strong className="up">₹{target}</strong>
            </div>
            <div>
              <label>Stop Loss</label>
              <strong className="down">₹{stopLoss}</strong>
            </div>
          </div>

          {sheetExpanded && (
            <p className="mobile-sheet-reasoning">
              {currentSignal?.explanation || 'Signal engine combines momentum and trend factors for this setup.'}
            </p>
          )}
        </section>
      )}

      <nav className="mobile-premium-nav" aria-label="Bottom navigation">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={activeTab === tab.id ? 'active' : ''}
            onClick={() => onTabSelect(tab.id)}
          >
            <span className="icon" aria-hidden="true">{tab.icon}</span>
            <span className="label">{tab.label}</span>
          </button>
        ))}

        <div className={`mobile-nav-status ${wsStatus}`}>
          <span className="dot" />
        </div>
      </nav>
    </div>
  );
}
