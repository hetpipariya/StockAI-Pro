# Phase 2 Quick Reference Guide

## 🚀 Quick Start

### Import and Use Stores

```typescript
import { useAuthStore, usePriceStore, useSignalStore, useUIStore } from '@/store';
```

### Import and Use APIs

```typescript
import { authApi, stocksApi, signalsApi, watchlistApi, portfolioApi, userApi } from '@/api';
```

## 📦 Stores at a Glance

### useAuthStore
```typescript
const { user, isAuthenticated, login, logout } = useAuthStore();
```

### usePriceStore
```typescript
const { prices, updatePrice, getPrice } = usePriceStore();
```

### useSignalStore
```typescript
const { signals, latestSignals, setFilter, getFilteredSignals } = useSignalStore();
```

### useUIStore
```typescript
const { sidebarOpen, notifications, theme, addNotification } = useUIStore();
```

## 📡 Common API Patterns

### Authentication Flow
```typescript
// 1. Login
const auth = await authApi.login(email, password);

// 2. Store tokens and user
useAuthStore.getState().login(
  auth.access_token,
  auth.refresh_token,
  auth.user
);

// 3. Use authenticated endpoints (tokens attached automatically)
const profile = await authApi.getProfile();

// 4. Logout
await authApi.logout();
useAuthStore.getState().logout();
```

### Fetch and Display Prices
```typescript
const stock = await stocksApi.getQuote('AAPL');
usePriceStore.getState().updatePrice(stock.symbol, {
  symbol: stock.symbol,
  price: stock.price,
  change: stock.change,
  changePercent: stock.changePercent,
  high: stock.high,
  low: stock.low,
  volume: stock.volume,
  timestamp: Date.now(),
});
```

### Display Signals
```typescript
const signals = await signalsApi.getSignals();
useSignalStore.getState().setSignals(signals);

// Filter by action
useSignalStore.getState().setFilter('buy');
const filtered = useSignalStore.getState().getFilteredSignals();
```

### Notifications
```typescript
useUIStore.getState().addNotification('Success!', 'success', 3000);
useUIStore.getState().addNotification('Error!', 'error');
```

## 🔑 Key Concepts

### Zustand Stores
- Lightweight state management
- No boilerplate, no providers needed
- Use `useStore.getState()` to access outside components
- All stores are TypeScript-first

### API Modules
- Exported as objects with named methods
- Automatically handle JWT tokens
- All responses are fully typed
- Automatic token refresh on 401 errors

### TypeScript Types
- All in `src/store/types.ts`
- Imported by both stores and APIs
- Full IDE autocomplete support

## 📋 Common Errors & Solutions

### "No refresh token available"
- User not properly logged in
- Tokens expired and not refreshed
- Clear localStorage and re-login

### "API not responding"
- Check `VITE_API_BASE_URL` environment variable
- Verify backend is running
- Check browser console for CORS errors

### TypeScript errors
- Import types from `src/store/types`
- Use proper type annotations
- Check IDE for type suggestions

## 🎯 Best Practices

1. **Always use `getState()` outside components**
   ```typescript
   // ✅ Good
   useAuthStore.getState().logout();
   
   // ❌ Bad (doesn't work outside React)
   const { logout } = useAuthStore();
   ```

2. **Handle errors consistently**
   ```typescript
   try {
     await apiCall();
   } catch (error) {
     useUIStore.getState().addNotification(
       error.message || 'Operation failed',
       'error'
     );
   }
   ```

3. **Use proper types**
   ```typescript
   // ✅ Good
   import { User, Stock, Signal } from '@/store/types';
   const user: User = { ... };
   
   // ❌ Bad
   const user: any = { ... };
   ```

4. **Check authentication before sensitive operations**
   ```typescript
   if (!useAuthStore.getState().isAuthenticated) {
     redirect('/login');
     return;
   }
   ```

## 📂 File Locations

- Stores: `frontend/src/store/`
- APIs: `frontend/src/api/`
- Types: `frontend/src/store/types.ts`
- Constants: `frontend/src/api/constants.ts`

## 🔌 Environment Setup

Create `.env.local` in `frontend/` root:
```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

## 📚 Full Documentation

See `PHASE2_DOCUMENTATION.md` for complete guide with:
- Architecture details
- Full API reference
- Integration examples
- Error handling patterns
- WebSocket support info

## 🚦 Status Checks

```typescript
// Check if user is logged in
if (useAuthStore.getState().isAuthenticated) {
  // User is authenticated
}

// Check if loading
if (useAuthStore.getState().isLoading) {
  // Show loading spinner
}

// Check if there are errors
if (useAuthStore.getState().error) {
  // Show error message
}

// Check market status
const status = await stocksApi.getMarketStatus();
console.log(status.status); // 'open', 'closed', etc
```

## 💾 Persistence

Automatic persistence to localStorage:
- `auth_access_token` - JWT token
- `auth_refresh_token` - Refresh token
- `auth_user` - User object
- `ui_theme` - Theme preference

These are automatically loaded on app start!
