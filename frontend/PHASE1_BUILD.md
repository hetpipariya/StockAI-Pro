# StockAI-Pro Frontend - Phase 1 Build Complete ✅

## Overview
Phase 1 establishes the design system, foundation utilities, and core infrastructure for the StockAI-Pro frontend rebuild. All files use strict TypeScript and follow a modular architecture pattern.

## Files Created

### 1. **src/index.css** - Glassmorphism Design System
Complete CSS foundation with:
- **CSS Variables**: 60+ design tokens for colors, spacing, shadows, transitions
- **Glassmorphism Components**: `.glass-card`, `.glass-card-sm`, `.glass-card-lg` with blur effects
- **Typography**: Space Grotesk & JetBrains Mono fonts with complete hierarchy
- **Form Elements**: Unified styling for inputs, buttons, textareas with hover/focus states
- **Utilities**: Flex, spacing, text, animation helpers
- **Animations**: Fade, slide, pulse, glow effects
- **Responsive Design**: Mobile, tablet, desktop breakpoints
- **Accessibility**: Reduced motion preferences, dark/light theme support

**Key Features**:
- Dark-themed background with gradient (primary → secondary)
- Cyan accent color (#00d4ff) with complementary palette
- Consistent spacing scale (4px base unit)
- Smooth transitions across all interactive elements
- Z-index scale for layering (0-1070)

### 2. **src/utils/constants.ts** - Configuration Constants
TypeScript configuration hub with:

**API Configuration**:
- `API_BASE_URL`: Backend endpoint (from VITE_API_BASE_URL env var)
- `WS_URL`: WebSocket URL (from VITE_WS_URL env var)

**WebSocket Settings**:
- `WS_RECONNECT_DELAY_MS = 3000`: Initial reconnect delay
- `WS_MAX_RECONNECT_ATTEMPTS = 10`: Max attempts before giving up
- `SIGNAL_POLL_INTERVAL_MS = 30000`: Polling interval for signals

**Market Data**:
- `NSE_INDICES`: NIFTY 50, NIFTY BANK, NIFTY IT, NIFTY MIDCAP
- `TIMEFRAMES`: 8 timeframes (1m → 1M) with labels, values, and seconds
- `INDICATORS`: EMA9, EMA21, EMA50, RSI, MACD, VWAP

**Complete API Endpoints**:
- Authentication (login, logout, refresh, verify)
- User management (profile, preferences)
- Stock data (search, details, quote, historical, indicators)
- Signals (list, details, trades)
- Watchlist operations
- Portfolio management
- Alerts
- Market data

**Additional Exports**:
- `STORAGE_KEYS`: LocalStorage keys for tokens and user data
- `HTTP_STATUS`: Status codes
- `CHART_CONFIG`: Chart styling constants
- `PAGINATION`: Default page sizes
- `VALIDATION`: Input validation rules
- `RETRY_CONFIG`: Exponential backoff settings

### 3. **src/utils/formatters.ts** - Formatting Utilities
11 exported formatting functions:

1. **formatINR(value, decimals)** - ₹ currency formatting
2. **formatPrice(price)** - Fixed 2-decimal prices
3. **formatPercent(pct, decimals)** - +/- percentage signs
4. **formatVolume(volume, decimals)** - Human-readable (Cr/L/K)
5. **formatLargeINR(value, decimals)** - ₹ in Cr/L
6. **formatDate(timestamp, format)** - 'short'/'long'/'time' formats
7. **formatDateTime(timestamp)** - Date + time combined
8. **formatDuration(ms)** - Human-readable durations
9. **formatNumber(value, decimals)** - Indian numbering
10. **getChangeColor(value)** - Color class for +/-/0
11. **getStatusColor(status)** - Status color mapping

All functions include:
- TypeScript type safety
- Error handling for invalid inputs
- JSDoc examples
- Indian Numbering System support (10L = 1M)

### 4. **src/api/axios.ts** - Axios Configuration
Pre-configured HTTP client with authentication:

**Features**:
- Base URL: `API_BASE_URL` from env vars
- 30-second timeout
- Automatic JWT Bearer token injection from localStorage
- **Request Interceptor**: Attaches `Authorization: Bearer <token>` header
- **Response Interceptor**:
  - Detects 401 Unauthorized responses
  - Automatically refreshes access token using refresh token
  - Queues failed requests during refresh
  - Retries requests with new token
  - Clears auth on refresh failure and redirects to `/login`
  - Prevents multiple simultaneous refresh attempts

**Token Refresh Flow**:
1. Request fails with 401
2. Check if already refreshing (prevents race conditions)
3. Call `/api/v1/auth/refresh` with refresh token
4. Update tokens in localStorage
5. Retry original request with new token
6. Process queued requests

### 5. **src/hooks/useWebSocket.ts** - WebSocket Hook
React hook for persistent WebSocket connections:

**Hook Signature**:
```typescript
const { send, isConnected, reconnect, disconnect } = useWebSocket({
  url: string,
  onMessage?: (data: any) => void,
  onOpen?: () => void,
  onClose?: () => void,
  onError?: (error: Event) => void,
  enabled?: boolean,
})
```

**Features**:
- Automatic connection management
- Exponential backoff reconnection: `delay = 3000 * 1.5^attempts`
- Max 10 reconnection attempts (capped at 30s)
- Auth token injection from localStorage as URL query param
- Graceful cleanup on unmount
- Manual reconnect/disconnect controls
- JSON message parsing with fallback
- Connection status tracking
- Token refresh handling via storage events

**Usage Example**:
```tsx
const { send, isConnected } = useWebSocket({
  url: import.meta.env.VITE_WS_URL,
  onMessage: (data) => handleMarketData(data),
  onOpen: () => setStatus('connected'),
  enabled: true,
});

if (isConnected) {
  send({ action: 'subscribe', symbol: 'RELIANCE' });
}
```

## Design System Details

### Color Palette
| Variable | Value | Usage |
|----------|-------|-------|
| `--bg-primary` | #0a0e27 | Main background |
| `--accent-primary` | #00d4ff | Primary CTA, focus states |
| `--chart-up` | #10b981 | Bullish/Green candles |
| `--chart-down` | #ef4444 | Bearish/Red candles |
| `--text-primary` | #f0f4f8 | Main text |
| `--text-secondary` | #a0aec0 | Secondary text |

### Spacing Scale (4px base)
```
xs: 0.25rem (4px)
sm: 0.5rem (8px)
md: 1rem (16px)
lg: 1.5rem (24px)
xl: 2rem (32px)
2xl: 3rem (48px)
3xl: 4rem (64px)
```

### Glass Card Component
Three variants with different elevation:
- `.glass-card`: Standard card (md shadow)
- `.glass-card-sm`: Small card (sm shadow)
- `.glass-card-lg`: Large card (lg shadow)

All feature:
- Backdrop blur (20px)
- Semi-transparent background
- 1px border with hover effect
- Smooth transitions

## TypeScript Support

All files are written in strict TypeScript with:
- Full type annotations
- Proper interface exports
- No `any` types (except WebSocket message data)
- Generic type parameters where applicable
- Const assertions for literal types (NSE_INDICES, INDICATORS)

### Exported Types
```typescript
export type NSEIndex = 'NIFTY 50' | 'NIFTY BANK' | 'NIFTY IT' | 'NIFTY MIDCAP'
export type Indicator = 'EMA9' | 'EMA21' | 'EMA50' | 'RSI' | 'MACD' | 'VWAP'
export interface Timeframe { label, value, seconds? }
export interface UseWebSocketOptions { url, onMessage?, ... }
export interface UseWebSocketReturn { send, isConnected, reconnect, disconnect }
```

## Integration Points

### Environment Variables Required
```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/live
```

### localStorage Keys Used
- `stockai_access_token`: JWT access token
- `stockai_refresh_token`: JWT refresh token
- `stockai_user_data`: Cached user profile
- `stockai_preferences`: User preferences
- `stockai_watchlists`: Cached watchlists
- `stockai_alerts`: Cached alerts

### Required Dependencies
- `axios@^1.15.0`: HTTP client
- `react@^18.2.0`: React library
- `react-dom@^18.2.0`: React DOM

## Verification

All modules are fully importable and syntactically correct. Test file created at `src/phase1-verification.ts` demonstrates:
```
✓ Constants loaded with all exports
✓ Formatters all callable with correct returns
✓ Axios instance ready with interceptors
✓ WebSocket hook properly typed and exported
```

## Next Steps (Phase 2)

1. **Component Library**: Create reusable UI components (Button, Card, Input, etc.)
2. **Authentication Module**: Login, register, password reset flows
3. **Layout System**: Dashboard grid, header, sidebar components
4. **API Hooks**: React Query integration for data fetching
5. **State Management**: Zustand stores for global state

## File Structure
```
src/
├── index.css (New - Design System)
├── utils/
│   ├── constants.ts (New)
│   └── formatters.ts (New)
├── api/
│   └── axios.ts (New)
└── hooks/
    └── useWebSocket.ts (New)
```

---
**Status**: ✅ Phase 1 Complete - All foundation utilities ready for component development
