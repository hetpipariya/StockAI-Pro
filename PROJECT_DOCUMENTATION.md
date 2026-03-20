# StockAI Pro — Complete System Documentation

> **Version:** 2.0 | **Stack:** React 18 + FastAPI 0.109 + SmartAPI (AngelOne) + SQLite/PostgreSQL + Redis  
> **Environment:** Development running on `localhost:5173` (frontend) and `localhost:8000` (backend)  
> **Last Updated:** March 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Complete System Architecture](#2-complete-system-architecture)
3. [File Structure Analysis](#3-file-structure-analysis)
4. [Frontend Deep Analysis](#4-frontend-deep-analysis)
5. [Backend Deep Analysis](#5-backend-deep-analysis)
6. [Data Pipeline](#6-data-pipeline)
7. [Signal Engine Logic](#7-signal-engine-logic)
8. [Indicator System](#8-indicator-system)
9. [UI/UX System](#9-uiux-system)
10. [Performance Optimization](#10-performance-optimization)
11. [Bugs & Fixes](#11-bugs--fixes)
12. [Security & API Handling](#12-security--api-handling)
13. [Deployment Plan](#13-deployment-plan)
14. [Future Roadmap](#14-future-roadmap)
15. [Final Conclusion](#15-final-conclusion)

---

# 1. Project Overview

## 1.1 Project Name

**StockAI Pro** — An AI-powered real-time Indian stock market trading dashboard built for the NSE (National Stock Exchange) using the AngelOne SmartAPI brokerage platform.

## 1.2 Vision and Goal

StockAI Pro is designed to bring institutional-grade market intelligence to retail traders. The central vision is to combine **real-time tick data**, **technical analysis**, **machine learning inference**, and a **professional-grade charting UI** into a single, seamless dashboard — one that a quant trader or a day trader can open in a browser and immediately start making data-driven decisions.

The system is not just a chart viewer. It is an end-to-end AI trading intelligence layer:

- **Ingests** live tick data from AngelOne broker WebSocket
- **Aggregates** ticks into 1-minute OHLCV candles in real time
- **Runs** multi-model ML ensemble inference on every candle close
- **Broadcasts** structured signals (BUY/SELL/HOLD) with confidence scores to the browser
- **Allows** conditional live order execution via SmartAPI REST when trading mode is `LIVE`
- **Records** all predictions, candles, and trades in a persistent database

## 1.3 Problem It Solves

Retail traders in India face three core problems:

1. **Information fragmentation** — Price feeds, news, indicators, and predictions exist in separate tools
2. **Signal noise** — Raw technical indicators produce many false positives with no confidence weighting
3. **Execution latency** — Manual order placement in a broker UI costs precious seconds in fast markets

StockAI Pro resolves all three:
- It consolidates live price, indicators, AI signals, market news, sentiment, and order entry into one dark-themed dashboard
- The ML ensemble (LSTM + XGBoost + rule-based scorer) assigns a `confidence` score (0–100) so only high-conviction signals (≥70) trigger toast notifications or order buttons
- The `live_executor.py` module can place orders programmatically on SmartAPI when a 15-minute candle closes with a valid signal

## 1.4 Real-World Use Case

**Day trader scenario:**  
Trader opens dashboard at 9:15 AM IST (NSE open). The backend has already authenticated with SmartAPI (TOTP-based login runs at startup). The default watchlist of 15 blue-chip NSE stocks is streaming. The frontend shows:

- Live candlestick chart for RELIANCE with EMA9/EMA15 overlay
- Signal panel showing `BUY | Confidence: 82% | Target: ₹2,545 | SL: ₹2,488`
- A green pulsing "Action Order" button in the navbar
- Real-time tick updates via WebSocket every few hundred milliseconds

The trader clicks "Action Order", reviews the pre-filled order panel (quantity, target, stop loss auto-populated from the signal), and submits. The backend places the order via `SmartAPIConnector.place_order()`.

## 1.5 Target Users

- **Intraday day traders** on NSE who trade Nifty 50 or large-cap stocks
- **Algo-assisted traders** who want AI signal confirmation before manual order entry
- **Retail quantitative analysts** studying ML-based signal generation
- **Developers** building production-grade fintech dashboards as reference architecture

---

# 2. Complete System Architecture

## 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                   BROWSER (React 18)                │
│  DesktopLayout / MobileLayout                       │
│    LeftPanel  |  ChartSection  |  RightPanel        │
│    useTradingEngine() — central state hook          │
│    useWebsocket() — WS client                       │
└──────────┬─────────────────────────┬────────────────┘
           │ REST (fetch)            │ WebSocket /live
           ▼                         ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Backend (server.py)            │
│  ┌──────────────────┐  ┌──────────────────────────┐│
│  │  REST Routers    │  │  /live WebSocket Endpoint ││
│  │  /api/v1/market  │  │  relay.py broadcast       ││
│  │  /api/v1/predict │  │  tick / candle / status   ││
│  │  /api/v1/predict │  └──────────────────────────┘│
│  │  /api/v1/auth    │                               │
│  │  /api/v1/trading │  ┌──────────────────────────┐│
│  │  /api/v1/backtest│  │     APScheduler (cron)   ││
│  └──────────────────┘  │  regen_token every 8:30  ││
│                         │  refresh_instruments 8:00 ││
│  ┌──────────────────┐   │  prewarm_predictions 15m ││
│  │  Inference Layer │   │  auto_start_ws market hr ││
│  │  runner.py       │   │  sync_broker_positions   ││
│  │  ModelEnsemble   │   └──────────────────────────┘│
│  │  feature_eng.py  │                               │
│  └──────────────────┘                               │
│                                                     │
│  ┌──────────────────┐  ┌───────────────────────────┐│
│  │  Services Layer  │  │  Trading Layer            ││
│  │  indicators.py   │  │  live_executor.py         ││
│  │  candle_store.py │  │  risk_manager.py          ││
│  │  db.py           │  │  candle_builder.py        ││
│  │  redis_client.py │  │  trading_state.py         ││
│  └──────────────────┘  └───────────────────────────┘│
└────────────────┬──────────────────────────────────┬─┘
                 │                                  │
    ┌────────────▼──────────┐         ┌────────────▼──────┐
    │   AngelOne SmartAPI   │         │  Redis (cache)    │
    │  REST + WebSocket     │         │  SQLite / Postgres │
    │  Tick data + Orders   │         │  (persistence)     │
    └───────────────────────┘         └────────────────────┘
```

## 2.2 Frontend Structure (React + Vite + Tailwind)

The frontend is a **Vite-powered React 18 SPA** with Tailwind CSS for styling and Framer Motion for animations. It uses:

- **`lightweight-charts` v4** (from TradingView) for the candlestick and indicator chart
- **`framer-motion`** for modal animations, toast slides, and panel transitions
- **`react-router-dom` v7** for routing (`/` → Dashboard, `/news` → NewsPage)
- A single custom hook `useTradingEngine` that acts as the global state machine

There is **no Redux, Zustand, or Context API for market data**. All trading state — OHLCV candles, snapshot, prediction, indicators, signals, loading — lives in `useTradingEngine()` and is passed down as props. This is a deliberate, performance-conscious choice.

## 2.3 Backend Structure (FastAPI)

The backend is a **FastAPI 0.109 ASGI server** running under `uvicorn` with `uvloop` for high-throughput async I/O. Startup is managed by the `@asynccontextmanager lifespan` pattern (FastAPI 0.109+).

Key architectural decisions:
- **Singleton SmartAPIConnector** — Only one instance ever exists; thread-safe with `threading.Lock`
- **Thread-bridge pattern** — SmartAPI WebSocket runs in a dedicated daemon thread; completed candles are scheduled onto the asyncio event loop via `asyncio.run_coroutine_threadsafe()`
- **APScheduler** — Cron jobs handle token refresh, instrument reload, prediction pre-warming, and broker position sync

## 2.4 WebSocket Architecture (Two-Level)

There are two distinct WebSocket layers:

**Level 1 — SmartAPI WS (Backend → AngelOne)**
- `SmartAPIConnector.start_ws()` launches a daemon thread running `SmartWebSocketV2`
- On each tick: token → symbol resolution → `tick_aggregator.process_tick()` → 1m candle aggregation → broadcast to frontend clients

**Level 2 — Frontend WS (Browser → Backend `/live`)**
- `useWebsocket.js` connects to `ws://localhost:8000/live` (dev) or `wss://domain/live` (prod)
- Backend `websocket_live()` endpoint registers each browser as a client in `relay.py`
- `broadcast_tick()`, `broadcast_candle()` push JSON messages to all registered clients
- Heartbeat ping every 30 seconds keeps the connection alive through proxies

## 2.5 Data Flow — Step by Step

```
AngelOne Market → SmartAPI WS → _on_smartapi_tick() callback
    │
    ├─► token lookup via instrument_master
    ├─► tick_aggregator.process_tick(symbol, ltp, vol)
    │       └─► builds rolling 1m OHLCV candle
    │           └─► if candle complete → broadcast_candle() + _persist_completed_candle()
    │
    ├─► broadcast_tick() → relay.py → ALL connected /live WebSocket clients
    │       └─► frontend useTradingEngine: WS message → setSnapshot() + setOhlcv() update
    │
    ├─► candle_builder_15m.process_tick() → 15m candle aggregation
    │       └─► if 15m candle complete → _run_live_executor(symbol)
    │               └─► live_executor.on_candle_complete() → ML predict → place order if signal≥70
    │
    └─► live_executor.check_exits(symbol, ltp) → exit open positions at SL/Target
```

REST polling supplements WebSocket:
```
Frontend (every 15s via setInterval):
  fetch /api/v1/market/history?symbol=X&interval=1m&limit=500
  fetch /api/v1/market/snapshot?symbol=X
  fetch /api/v1/predict?symbol=X&horizon=15m
  fetch /api/v1/market/status
  ↓
All 4 fetches run in parallel via Promise.all()
  ↓
validateAndCleanOHLCV() → spike removal + gap fill + deduplication
  ↓
setOhlcv() → temporal merge with existing data (Map-based dedup by timestamp)
```

---

# 3. File Structure Analysis

## 3.1 Root Level

```
stockai-pro/
├── .env                    # Root env (shared secrets)
├── .env.example            # Template for onboarding
├── .gitignore
├── docker-compose.yml      # Full stack: db, redis, backend, frontend, nginx, prometheus, grafana
├── pyrightconfig.json      # Python type-checker config
├── test_predict.py         # Root-level quick prediction smoke test
├── backend/                # FastAPI Python backend
├── frontend/               # React/Vite frontend
├── experiments/            # Jupyter notebooks and research scripts
├── infra/                  # Terraform/cloud infra configs
├── logs/                   # Application log files
├── models/                 # Serialized ML model files (.pkl, .joblib)
├── nginx/                  # Nginx reverse proxy config
└── prometheus/             # Prometheus scrape config
```

**`docker-compose.yml`** orchestrates 7 services: `db` (PostgreSQL 15), `redis` (Redis 7), `backend`, `frontend`, `nginx`, `prometheus`, `grafana`. The backend waits for DB and Redis health checks before starting. Grafana points to Prometheus as a datasource for backend metrics exposed by `prometheus-fastapi-instrumentator`.

## 3.2 Backend Structure

```
backend/
├── Dockerfile              # Python 3.11 slim; pip install; uvicorn entrypoint
├── requirements.txt        # 30 packages: FastAPI, SmartAPI, scikit-learn, XGBoost, etc.
├── alembic/                # DB migrations (alembic upgrade head)
├── alembic.ini             # Points to DATABASE_URL env var
├── stockai.db              # SQLite dev database (~4.5MB of candle/prediction data)
├── app/
│   ├── __init__.py
│   ├── config.py           # Reads .env: API keys, JWT secret, trading mode, exchange
│   ├── main.py             # Alternative entry point (minimal)
│   ├── server.py           # PRIMARY app entry: lifespan, routers, WS endpoint, scheduler
│   ├── connectors/
│   │   ├── __init__.py     # Re-exports SmartAPIConnector, get_symbol_token
│   │   └── smartapi_connector.py  # Full SmartAPI REST+WS connector (608 lines)
│   ├── routes/
│   │   ├── auth.py         # JWT login/logout; /api/v1/auth/login, /token
│   │   ├── market.py       # /api/v1/market/history, /snapshot, /status, /top-symbols
│   │   ├── predict.py      # /api/v1/predict — calls inference runner
│   │   ├── indicators.py   # /api/v1/indicators — batch indicator computation
│   │   ├── trading.py      # /api/v1/trading — positions, orders, PnL, mode toggle
│   │   ├── backtest.py     # /api/v1/backtest — historical strategy simulation
│   │   ├── news.py         # /api/v1/news — NewsAPI integration
│   │   ├── sentiment.py    # /api/v1/sentiment
│   │   ├── symbols.py      # /api/v1/symbols/search
│   │   └── order_proxy.py  # /api/v1/orders — proxies to SmartAPI order placement
│   ├── services/
│   │   ├── data_pipeline.py    # ML training pipeline: validate→download→feature_eng (471 lines)
│   │   ├── indicators.py       # IndicatorEngine class: 20+ indicators (266 lines)
│   │   ├── candle_store.py     # Async DB CRUD for OHLCV candles
│   │   ├── db.py               # SQLAlchemy async engine, ORM models, init_db()
│   │   ├── instrument_master.py # AngelOne ScripMaster loader: token↔symbol resolution
│   │   ├── market_state.py     # is_market_open() — IST timezone 9:15–15:30 Mon-Fri
│   │   ├── redis_client.py     # Async Redis: get/set cache, session token storage
│   │   ├── tick_aggregator.py  # In-memory 1m OHLCV builder from raw ticks
│   │   └── ticker_map.py       # TICKERS, TICKER_NAMES, WATCHLIST lists (100 NSE stocks)
│   ├── inference/
│   │   ├── runner.py           # predict_symbol() → PredictionResult dataclass
│   │   ├── models.py           # ModelEnsemble: LSTM + XGBoost + rule-based scorers
│   │   ├── feature_engineering.py # Feature extraction from OHLCV for ML models
│   │   ├── features.py         # extract_features(), get_latest_sequence(), get_latest_tabular()
│   │   ├── train_models.py     # Training script: builds and saves models to /models
│   │   └── model_client.py     # Thin wrapper for model file loading
│   ├── trading/
│   │   ├── live_executor.py    # On 15m candle close: predict → risk check → place order
│   │   ├── risk_manager.py     # Max drawdown, position sizing, daily loss limits
│   │   ├── candle_builder.py   # 15m candle aggregator (mirrors tick_aggregator for 15m)
│   │   ├── trading_state.py    # Persists/restores positions, PnL, risk state from DB
│   │   └── trade_logger.py     # Structured JSON trade event logging to files
│   ├── websocket/
│   │   └── relay.py            # register_client, unregister_client, broadcast_*()
│   └── cache/
│       ├── raw_data/           # OHLCV CSV cache per ticker (used by data_pipeline.py)
│       └── features/           # Feature CSV cache per ticker (used by train_models.py)
├── models/                     # Serialized .pkl / .joblib ML model files
└── tests/                      # pytest test suite
```

## 3.3 Frontend Structure

```
frontend/
├── index.html              # Vite entry HTML; mounts <div id="root">
├── package.json            # React 18, lightweight-charts v4, framer-motion, react-router-dom v7
├── vite.config.js          # Proxy: /api/v1 → localhost:8000, /ws → ws://localhost:8000
├── tailwind.config.js      # Dark theme; custom colors: teal-400, emerald-500, slate-*
├── postcss.config.js       # Tailwind + Autoprefixer
├── Dockerfile              # Multi-stage: npm build → nginx serve
├── nginx.conf              # SPA routing: try_files $uri /index.html
└── src/
    ├── main.jsx            # ReactDOM.createRoot; wraps with <AuthProvider> + <BrowserRouter>
    ├── App.jsx             # Route "/" → Dashboard (auth guard + responsive switch); "/news" → NewsPage
    ├── index.css           # Global styles: scrollbar, animations, glassmorphism utilities
    ├── context/
    │   └── AuthContext.jsx # JWT auth state: login(), logout(), token, user
    ├── hooks/
    │   ├── useTradingEngine.jsx  # CORE: all market state, fetching, WS integration (469 lines)
    │   └── useWebsocket.js       # WS connection manager: auto-reconnect, message buffer
    ├── layouts/
    │   ├── DesktopLayout.jsx     # 3-panel grid: LeftPanel + ChartSection + RightPanel (150 lines)
    │   ├── MobileLayout.jsx      # Tab-based mobile view: chart/signal/watchlist/intel tabs
    │   ├── LeftPanel.jsx         # Watchlist + quick-order trigger
    │   ├── ChartSection.jsx      # Chart + ChartToolbar + IndicatorConclusionStrip
    │   └── RightPanel.jsx        # Prediction card + indicators panel + signal panel
    ├── pages/
    │   └── NewsPage/
    │       └── NewsPage.jsx      # Full-page news feed from /api/v1/news
    ├── components/
    │   ├── TradingChart/         # lightweight-charts candlestick renderer with overlays
    │   ├── ChartToolbar/         # Timeframe selector + indicator toggle buttons
    │   ├── SignalPanel/          # BUY/SELL/HOLD signal display with confidence bar
    │   ├── PredictionCard/       # Target price, stop loss, confidence, regime
    │   ├── IndicatorsPanel/      # Scrollable list of 20+ indicator values
    │   ├── WatchlistPanel/       # Symbol search + watchlist with live prices
    │   ├── DataStreamPanel/      # Real-time tick log display
    │   ├── IntelligencePanel/    # AI reasoning factors and explanation text
    │   ├── AiAnalysis/           # Detailed AI market analysis component
    │   ├── FloatingOrderPanel/   # Order ticket: symbol, qty, type, SL, target
    │   ├── OrderEntry/           # Form component inside FloatingOrderPanel
    │   ├── MacroBar/             # Top scrolling bar: index values, market movers
    │   ├── MarketMoversRail/     # Horizontal scroller of top-volume movers
    │   ├── SectorHeatmap/        # NSE sector performance heatmap grid
    │   ├── CorrelationMatrix/    # Stock correlation heatmap modal
    │   ├── BacktestPanel/        # Backtest config and results display
    │   ├── DecisionChartCanvas/  # Overlay decision markers on chart
    │   ├── DecisionTimeline/     # Chronological signal history timeline
    │   ├── IndicatorOrbit/       # Circular visualization of indicator states
    │   ├── IndicatorConclusionStrip/ # Summary bar: overall indicator sentiment
    │   ├── SentimentPanel/       # Market sentiment score from news/social
    │   ├── NewsPanel/            # Embedded news within dashboard
    │   ├── Header/               # App header with logo, market status, LTP
    │   ├── SignalToast/          # Bottom-right animated toast for high-confidence signals
    │   ├── MobileDrawer/         # Side drawer for mobile additional panels
    │   ├── MobileGestureLayer/   # Touch gesture handler for mobile chart interaction
    │   ├── MarketClosedPopup/    # Banner shown when NSE market is closed
    │   ├── AiVoiceButton/        # Voice announcement of AI signals
    │   ├── Auth/
    │   │   └── LoginPage.jsx     # JWT login form
    │   └── ErrorBoundary.jsx     # React ErrorBoundary preventing full-page crash
    └── utils/                    # Date formatters, number formatters, etc.
```

---

# 4. Frontend Deep Analysis

## 4.1 Entry Point and Auth Guard

**`main.jsx`** creates the React root inside `<AuthProvider>` and `<BrowserRouter>`. The `AuthContext` provides `useAuth()` to any component.

**`App.jsx`** contains two routes:
- `/` renders `Dashboard`, which is an auth-guarded component
- `/news` renders the standalone `NewsPage`

The `Dashboard` component applies the auth guard:
```jsx
if (!user || !token) return <LoginPage />
```

After authentication, it checks `window.innerWidth < 768` and re-checks on `resize` to decide between `MobileLayout` and `DesktopLayout`. Both layouts receive the full `engine` object from `useTradingEngine()`.

## 4.2 `useTradingEngine` — The Central State Machine

This 469-line hook is the brain of the frontend. It manages:

| State Variable | Type | Purpose |
|---|---|---|
| `symbol` | `string` | Active trading symbol, e.g. `"RELIANCE"` |
| `timeframe` | `string` | Chart interval: `1m`, `5m`, `15m`, `1h`, `1d` |
| `ohlcv` | `Array` | Cleaned OHLCV candle array for chart |
| `snapshot` | `Object` | Current LTP, bid, ask, volume |
| `prediction` | `Object` | AI signal, confidence, target, stop, factors |
| `indicators` | `Array` | List of active indicator IDs (from ChartToolbar) |
| `indicatorData` | `Array` | Computed indicator values per candle |
| `loading` | `boolean` | True during initial fetch |
| `activeSignal` | `Object` | High-confidence signal to show in SignalToast |
| `marketStatus` | `Object` | `{open: bool, session: string}` |

**Fetch cycle:** On `symbol` or `timeframe` change, a new `fetchToken` is minted (integer counter). All 4 parallel fetches carry this token. If a newer fetch is triggered before the old one finishes, results from the old fetch are silently discarded (`if (fetchToken !== activeFetchTokenRef.current) return`). This prevents React state corruption from race conditions.

**15-second polling:** A `setInterval` re-fires `fetchData()` every 15 seconds. Combined with WebSocket updates, this means the chart is always fresh even if the WS drops momentarily.

**Signal deduplication:** Signals with `confidence >= 70 && signal !== 'HOLD'` trigger `setActiveSignal()`, but only when the signal type changes from the previous prediction. This avoids spamming the same toast every 15 seconds.

## 4.3 `validateAndCleanOHLCV` — The Data Validation Pipeline

Every batch of raw candles from the API passes through this critical function before reaching the chart. It performs 5 operations in sequence:

**Step 1 — Deduplication by timestamp:**
```js
const seen = new Map()
rawData.forEach(d => {
  const ms = new Date(d.time).getTime()
  seen.set(ms, d)  // later entries overwrite earlier ones with same timestamp
})
```
Guarantees exactly one candle per timestamp.

**Step 2 — Timestamp-aligned gap filling:**
For gaps up to 10 missing candles, synthetic flat candles are inserted:
```js
while (fillTime < currTime) {
  validData.push({ time: ..., open: prevClose, high: prevClose,
                   low: prevClose, close: prevClose, volume: 0 })
  fillTime += tfMs
}
```
This prevents the chart from showing a visual discontinuity during lunch breaks or data gaps.

**Step 3 — Spike detection and suppression:**
A candle is classified as a spike if:
- `|close - prevClose| / prevClose > 3%` (price jump > 3%)
- OR the candle range `(high - low) > 3 × avgRange` (extreme wick relative to recent average)

Spiked candles are replaced with flat candles at `prevClose`.

**Step 4 — Structural OHLC validation:**
```js
if (high < Math.max(open, close)) high = Math.max(open, close)
if (low > Math.min(open, close)) low = Math.min(open, close)
```
Ensures mathematical correctness (high must be highest, low must be lowest).

**Step 5 — Debug summary logging:**
Logs a consolidated report to the console whenever any correction was made, helping diagnose data quality issues.

## 4.4 Layout System

### Desktop Layout (≥768px)

```
┌──────────────────────────────────────────────────────────┐
│  NAVBAR: Logo | MacroBar (scrollable) | Market Status | LTP | Buttons │
├──────────┬──────────────────────────────────┬────────────┤
│          │                                  │            │
│   LEFT   │       CHART SECTION              │   RIGHT    │
│  PANEL   │  ChartToolbar (TF + indicators)  │   PANEL    │
│          │  TradingChart (candlestick)       │            │
│ Watchlist│  IndicatorConclusionStrip         │ Prediction │
│ + search │  (below chart)                   │ SignalPanel│
│          │                                  │ Indicators │
│ Quick    │                                  │ Intelligence│
│ Order    │                                  │            │
└──────────┴──────────────────────────────────┴────────────┘
```

The layout uses `flex` with `h-screen overflow-hidden`. The center `ChartSection` is `flex-1 min-w-0` which naturally fills remaining space. Left and right panels have fixed widths.

**Floating modals** (SectorHeatmap, CorrelationMatrix, FloatingOrderPanel) render as fixed-position overlays with `z-[100]`, backdrop blur, and Framer Motion `scale` transitions.

**SignalToast** appears bottom-right via `AnimatePresence` with `slide-in-from-bottom` animation when `activeSignal` is non-null.

### Mobile Layout (<768px)

`MobileLayout.jsx` (1,222 bytes compressed) renders a **bottom tab bar** with 4 tabs:
- `chart` — Full-screen TradingChart with floating chart toolbar
- `signal` — SignalPanel + PredictionCard stacked vertically
- `watchlist` — WatchlistPanel with search
- `intel` — IntelligencePanel + SentimentPanel

`MobileGestureLayer` wraps the chart to handle touch events: pinch-to-zoom calls `chart.timeScale().setVisibleRange()` and double-tap resets the view.

## 4.5 TradingChart Component

Built on `lightweight-charts` v4 (TradingView's open-source library). It mounts a candlestick series and additional line series for each active indicator.

Key behaviors:
- On `symbol` or `timeframe` change: `series.setData(ohlcv)` is called with the fully cleaned data
- On WebSocket tick: the last candle's `close`, `high`, `low` are mutated via `series.update()`
- Indicator overlays (EMA9, EMA15, VWAP) are separate `LineSeries` instances added on demand
- The `loadMoreHistory` function is bound to the chart's `visibleRangeChange` event — when the user scrolls left to the edge of loaded data, it fetches an older batch with `?to_time=<oldest candle ISO>`

---

# 5. Backend Deep Analysis

## 5.1 Application Startup Sequence

`server.py:lifespan()` is the async context manager that executes on startup:

```
Start (uvicorn process starts)
  │
  ├── 1. asyncio event loop captured (for cross-thread scheduling)
  ├── 2. init_db() — creates SQLAlchemy tables if not exist
  ├── 3. load_trading_state() — restores open positions and PnL from DB
  ├── 4. get_redis() — connects to Redis, creates pool (gracefully skips if Redis unavailable)
  ├── 5. load_instruments() — downloads AngelOne ScripMaster JSON (~30k instruments, runs in thread pool)
  ├── 6. SmartAPIConnector().login() — TOTP-based session creation (runs in thread pool)
  ├── 7. if is_market_open(): _start_smartapi_ws(DEFAULT_WATCHLIST) — subscribes to 15 symbols
  └── 8. APScheduler starts with 5 cron jobs
```

On shutdown, the scheduler stops, WebSocket disconnects, and SmartAPI session terminates gracefully.

## 5.2 API Endpoints — Full Reference

### Market Routes (`/api/v1/market`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/market/status` | Returns `{open: bool, session: "pre/open/post/closed"}` |
| `GET` | `/api/v1/market/snapshot?symbol=X` | LTP + OHLC for symbol. Chain: SmartAPI → DB last candle → mock |
| `GET` | `/api/v1/market/history?symbol=X&interval=1m&limit=500` | OHLCV candles. Chain: Redis → DB → SmartAPI → mock |
| `GET` | `/api/v1/market/top-symbols` | Curated list of 25 NSE symbols with sector info |
| `GET` | `/api/v1/market/top-volume` | Top 5 by volume (currently curated, live in roadmap) |

**History endpoint fallback chain:**
1. Redis cache (30-second TTL for hot data)
2. SQLite/PostgreSQL via `get_candles()` (if ≥80% of requested limit available and not stale)
3. SmartAPI `getCandleData()` REST call → stored to DB → returned
4. Mock data generator (last resort when market is closed and no DB data)

### Prediction Route (`/api/v1/predict`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/predict?symbol=X&horizon=15m` | AI ensemble prediction; cacheable by `symbol:horizon:lastCandleTime` |
| `GET` | `/api/v1/predict?symbol=X&debug=true` | Same but bypasses cache and returns raw debug features |

The predict endpoint:
1. Fetches 200 candles of 1m history (to ensure enough data for all indicators)
2. Fetches current LTP from SmartAPI
3. Calls `predict_symbol(symbol, horizon, latest_ltp, ohlcv)`
4. Saves the prediction to the `predictions` DB table
5. Caches result for 30 seconds (keyed by latest candle time to avoid serving stale predictions)

### Auth Routes (`/api/v1/auth`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Username + password → JWT access token (30-day expiry) |
| `POST` | `/token` | OAuth2 alias for `/auth/login` (for Swagger UI compatibility) |
| `GET` | `/api/v1/auth/me` | Returns current user info from JWT |

JWT uses `HS256` with `JWT_SECRET` from `.env`. Tokens include `sub` (username) and `exp`.

### Trading Routes (`/api/v1/trading`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/trading/positions` | All open positions with unrealized PnL |
| `GET` | `/api/v1/trading/orders` | Order history |
| `POST` | `/api/v1/trading/mode` | Toggle `PAPER` / `LIVE` mode |
| `GET` | `/api/v1/trading/pnl` | Daily realized + unrealized PnL summary |
| `GET` | `/api/v1/trading/risk` | Current risk metrics: drawdown, exposure |

### Indicators Route (`/api/v1/indicators`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/indicators?symbol=X&interval=1m&indicators=rsi,macd,ema9` | Batch computes specified indicators on latest candles |

Fetches candle history then passes to `IndicatorEngine.compute_all()` returning a time-series of indicator values aligned with the OHLCV data.

### Other Routes

| Route | Description |
|---|---|
| `/api/v1/news?query=RELIANCE&limit=10` | NewsAPI-powered financial news |
| `/api/v1/sentiment?symbol=X` | Symbol-level sentiment score |
| `/api/v1/backtest?symbol=X&strategy=sma_cross&from=...&to=...` | Backtesting engine |
| `/api/v1/symbols/search?q=REL` | Instrument master search returning matching symbols |
| `/api/v1/orders` | Order proxy — submits orders to SmartAPI |

### Special Endpoints

| Route | Description |
|---|---|
| `GET /health` | Full system health: instruments loaded, SmartAPI connected, WS clients, market open |
| `POST /debug/start-ws` | Force-start SmartAPI WebSocket (dev/debug utility) |
| `GET /live` (WebSocket) | Browser real-time data endpoint — tick, candle_update, heartbeat, status messages |
| `GET /ws/market` (WebSocket) | Alias for `/live` |
| `GET /metrics` | Prometheus metrics (via `prometheus-fastapi-instrumentator`) |

## 5.3 `SmartAPIConnector` — Production Singleton

The `smartapi_connector.py` (608 lines) is one of the most critical files in the system. Key design decisions:

**Singleton pattern:**
```python
def __new__(cls, *args, **kwargs):
    with cls._instance_lock:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```
Only one SmartAPI session ever exists in the process, preventing duplicate login attempts.

**Rate limiting:**
All SmartAPI REST calls are gated through `_rate_limit()`:
```python
_MIN_API_INTERVAL = 0.34  # 3 calls/second maximum
```
A threading lock ensures even concurrent requests are serialized.

**Credentials** are read exclusively from `.env` via `python-dotenv`:
- `SMARTAPI_API_KEY` — AngelOne app API key
- `SMARTAPI_CLIENT_ID` — Broker client ID
- `SMARTAPI_CLIENT_PWD` — Login password
- `SMARTAPI_TOTP_SECRET` — Base32 secret for time-based OTP (pyotp)

**Login retry with exponential backoff:**
```python
for attempt in range(1, 4):
    time.sleep(2 ** attempt)  # 2s, 4s
```

**Error code handling:**
- `AG8001` / `AG8003` — Invalid Token → trigger `_refresh_session()`
- `AG8002` — Rate limit exceeded → sleep 1 second and retry

**WebSocket auto-reconnect:**
The WS runs in a `while self._ws_should_reconnect:` loop with exponential backoff (starts at 1s, max 30s). On reconnect, it refreshes the session token before re-subscribing.

## 5.4 `tick_aggregator.py` — Real-Time OHLCV Builder

Maintains an in-memory dictionary `{symbol: current_candle}`. Each call to `process_tick(symbol, ltp, vol)`:

1. Calculates the current 1-minute bucket: `current_minute = int(time.time() / 60) * 60`
2. If no candle exists for this bucket, starts a new one with `open=ltp, high=ltp, low=ltp, close=ltp`
3. If current bucket matches existing candle, updates `high`, `low`, `close`, accumulates `volume`
4. If bucket has changed (minute rolled over), marks the old candle as completed and returns it

Completed candles flow to:
- `broadcast_candle()` → pushed to all WebSocket clients as `type: candle_update`
- `_persist_completed_candle()` → saved to `candle_store` in SQLite/PostgreSQL

## 5.5 `instrument_master.py` — Token-Symbol Resolution

AngelOne identifies every instrument by a numeric `symboltoken` (e.g., RELIANCE = `2881`). The instrument master:

1. Downloads the full AngelOne ScripMaster JSON (contains ~30,000+ instruments)
2. Builds two in-memory dictionaries: `token_to_symbol` and `symbol_to_token`
3. Filters to NSE equity segment (`NSE` exchange + `-EQ` suffix)
4. Updates daily at 8:00 AM IST via scheduler

Functions used throughout the app:
- `get_token("RELIANCE")` → `"2881"`
- `get_symbol("2881")` → `"RELIANCE"`
- `search_symbols("REL")` → list of matching instruments

## 5.6 `market_state.py` — IST-Aware Market Hours

```python
def is_market_open() -> bool:
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:  # Saturday, Sunday
        return False
    market_open = now_ist.replace(hour=9, minute=15, second=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0)
    return market_open <= now_ist <= market_close
```

This is used in:
- Server startup to decide whether to start WS immediately
- `auto_start_ws` cron job (runs every minute 9-15h Mon-Fri)
- Frontend `MarketClosedPopup` component (fetches `/api/v1/market/status`)
