# Phase 2 → Phase 3: React Component Integration Examples

## Overview

These examples show how to integrate Phase 2 stores and APIs into React components for Phase 3.

## 1. Auth Context Component

```typescript
// src/hooks/useAuth.ts
import { useEffect } from 'react';
import { useAuthStore } from '@/store';
import { authApi } from '@/api';

export function useAuth() {
  const store = useAuthStore();

  useEffect(() => {
    // Check if user is already logged in
    const checkAuth = async () => {
      const token = localStorage.getItem('auth_access_token');
      if (token) {
        try {
          const user = await authApi.getProfile();
          store.login(token, localStorage.getItem('auth_refresh_token'), user);
        } catch (error) {
          store.logout();
        }
      }
    };

    checkAuth();
  }, []);

  return store;
}
```

## 2. Login Component

```typescript
// src/components/LoginForm.tsx
import { useState } from 'react';
import { useAuthStore, useUIStore } from '@/store';
import { authApi } from '@/api';
import { useNavigate } from 'react-router-dom';

export function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { isLoading, login } = useAuthStore();
  const { addNotification } = useUIStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    useAuthStore.getState().setLoading(true);

    try {
      const response = await authApi.login(email, password);
      login(response.access_token, response.refresh_token || null, response.user);
      addNotification('Login successful!', 'success');
      navigate('/dashboard');
    } catch (error: any) {
      addNotification(error.response?.data?.message || 'Login failed', 'error');
    } finally {
      useAuthStore.getState().setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        disabled={isLoading}
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        disabled={isLoading}
      />
      <button type="submit" disabled={isLoading}>
        {isLoading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  );
}
```

## 3. Stock Price Display Component

```typescript
// src/components/StockPrice.tsx
import { useEffect, useState } from 'react';
import { usePriceStore } from '@/store';
import { stocksApi } from '@/api';
import { Stock } from '@/store/types';

interface StockPriceProps {
  symbol: string;
}

export function StockPrice({ symbol }: StockPriceProps) {
  const { updatePrice, getPrice } = usePriceStore();
  const [loading, setLoading] = useState(false);
  const priceData = getPrice(symbol);

  useEffect(() => {
    const fetchPrice = async () => {
      setLoading(true);
      try {
        const stock = await stocksApi.getQuote(symbol);
        updatePrice(symbol, {
          symbol: stock.symbol,
          price: stock.price,
          change: stock.change,
          changePercent: stock.changePercent,
          high: stock.high,
          low: stock.low,
          volume: stock.volume,
          timestamp: Date.now(),
        });
      } catch (error) {
        console.error('Failed to fetch price:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchPrice();
    const interval = setInterval(fetchPrice, 5000); // Update every 5s
    return () => clearInterval(interval);
  }, [symbol]);

  if (loading && !priceData) return <div>Loading...</div>;
  if (!priceData) return <div>No data</div>;

  const isPositive = priceData.change >= 0;

  return (
    <div className="stock-price">
      <h3>{symbol}</h3>
      <p className="price">${priceData.price.toFixed(2)}</p>
      <p className={`change ${isPositive ? 'positive' : 'negative'}`}>
        {isPositive ? '+' : ''}{priceData.change.toFixed(2)} ({priceData.changePercent.toFixed(2)}%)
      </p>
      <p className="volume">Volume: {(priceData.volume / 1000000).toFixed(2)}M</p>
    </div>
  );
}
```

## 4. Signals Display Component

```typescript
// src/components/SignalsPanel.tsx
import { useEffect } from 'react';
import { useSignalStore, useUIStore } from '@/store';
import { signalsApi } from '@/api';

export function SignalsPanel() {
  const { signals, latestSignals, filter, setFilter, setSignals } = useSignalStore();
  const { addNotification } = useUIStore();

  useEffect(() => {
    const fetchSignals = async () => {
      try {
        const data = await signalsApi.getSignals();
        setSignals(data);
        addNotification(`Loaded ${data.length} signals`, 'info', 2000);
      } catch (error: any) {
        addNotification('Failed to load signals', 'error');
      }
    };

    fetchSignals();
    const interval = setInterval(fetchSignals, 10000); // Update every 10s
    return () => clearInterval(interval);
  }, []);

  const filtered = filter === 'all' 
    ? latestSignals 
    : latestSignals.filter(s => s.action.toLowerCase() === filter);

  return (
    <div className="signals-panel">
      <h3>Trading Signals</h3>
      
      <div className="filter-buttons">
        {['all', 'buy', 'sell', 'hold'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f as any)}
            className={filter === f ? 'active' : ''}
          >
            {f.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="signals-list">
        {filtered.map(signal => (
          <div key={signal.id} className={`signal signal-${signal.action.toLowerCase()}`}>
            <span className="symbol">{signal.symbol}</span>
            <span className="action">{signal.action}</span>
            <span className="confidence">{signal.confidence}%</span>
            <span className="timeframe">{signal.timeframe}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

## 5. Portfolio Component

```typescript
// src/components/Portfolio.tsx
import { useEffect, useState } from 'react';
import { useUIStore } from '@/store';
import { portfolioApi } from '@/api';
import { Portfolio as PortfolioType } from '@/store/types';

export function Portfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioType | null>(null);
  const [loading, setLoading] = useState(true);
  const { addNotification } = useUIStore();

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const data = await portfolioApi.getPortfolio();
        setPortfolio(data);
      } catch (error: any) {
        addNotification('Failed to load portfolio', 'error');
      } finally {
        setLoading(false);
      }
    };

    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 30000); // Update every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading portfolio...</div>;
  if (!portfolio) return <div>No portfolio data</div>;

  return (
    <div className="portfolio">
      <h2>Portfolio</h2>
      
      <div className="portfolio-summary">
        <div className="stat">
          <span className="label">Total Value</span>
          <span className="value">${portfolio.totalValue.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="label">Total Gain</span>
          <span className={`value ${portfolio.totalGain >= 0 ? 'positive' : 'negative'}`}>
            ${portfolio.totalGain.toFixed(2)} ({portfolio.totalGainPercent.toFixed(2)}%)
          </span>
        </div>
        <div className="stat">
          <span className="label">Cash</span>
          <span className="value">${portfolio.cashBalance.toFixed(2)}</span>
        </div>
      </div>

      <div className="positions">
        <h3>Positions ({portfolio.positions.length})</h3>
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Quantity</th>
              <th>Entry Price</th>
              <th>Current Price</th>
              <th>Value</th>
              <th>Gain/Loss</th>
            </tr>
          </thead>
          <tbody>
            {portfolio.positions.map(position => (
              <tr key={position.id}>
                <td>{position.symbol}</td>
                <td>{position.quantity}</td>
                <td>${position.entryPrice.toFixed(2)}</td>
                <td>${position.currentPrice.toFixed(2)}</td>
                <td>${position.currentValue.toFixed(2)}</td>
                <td className={position.unrealizedGain >= 0 ? 'positive' : 'negative'}>
                  ${position.unrealizedGain.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

## 6. Notification System Component

```typescript
// src/components/NotificationCenter.tsx
import { useUIStore } from '@/store';

export function NotificationCenter() {
  const { notifications, removeNotification } = useUIStore();

  return (
    <div className="notification-center">
      {notifications.map(notification => (
        <div
          key={notification.id}
          className={`notification notification-${notification.type}`}
          role="alert"
        >
          <div className="notification-content">
            <p>{notification.message}</p>
          </div>
          <button
            onClick={() => removeNotification(notification.id)}
            aria-label="Close notification"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
```

## 7. Watchlist Component

```typescript
// src/components/Watchlist.tsx
import { useEffect, useState } from 'react';
import { watchlistApi, stocksApi } from '@/api';
import { useUIStore } from '@/store';
import { Stock } from '@/store/types';

export function Watchlist() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const { addNotification } = useUIStore();

  useEffect(() => {
    const fetchWatchlist = async () => {
      try {
        const data = await watchlistApi.getWatchlist();
        setStocks(data);
      } catch (error: any) {
        addNotification('Failed to load watchlist', 'error');
      } finally {
        setLoading(false);
      }
    };

    fetchWatchlist();
  }, []);

  const handleRemove = async (symbol: string) => {
    try {
      await watchlistApi.removeFromWatchlist(symbol);
      setStocks(stocks.filter(s => s.symbol !== symbol));
      addNotification(`${symbol} removed from watchlist`, 'success');
    } catch (error: any) {
      addNotification('Failed to remove from watchlist', 'error');
    }
  };

  if (loading) return <div>Loading watchlist...</div>;

  return (
    <div className="watchlist">
      <h3>My Watchlist ({stocks.length})</h3>
      {stocks.length === 0 ? (
        <p>No stocks in your watchlist</p>
      ) : (
        <div className="stocks-grid">
          {stocks.map(stock => (
            <div key={stock.symbol} className="stock-card">
              <h4>{stock.symbol}</h4>
              <p className="price">${stock.price.toFixed(2)}</p>
              <p className={`change ${stock.change >= 0 ? 'positive' : 'negative'}`}>
                {stock.change >= 0 ? '+' : ''}{stock.change.toFixed(2)}%
              </p>
              <button
                onClick={() => handleRemove(stock.symbol)}
                className="btn-remove"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

## 8. Theme Switcher Component

```typescript
// src/components/ThemeSwitcher.tsx
import { useUIStore } from '@/store';

export function ThemeSwitcher() {
  const { theme, setTheme } = useUIStore();

  return (
    <button
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="theme-switcher"
      aria-label="Toggle theme"
    >
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
}
```

## 9. Protected Route Component

```typescript
// src/components/ProtectedRoute.tsx
import { useAuthStore } from '@/store';
import { Navigate } from 'react-router-dom';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated } = useAuthStore();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
```

## Integration Pattern Summary

1. **Always use hooks for components**: `useAuthStore`, `useUIStore`, etc.
2. **Use `getState()` for non-React contexts**: API calls, service layers
3. **Handle loading states**: Most API calls need loading indicators
4. **Show notifications**: Use `useUIStore().addNotification()` for user feedback
5. **Persist settings**: Theme, sidebar state automatically persisted to localStorage
6. **Error handling**: Try-catch around all API calls with user feedback
7. **Auto-refresh data**: Use `useEffect` with `setInterval` for polling
8. **Type safety**: Always import types from `@/store/types`

## Next Phase Requirements

For Phase 3, create:
- Login/Register pages using LoginForm
- Dashboard with all panels
- Stock detail view using StockPrice
- Portfolio management page
- Settings/Profile page
- Layout with sidebar navigation
- Responsive design

All foundation is ready! Components will integrate seamlessly.
