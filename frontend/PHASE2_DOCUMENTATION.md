# StockAI-Pro Frontend - Phase 2 Documentation

## Overview

Phase 2 implements the core state management and API integration layer for StockAI-Pro frontend using Zustand stores and TypeScript-based API modules.

## Architecture

### 1. Type System (`src/store/types.ts`)

Complete TypeScript interfaces for the entire application:

- **User & Auth**: `User`, `Settings`, `AuthResponse`
- **Stock & Market**: `Stock`, `PriceData`, `OHLCV`, `MarketStatus`
- **Signals**: `Signal`, `SignalAction`, `SignalFilter`, `Timeframe`
- **Portfolio**: `Portfolio`, `Position`
- **UI**: `Notification`, `NotificationType`
- **API**: `ApiResponse`, `PaginatedResponse`, `WatchlistItem`

### 2. Zustand Stores

All stores are in `src/store/` and use TypeScript for type safety.

#### **authStore.ts**

Manages authentication state and tokens.

```typescript
import { useAuthStore } from '@/store';

// In your component:
const { user, isAuthenticated, login, logout } = useAuthStore();

// Login
useAuthStore.getState().login(accessToken, refreshToken, userData);

// Logout
useAuthStore.getState().logout();

// Check auth status
if (isAuthenticated) {
  console.log('User:', user);
}
```

**Store State:**
- `user`: Current authenticated user or null
- `accessToken`: JWT access token
- `refreshToken`: Refresh token for re-authentication
- `isLoading`: Loading state for auth operations
- `error`: Error message if authentication fails
- `isAuthenticated`: Boolean flag for auth status

#### **priceStore.ts**

Real-time stock price management using Map for O(1) lookups.

```typescript
import { usePriceStore } from '@/store';

// Update single price
usePriceStore.getState().updatePrice('AAPL', {
  symbol: 'AAPL',
  price: 150.25,
  change: 2.5,
  changePercent: 1.69,
  high: 151.0,
  low: 149.5,
  volume: 50000000,
  timestamp: Date.now(),
});

// Update multiple prices
const pricesMap = new Map([
  ['AAPL', priceData1],
  ['GOOGL', priceData2],
]);
usePriceStore.getState().updatePrices(pricesMap);

// Get price
const price = usePriceStore.getState().getPrice('AAPL');

// Get all prices as array
const allPrices = usePriceStore.getState().getPrices();
```

**Store State:**
- `prices`: Map<symbol, PriceData> for O(1) lookups

#### **signalStore.ts**

Trading signals management with filtering.

```typescript
import { useSignalStore } from '@/store';

// Add signals
useSignalStore.getState().setSignals(signalsArray);

// Add single signal
useSignalStore.getState().addSignal(newSignal);

// Filter signals
useSignalStore.getState().setFilter('buy');
const buySignals = useSignalStore.getState().getFilteredSignals();

// Get latest signals (first 10)
const latest = useSignalStore.getState().latestSignals;
```

**Store State:**
- `signals`: Array of all signals
- `latestSignals`: Most recent 10 signals
- `filter`: Current filter ('buy' | 'sell' | 'hold' | 'all')

#### **uiStore.ts**

UI state management with localStorage persistence.

```typescript
import { useUIStore } from '@/store';

// Toggle sidebar
useUIStore.getState().toggleSidebar();

// Add notification (auto-dismisses after duration)
useUIStore.getState().addNotification('Trade executed!', 'success', 3000);

// Add persistent notification
useUIStore.getState().addNotification('System error', 'error', 0);

// Remove notification
useUIStore.getState().removeNotification(notificationId);

// Change theme (persists to localStorage)
useUIStore.getState().setTheme('light');

// Select a stock
useUIStore.getState().setSelectedSymbol('AAPL');
```

**Store State:**
- `sidebarOpen`: Sidebar visibility
- `notifications`: Array of active notifications
- `theme`: Current theme ('dark' | 'light')
- `selectedSymbol`: Currently selected stock symbol

### 3. API Modules

All API modules in `src/api/` use the configured axios instance with automatic token refresh.

#### **auth.ts**

Authentication API endpoints.

```typescript
import { authApi } from '@/api';

// Login
const response = await authApi.login('user@example.com', 'password');
// Returns: { access_token, refresh_token, user }

// Register
const response = await authApi.register('John Doe', 'john@example.com', 'password');

// Get profile
const user = await authApi.getProfile();

// Refresh token
const newToken = await authApi.refreshToken(refreshToken);

// Logout
await authApi.logout();
```

#### **stocks.ts**

Stock market data endpoints.

```typescript
import { stocksApi } from '@/api';

// Search stocks
const results = await stocksApi.searchStocks('apple');

// Get stock quote
const stock = await stocksApi.getQuote('AAPL');

// Get historical data
const ohlcv = await stocksApi.getHistory('AAPL', '1d', 100);

// Get market status
const status = await stocksApi.getMarketStatus();
```

#### **signals.ts**

Trading signals endpoints.

```typescript
import { signalsApi } from '@/api';

// Get all signals
const signals = await signalsApi.getSignals();

// Get filtered signals
const buySignals = await signalsApi.getSignals({
  action: 'BUY',
  confidence: 75,
  timeframe: '1h',
});

// Get signal history for symbol
const history = await signalsApi.getSignalHistory('AAPL');
```

#### **watchlist.ts**

Watchlist management endpoints.

```typescript
import { watchlistApi } from '@/api';

// Get watchlist
const watchlist = await watchlistApi.getWatchlist();

// Add to watchlist
const item = await watchlistApi.addToWatchlist('AAPL');

// Remove from watchlist
await watchlistApi.removeFromWatchlist('AAPL');
```

#### **portfolio.ts**

Portfolio and position management.

```typescript
import { portfolioApi } from '@/api';

// Get portfolio
const portfolio = await portfolioApi.getPortfolio();

// Add position
const position = await portfolioApi.addPosition('AAPL', 100, 150.25);

// Update position
const updated = await portfolioApi.updatePosition(positionId, 150, 150.00);

// Delete position
await portfolioApi.deletePosition(positionId);
```

#### **user.ts**

User profile and settings endpoints.

```typescript
import { userApi } from '@/api';

// Get profile
const user = await userApi.getProfile();

// Update profile
const updated = await userApi.updateProfile({
  firstName: 'John',
  lastName: 'Doe',
});

// Update settings
const newSettings = await userApi.updateSettings({
  theme: 'light',
  riskLevel: 'moderate',
});
```

## Error Handling

### API Errors

```typescript
import { stocksApi } from '@/api';

try {
  const stock = await stocksApi.getQuote('INVALID');
} catch (error) {
  if (error.response?.status === 404) {
    console.error('Stock not found');
  } else if (error.response?.status === 401) {
    // Token refresh happens automatically via axios interceptor
    console.error('Unauthorized');
  } else {
    console.error('API error:', error.message);
  }
}
```

### Store Error Handling

```typescript
import { useAuthStore } from '@/store';

const { error, setError } = useAuthStore();

if (error) {
  console.error('Auth error:', error);
  useAuthStore.getState().clearError();
}
```

## Features

### Automatic Token Refresh

The axios instance (`src/api/axios.ts`) automatically:
- Attaches JWT tokens to requests
- Refreshes expired tokens
- Queues requests during refresh
- Redirects to login on auth failure

### localStorage Persistence

Auth store persists to localStorage:
- `auth_access_token`: JWT access token
- `auth_refresh_token`: Refresh token
- `auth_user`: User object

UI store persists:
- `ui_theme`: Current theme preference

### TypeScript Support

All modules are fully typed:
- Strict parameter validation
- Return type inference
- IDE autocomplete

## Usage Example: Complete Login Flow

```typescript
import { useAuthStore, useUIStore } from '@/store';
import { authApi } from '@/api';

async function handleLogin(email: string, password: string) {
  const { setLoading, login, setError } = useAuthStore.getState();
  const { addNotification } = useUIStore.getState();

  setLoading(true);

  try {
    const response = await authApi.login(email, password);
    login(
      response.access_token,
      response.refresh_token || null,
      response.user
    );
    addNotification('Welcome back!', 'success');
  } catch (error) {
    const message = error.response?.data?.message || 'Login failed';
    setError(message);
    addNotification(message, 'error');
  } finally {
    setLoading(false);
  }
}
```

## Environment Variables

Create `.env.local` in frontend root:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

## File Structure

```
frontend/src/
├── store/                 # Zustand stores
│   ├── types.ts          # TypeScript interfaces
│   ├── authStore.ts      # Auth state
│   ├── priceStore.ts     # Price state
│   ├── signalStore.ts    # Signals state
│   ├── uiStore.ts        # UI state
│   └── index.ts          # Store exports
├── api/                  # API modules
│   ├── constants.ts      # API constants
│   ├── axios.ts          # Axios instance (existing)
│   ├── auth.ts           # Auth endpoints
│   ├── stocks.ts         # Stock endpoints
│   ├── signals.ts        # Signal endpoints
│   ├── watchlist.ts      # Watchlist endpoints
│   ├── portfolio.ts      # Portfolio endpoints
│   ├── user.ts           # User endpoints
│   └── index.ts          # API exports
```

## Integration with React Components

```typescript
import { useAuthStore } from '@/store';
import { authApi } from '@/api';

function LoginComponent() {
  const { user, isAuthenticated } = useAuthStore();
  const { setLoading, login, setError } = useAuthStore();

  if (isAuthenticated) {
    return <div>Welcome, {user?.firstName}!</div>;
  }

  return <LoginForm onSubmit={async (email, password) => {
    try {
      const response = await authApi.login(email, password);
      login(response.access_token, response.refresh_token, response.user);
    } catch (error) {
      setError(error.message);
    }
  }} />;
}
```

## Next Steps (Phase 3)

- React components using these stores
- Real-time data integration (WebSocket)
- Advanced filtering and searching
- Dashboard implementation
- Trading execution UI

## References

- [Zustand Documentation](https://github.com/pmndrs/zustand)
- [Axios Documentation](https://axios-http.com/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
