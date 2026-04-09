# StockAI Pro Backend + Experiments Architecture

## 1. System Overview

StockAI Pro is a real-time intraday trading intelligence platform with two tightly-coupled domains:

- Production backend runtime: low-latency market bundle API, real-time WebSocket feed, authenticated trading workflows, and a conservative multi-engine inference core.
- Experiments and model engineering: dataset build, feature engineering, model training/versioning, and evaluation reports used to produce deployable artifacts.

Core architecture principles:

- Safety first: default to HOLD on uncertainty, data gaps, model issues, or invalid risk envelopes.
- Deterministic contracts: API payloads, prediction fields, and WebSocket messages use normalized schemas.
- Multi-layer fallbacks: live broker -> DB/cache -> mock/safe fallback to keep frontend and automations operational.
- Production observability: structured logs, health endpoints, Prometheus instrumentation, DB slow-query logging.

## 2. Production Topology

### Runtime stack

- API framework: FastAPI + async lifecycle.
- DB: PostgreSQL (primary), SQLite fallback for local/dev only.
- Cache: Redis (primary), in-memory TTL fallback.
- Broker connector: Angel One SmartAPI (REST + WS).
- Inference: scikit-learn/XGBoost artifacts + custom 12-engine fusion logic.
- Scheduling: APScheduler recurring jobs (token refresh, prediction prewarm, ws upkeep, broker sync).
- Metrics: prometheus-fastapi-instrumentator.

### Container topology

At repo root, docker-compose provisions:

- db (PostgreSQL 15)
- redis (Redis 7)
- backend (FastAPI + Alembic startup migrations for PostgreSQL)
- frontend (Vite build/runtime image)
- nginx (reverse proxy)
- prometheus
- grafana

Backend container startup behavior:

- Logs model artifacts at startup.
- Runs Alembic migration when DB is PostgreSQL.
- Starts uvicorn on app.main:app.
- Uses healthcheck against /api/health.

## 3. Repository and Folder Tree

### Backend tree (source-oriented)

```text
backend/
  alembic/
    env.py
    versions/
      b770c489ddcd_initial_schema_with_user_ids.py
      d3f90f4c2b18_enforce_user_isolation_constraints.py
      e6b9f2c4a1d0_add_query_performance_indexes.py
  app/
    main.py
    server.py
    lifespan.py
    middleware.py
    config.py
    connectors/
      smartapi_connector.py
      order_router.py
    inference/
      feature_engineering.py
      features.py
      models.py
      runner.py
      model_client.py
      quant_predictor.py
      volume_intelligence.py
      risk_position_context.py
      multi_timeframe_alignment.py
      time_intelligence.py
      liquidity_order_flow.py
      train_models.py
    routes/
      auth.py
      bundle.py
      market.py
      predict.py
      trading.py
      news.py
      sentiment.py
      backtest.py
      indicators.py
      symbols.py
      order_proxy.py
    services/
      db.py
      bundle_service.py
      candle_store.py
      redis_client.py
      scheduler.py
      market_state.py
      tick_aggregator.py
      instrument_master.py
      data_pipeline.py
      ticker_map.py
      indicators.py
    trading/
      live_executor.py
      risk_manager.py
      candle_builder.py
      user_state.py
      trading_state.py
      trade_logger.py
    websocket/
      handler.py
      relay.py
  tests/
    conftest.py
    test_auth.py
    test_security.py
    test_multi_user_isolation.py
    test_bundle_api.py
    test_bundle_e2e_flow.py
    test_prediction.py
    test_feature_engineering.py
    test_volume_intelligence.py
    test_time_intelligence.py
    test_multi_timeframe_alignment.py
    test_liquidity_order_flow.py
    test_risk_position_context.py
    test_risk_manager.py
    test_trading_engine.py
    test_websocket_feed.py
    test_product_features.py
  models/
    model.pkl
    scaler.pkl
    features.pkl
```

Notes:

- backend/app/cache/raw_data and backend/app/cache/features contain generated CSVs from pipeline jobs.
- backend/logs has date-partitioned runtime logs and data_pipeline.log.

### Experiments tree

```text
experiments/
  build_dataset.py
  train_models.py
  quant_pipeline.py
  intraday_backtest.py
  generate_nb.py
  training_template.ipynb
  data/
    raw/
    processed/
    train_data.csv
  models/
    model_vN.pkl, latest_model.json, compatibility artifacts
  reports/
    evaluation_report_vN.json
    pipeline_summary_*.json
  logs/
    pipeline_*.log
```

## 4. Backend Module Contracts

### App composition and lifecycle

- app/server.py
  - Responsibility: central FastAPI assembly and router inclusion.
  - Exposes health, API index, compatibility predict alias, WS routes.
- app/lifespan.py
  - Responsibility: startup/shutdown orchestration.
  - Startup sequence: DB init/check -> trading state restore -> Redis init -> instrument load -> SmartAPI init/login/ws -> model warmup -> scheduler start.
  - Shutdown sequence: scheduler stop -> ws stop -> broker session termination.
- app/middleware.py
  - Responsibility: production envelope normalization, request timeout, rate limiting, login throttling, CORS-safe error responses.
  - Contract: normalizes most API responses into success/data/error/timestamp envelope.

### Configuration and guards

- app/config.py
  - Strict JWT secret policy in production.
  - DATABASE_URL normalization/sanitization and async driver shaping.
  - Production hard-stop for SQLite.
  - Centralized risk and trading safety knobs.

### Data and persistence

- app/services/db.py
  - SQLAlchemy models and engine/session setup.
  - User-isolated tables: users, orders, positions, trade_logs, predictions.
  - Candle uniqueness: (symbol, timeframe, timestamp).
  - Slow-query logging hooks on sync + async engines.
- app/services/candle_store.py
  - Bulk upsert candles (PostgreSQL on-conflict; SQLite fallback).
  - Read latest/history with symbol/timeframe constraints.
- app/services/redis_client.py
  - get_cache/set_cache/delete_cache and SmartAPI session token store.
  - Transparent in-memory fallback when Redis unavailable.

### Market/bundle orchestration

- app/services/bundle_service.py
  - Main orchestration contract for low-latency consolidated bundle.
  - Parallel tasks: history + snapshot + market status, then indicators + prediction.
  - Strict timeout wrappers and deterministic fallbacks.
  - Prediction persistence to predictions table.
  - Cache profile: snapshot TTL 3s, history TTL 10s, prediction TTL 5s.

### Realtime infrastructure

- app/websocket/handler.py
  - Authenticated ws endpoint (/ws and legacy /live), subscribe/unsubscribe/ping handling.
  - SmartAPI tick normalization and guardrails against paise/price anomalies.
  - Tick -> candle completion -> DB persist -> signal update broadcast.
  - Reconnect logic with exponential backoff + circuit breaker.
- app/websocket/relay.py
  - Per-client subscriptions with user isolation.
  - Throttled and deduplicated tick broadcasting.
  - Broadcast contracts: tick, candle_update, signal_update, status.

### Trading subsystem

- app/trading/user_state.py
  - Per-user in-memory isolated risk/capital/positions state.
- app/trading/live_executor.py
  - Signal evaluation and execution orchestration.
  - Uses canonical compute_features(..., include_legacy=True) for runtime parity.
- app/connectors/order_router.py
  - Order state machine: PENDING_CONFIRMATION -> CONFIRMED -> PENDING_EXECUTION -> FILLED/FAILED/REJECTED.
  - PAPER/LIVE execution modes with safety gates and idempotency checks.
- app/trading/risk_manager.py
  - Position sizing and hard risk limits (max trades/day, max positions, daily loss halt, min balance).
- app/trading/trade_logger.py
  - Dual sink audit trail: JSONL + DB trade_logs.

## 5. Inference Engines (12-Engine Stack)

Inference is implemented in app/inference/models.py with canonical features from feature_engineering.py (FEATURE_VERSION v2.0, 19 base columns) plus derived/legacy compatibility columns.

Engine inventory:

1. Momentum engine
- Inputs: returns, RSI, MACD relation, Bollinger position, OBV dynamics, momentum terms, ML probability.
- Output: momentum_score (0-1), momentum label, signed decomposition.

2. Trend engine
- Inputs: EMA stack/slope/distance, resampled MTF EMAs.
- Output: trend_score, ema_structure, mtf_alignment/direction/timeframe map.

3. Volatility engine
- Inputs: ATR expansion, BB width ratio, historical vol, range ratio.
- Output: volatility_score, volatility_state, breakout_detected.

4. Volume engine
- Inputs: volume_ratio, spikes, VWAP deviation, OBV slope/divergence, volume trend.
- Output: volume_score and sizing hints.

5. Price action engine
- Inputs: candle body/wicks, engulfing, doji, streaks.
- Output: price_action_score, candle_type, engulfing/doji metadata.

6. Market structure engine
- Inputs: swing highs/lows, clustered S/R, breakout geometry.
- Output: structure_score, structure state, support/resistance distances.

7. Regime engine
- Inputs: range_or_trend, volatility state, MTF alignment, trend+structure.
- Output: regime_score, regime_state, public regime label.

8. Time intelligence engine
- Inputs: IST session, day-of-week bias, intraday bucket, expiry type.
- Output: time_score, confirmation_threshold, position_size_factor.

9. Liquidity/order-flow proxy engine
- Inputs: price impact per volume, jump, gap continuation/rejection, sweep patterns.
- Output: liquidity_score, jump/gap/sweep flags, flow_state.

10. Risk/position context engine
- Inputs: ATR, entry, target, capital, risk-per-trade, volatility state.
- Output: stop_loss, RR, position_size, risk_filter_fail, position_size_factor.

11. Multi-timeframe alignment engine
- Inputs: 1m/5m/15m/1h direction consensus and strength.
- Output: mtf_alignment, mtf_score, direction, htf_confirmed, ltf_entry_confirmed.

12. Derived AI/meta engine
- Inputs: normalized and z-score derived features + ML certainty/alignment/coherence.
- Output: ai_score and ai_label.

## 6. Final Fusion and Decision Logic

### Weighted fusion

Final fusion combines directionalized engine scores:

- trend_score: 0.15
- momentum_score: 0.10
- volatility_score: 0.10
- volume_score: 0.10
- price_action_score: 0.10
- structure_score: 0.10
- mtf_score: 0.10
- regime_score: 0.08
- liquidity_score: 0.05
- time_score: 0.05
- risk_score: 0.04
- ai_score: 0.03

Formula:

- fusion_score = sum(weight_i * score_i), clipped to [0, 1]

### Hard HOLD filters

The predictor forces HOLD when any hard gate fails, including:

- Missing/insufficient data
- Low volume or inconsistent volume confirmation
- MTF misalignment or conflicting timeframes
- Range-bound/unclear structure context
- Doji/weak price-action confirmations
- Liquidity trap conditions (gap rejection, jump without support)
- RR below threshold (rr < 1.5)
- Off-hours and weak session-specific confirmation

### Final signal gates

- BUY if:
  - No hold filters
  - fusion_score > 0.70
  - trend_score > 0.60
  - MTF aligned bullish
  - breakout confirmation or support-bounce confirmation
- SELL if:
  - No hold filters
  - fusion_score < 0.30
  - trend_score < 0.40
  - MTF aligned bearish
- Else HOLD

### Post-decision safety

- If signal is BUY/SELL and confidence < 0.60 -> force HOLD.
- If BUY envelope invalid (target <= ltp or stop >= ltp) -> HOLD.
- If SELL envelope invalid (target >= ltp or stop <= ltp) -> HOLD.
- HOLD response clamps confidence under 0.60 and resets conservative target/stop envelope.

## 7. Runtime Data Flows

### Bundle API flow (primary frontend path)

1. Request reaches /api/bundle/{symbol}.
2. Route wraps call with 8s guard and normalized success/error envelope.
3. Service executes in parallel:
   - get_history
   - get_snapshot
   - get_market_status
4. Then in parallel:
   - get_indicators
   - get_prediction
5. Applies fallback logic for low-candle validity and timeout scenarios.
6. Returns consolidated payload with latency_ms and data-source tags.

### Market data flow

- SmartAPI WS tick -> normalize price -> tick_aggregator 1m candle.
- Completed candle -> broadcast candle_update + persist to DB + recompute prediction.
- signal_update payload broadcast to subscribed clients.

### Trading execution flow

1. Authenticated user requests /api/v1/trading/signal or /execute.
2. Executor evaluates signal against 15m candle history and technical + ML rules.
3. Risk manager computes allowable size and risk envelope.
4. Order router stages order and confirms/executions by mode.
5. Position and audit state sync to DB and trade logs.

### Experiments MLOps flow

1. experiments/build_dataset.py builds categorized intraday dataset and train_data.csv.
2. experiments/train_models.py trains ensemble and exports model/scaler/features.
3. experiments/quant_pipeline.py runs full pipeline with:
   - data ingestion
   - feature build
   - temporal leakage checks
   - iterative model search
   - versioned artifacts and reports
4. Backend inference loads artifacts from MODEL_PATH/models and serves runtime predictions.

## 8. API and WebSocket Contracts

### Core production endpoints

- GET /api/bundle/{symbol}
  - Query: interval, limit, horizon
  - Returns: history, snapshot, prediction, indicators, market_status, latency
- GET /api/health
- GET /api/health/detailed
- GET /api/system/db-ping

### Auth endpoints

- POST /api/auth/signup
- POST /api/auth/login
- POST /api/auth/token (OAuth2 form)
- GET /api/auth/me
- POST /api/auth/refresh
- POST /api/auth/logout
- Compatibility aliases under /api and /api/v1/auth

### Trading endpoints (JWT required)

- GET /api/v1/trading/status
- GET /api/v1/trading/signal
- POST /api/v1/trading/execute
- GET /api/v1/trading/positions
- GET /api/v1/trading/orders
- GET /api/v1/trading/journal
- GET /api/v1/trading/logs
- GET /api/v1/trading/pnl
- GET /api/v1/trading/risk
- GET /api/v1/trading/safety
- POST /api/v1/trading/confirm/{order_id}
- POST /api/v1/trading/kill-switch

### Supplemental endpoints

- /api/market/status and curated symbol/volume endpoints
- Deprecated (kept for compatibility): /api/market/history, /api/market/snapshot, /api/predict
- /api/v1/news, /api/v1/sentiment, /api/v1/backtest
- /api/symbols/search, /api/symbols/all

### WebSocket protocol

- Endpoint: /ws?token=<jwt> (legacy alias: /live)
- Client actions:
  - subscribe with symbols list
  - unsubscribe with symbols list
  - ping/pong
- Server message types:
  - connected
  - subscribed/unsubscribed
  - tick
  - candle_update
  - signal_update
  - heartbeat
  - status

## 9. Test Strategy and Quality Gates

### Test architecture

- Framework: pytest + anyio for async routes.
- DB strategy: in-memory SQLite via overridden FastAPI dependency.
- Isolation controls:
  - middleware rate-limit state reset
  - trading_manager state reset
  - deterministic fixtures for bullish/bearish/short OHLCV

### Coverage dimensions

- Authentication and token lifecycle
- Security hardening (tampered/expired token, brute-force, injection payloads)
- Multi-user isolation across trading and data access
- Inference contract and decision behavior
- Individual engines:
  - volume intelligence
  - time intelligence
  - MTF alignment
  - liquidity/order-flow
  - risk/position context
- Bundle API contract, timeout handling, and e2e flow invariants
- WebSocket feed normalization and mock fallback behavior
- Trading risk manager and order lifecycle

### Current quality signal

- Full backend regression baseline: 167 passed, 0 failed.

## 10. Scaling Strategy, Operations, and Current Limitations

### What scales well today

- Stateless REST paths with short cache TTLs.
- DB-backed candles/orders/positions with indexed access paths.
- Graceful degraded mode when Redis or SmartAPI are unavailable.

### Key current bottlenecks/risks

- In-process singleton state:
  - SmartAPI connector singleton
  - per-process websocket manager and subscriptions
  - per-process trading manager/executors
- Some trading paths use sync DB sessions, which can constrain high-concurrency async behavior.
- Monolithic inference module (models.py) is large and high-change-risk.
- Broker sync helper expects connector.get_positions; connector currently does not expose a get_positions method.
- In-memory cache fallback is node-local (not shared across replicas).

### Recommended production scale path

- Externalize realtime fanout via Redis pub/sub or Kafka (WS gateway pattern).
- Move user/trading volatile state to shared store (Redis hash/stream or DB event log).
- Split inference orchestration from model computation worker (RPC/queue) for CPU isolation.
- Add circuit metrics and SLO dashboards:
  - bundle latency p50/p95/p99
  - prediction timeout rate
  - ws reconnect frequency
  - hold-filter reason distribution
- Add canary model rollout with shadow scoring before full traffic switch.

## 11. Roadmap (Near / Mid / Long Term)

### Near term (0-4 weeks)

- Refactor inference/models.py into engine modules + fusion orchestrator class.
- Implement connector.get_positions parity for broker sync path.
- Introduce strict Pydantic response models for bundle/prediction/ws payloads.
- Add regression tests for final_hard_filters combinations and confidence envelope gates.

### Mid term (1-2 months)

- Multi-instance safe WebSocket architecture with shared subscription/state bus.
- Convert sync order-routing DB operations to fully async transaction flows.
- Add feature-store style versioning and model artifact manifest checks at startup.
- Introduce scenario replay harness from recorded candles/ticks for deterministic incident debugging.

### Long term (1-2 quarters)

- Service decomposition:
  - market data ingestion service
  - inference service
  - execution/risk service
  - API gateway service
- Real broker abstraction layer for multi-broker redundancy.
- Online monitoring for model drift and confidence calibration.
- Full CI release gates with load tests, chaos tests, and contract snapshots.

---

This document reflects the current code paths and runtime behavior in backend and experiments as of the latest validated regression state.

## 12. Deep Runtime Addendum (As-Is Technical Expansion)

### 12.1 Function Signatures (Critical Runtime Surface)

The following are the active signatures currently exposed in runtime-critical backend modules.

#### Bundle route + orchestration

```python
@router.get("/bundle/{symbol}")
async def get_bundle(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=50, le=300),
    horizon: str = Query("15m"),
):

async def _with_timeout(
    coro,
    timeout_seconds: float,
    default: Any,
    context: str,
) -> Any:

async def get_market_status() -> dict[str, Any]:

async def get_snapshot(symbol: str) -> dict[str, Any]:

async def get_history(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
) -> dict[str, Any]:

async def get_indicators(
    symbol: str,
    interval: str = "1m",
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:

async def get_prediction(
    symbol: str,
    horizon: str = "15m",
    history: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:

async def get_bundle(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    horizon: str = "15m",
) -> dict[str, Any]:
```

#### Inference entrypoints

```python
def predict_symbol(
    symbol: str,
    timeframe: str = "15m",
    latest_ltp: Optional[float] = None,
    features_df: Optional[pd.DataFrame] = None,
    ohlcv: Optional[List[Dict[str, Any]]] = None,
) -> PredictionResult:

def ensure_models_loaded(max_retries: int = 3) -> bool:

def load_models():

@staticmethod
def predict(
    symbol: str,
    ltp: float,
    features_seq: "np.ndarray",
    features_tab: "np.ndarray",
    ohlcv_df: Optional[pd.DataFrame] = None,
    debug: bool = False,
) -> Dict[str, Any]:

def compute_features(
    ohlcv_df: pd.DataFrame,
    include_legacy: bool = False,
) -> pd.DataFrame:

def validate_features(
    feature_names: list[str],
    expected: Optional[list[str]] = None,
    context: str = "",
) -> None:

def extract_features(ohlcv: List[Dict[str, Any]]) -> pd.DataFrame:

def get_latest_sequence(
    features_df: pd.DataFrame,
    sequence_length: int = 20,
) -> np.ndarray:

def get_latest_tabular(features_df: pd.DataFrame) -> np.ndarray:

def predict_signal(symbol: str) -> Dict[str, Any]:
```

#### Cache + DB storage surfaces

```python
async def get_redis() -> Optional[redis.Redis]:

async def set_cache(key: str, value: Any, ttl: int = 60) -> None:

async def get_cache(key: str) -> Optional[Any]:

async def delete_cache(key: str) -> None:

async def store_candles(symbol: str, timeframe: str, candles: list[dict]) -> int:

async def bulk_upsert_candles(candles: list[dict], session: AsyncSession) -> int:

async def get_candles(
    symbol: str,
    timeframe: str,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: int = 500,
) -> list[dict]:

async def get_latest_candle(symbol: str, timeframe: str) -> Optional[dict]:

async def get_candle_count(symbol: str, timeframe: str) -> int:
```

#### WebSocket + cross-thread dispatch surfaces

```python
def _schedule_async(coro):

def _on_smartapi_tick(msg):

def start_smartapi_ws(symbols_list: list[str]):

async def websocket_live(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
):

async def _handle_ws_connection(websocket: WebSocket, user_id: int):
```

### 12.2 Feature -> Model Pipeline (Exact Runtime Path)

This is the active backend path from raw candle data to final prediction payload in the bundle endpoint.

1. `routes/bundle.py:get_bundle` calls `bundle_service.get_bundle(...)`.
2. `bundle_service.get_bundle(...)` concurrently builds:
   - history payload (`get_history`)
   - snapshot payload (`get_snapshot`)
   - market status (`get_market_status`)
3. `bundle_service.get_prediction(...)` takes the resolved history and snapshot:
   - reads candles from `history["candles"]` / `history["data"]`
   - sanitizes via `_sanitize_candles`
   - aborts to fallback if no candles or `< MIN_CANDLES_FOR_FEATURES` (`50`)
4. Prediction execution is offloaded with timeout guard:
   - `await _with_timeout(asyncio.to_thread(predict_symbol, ...), PREDICTION_TIMEOUT_SECONDS, ...)`
5. `runner.predict_symbol(...)` constructs inference inputs:
   - converts raw OHLCV list to `ohlcv_df`
   - if `features_df is None` and candle count is sufficient, calls `extract_features(ohlcv)`
   - builds `seq = get_latest_sequence(features_df)` and `tab = get_latest_tabular(features_df)`
   - falls back to zero arrays if no feature frame exists
   - calls `ModelEnsemble.predict(symbol, base, seq, tab, ohlcv_df=ohlcv_df)`
6. `ModelEnsemble.predict(...)` computes model-serving features from `ohlcv_df`:
   - `compute_features(ohlcv_df, include_legacy=True)` from `feature_engineering.py`
   - `build_feature_vector(ohlcv_df, base_features=feature_df)` from volume intelligence path
   - `_ensure_model_feature_columns(feature_df, ohlcv_df, required_model_features)`
   - row selection: `latest = feature_df.iloc[-1]`
   - vector assembly in trained feature order:
     - `input_data = [float(latest.get(name, 0.0)) for name in required_model_features]`
   - scaling and model probability:
     - `_scaler.transform(input_arr)`
     - `_ensemble_model.predict_proba(input_scaled)[0, 1]`
7. Multi-engine fusion and risk filters run inside `ModelEnsemble.predict(...)`, then a result dictionary is returned.
8. `runner.predict_symbol(...)` wraps the dictionary into `PredictionResult`.
9. `bundle_service._normalize_prediction(...)` normalizes and enforces final bundle contract fields.
10. `bundle_service._save_prediction_record(...)` persists prediction (best effort).
11. Final normalized prediction is cached (`pred:v3:*`) and returned as `bundle["prediction"]`.

Current noteworthy runtime detail:

- `features_seq` and `features_tab` are accepted by `ModelEnsemble.predict(...)` but the active implementation computes model input from `ohlcv_df` + canonical feature engineering path.

### 12.3 Async + Threading Model (Event Loop and Thread Boundaries)

#### HTTP request path

- FastAPI request handlers run on the async event loop.
- `routes/bundle.py:get_bundle` wraps service call in `asyncio.wait_for(..., timeout=8.0)`.
- `bundle_service.get_bundle(...)` uses two concurrency phases:
  - Phase A (parallel): `get_history`, `get_snapshot`, `get_market_status`
  - Phase B (parallel): `get_indicators`, `get_prediction`

#### Blocking work offloaded with `asyncio.to_thread`

Current synchronous/blocking operations moved to worker threads:

- SmartAPI connector/session/bootstrap (`_get_connector`)
- LTP fetch (`connector.get_ltp`)
- History fetch (`connector.fetch_history`)
- Indicator engine computation (`IndicatorEngine.compute_all`)
- Full prediction call (`predict_symbol`)

Each offloaded block in bundle path is wrapped by `_with_timeout(...)`, returning deterministic fallback data on timeout or exception.

#### WebSocket callback thread -> async loop handoff

- SmartAPI WS callback (`_on_smartapi_tick`) runs on connector-managed callback thread.
- Async tasks are injected into the main event loop through:
  - `_schedule_async(coro)` -> `asyncio.run_coroutine_threadsafe(coro, _event_loop)`
- Tick callback schedules async fanout/persistence tasks:
  - `broadcast_tick`
  - `broadcast_candle`
  - `_persist_completed_candle`
  - `_broadcast_signal_update`
- Reconnect loop scheduling also uses cross-thread coroutine submission:
  - `_schedule_reconnect(...)` -> `run_coroutine_threadsafe(_retry_ws_connect(...), _event_loop)`

### 12.4 Cache + Data Flow Layers (Including TTL Behavior)

#### Active cache TTL profile (bundle path)

- `HISTORY_CACHE_TTL_SECONDS = 10`
- `SNAPSHOT_CACHE_TTL_SECONDS = 3`
- `PREDICTION_CACHE_TTL_SECONDS = 5`

#### Cache key patterns in use

- Snapshot: `snap:v3:{SYMBOL}`
- History: `hist:v3:{SYMBOL}:{INTERVAL}:{LIMIT}`
- Prediction: `pred:v3:{SYMBOL}:{HORIZON}:{LAST_CANDLE_TIME}`
- Session token cache key: `smartapi_session` (TTL 86400)

#### Layer order and fallback behavior

Snapshot (`get_snapshot`):

1. Cache read (`get_cache(snap:v3:...)`)
2. If market open: live snapshot (`_fetch_snapshot`) with `SNAPSHOT_LIVE_TIMEOUT_SECONDS`
3. If live unavailable: DB snapshot (`_db_snapshot`) via latest 1m/1d candles
4. If DB unavailable: `_mock_snapshot`
5. Normalization + cache write with TTL=3s

History (`get_history`):

1. Cache read (`hist:v3:...`)
2. DB read (`get_candles`) with `DB_READ_TIMEOUT_SECONDS`
3. If DB has enough non-stale candles, return DB payload
4. If market open and needed, fetch live history with connector timeout guards
5. If live succeeds, sanitize + `store_candles(...)` + cache
6. If live fails, fallback to DB payload if available
7. If no DB payload, generate `_mock_ohlcv` and cache

Prediction (`get_prediction`):

1. Cache read (`pred:v3:...`)
2. If market closed, immediate HOLD fallback + cache
3. If candle count < 50, immediate HOLD fallback + cache
4. Thread-offloaded prediction with `PREDICTION_TIMEOUT_SECONDS`
5. On failure: session refresh + history refresh + prediction retry
6. Normalize + persist + cache with TTL=5s

#### Redis availability fallback behavior

- `get_redis()` maintains a process singleton client.
- If Redis connect fails, `_redis_failed` is set and reconnect attempts are throttled by `_REDIS_RETRY_INTERVAL = 60` seconds.
- During Redis outage, cache operations use in-memory fallback dictionary:
  - `_fallback_cache[key] = (serialized_value, expiry_monotonic)`
- Expiry is enforced with monotonic clock checks in `get_cache(...)`.

### 12.5 Model Selection Logic (Artifact Resolution + Signal Decision)

There are two active inference selection paths in current backend runtime.

#### A) Bundle inference path (`runner.py` + `models.py`)

Artifact directory resolution in `models.py`:

1. `MODEL_PATH` env var (only if path exists)
2. `/app/models`
3. relative parent model directories where `model.pkl` exists
4. fallback to backend-level models directory (created if missing)

Artifact load behavior:

- Required artifact names tracked: `model.pkl`, `scaler.pkl`, `features.pkl`
- If `model.pkl` is missing:
  - model/scaler/features globals are cleared
  - runtime switches to safe HOLD behavior
- Legacy model payloads (missing `version`) are wrapped into compatibility payload.
- Sidecar loading is attempted for scaler/features when needed.
- Feature-version mismatch is logged and runtime continues in compatibility mode.
- Feature schema mismatch is logged; compatibility mode continues.

Decision path in `ModelEnsemble.predict(...)`:

1. Hard early HOLD conditions:
   - no/insufficient OHLCV (`<50`)
   - model artifacts unavailable
   - feature frame empty
   - missing required model features
   - inference exception
2. ML probability extraction:
   - `ml_prob_up = predict_proba(...)[0, 1]`
   - `ml_signal`: BUY if `>=0.60`, SELL if down prob `>=0.60`, else HOLD
3. Twelve-engine scoring computed (momentum/trend/volatility/volume/price action/structure/regime/time/liquidity/risk/MTF/AI).
4. Hold filters applied (`hold_filters` + `final_hard_filters`) for sideways, weak volatility, weak volume, MTF conflict, RR constraints, weak candle structure, etc.
5. Final signal selection:
   - BUY when strict bullish alignment thresholds pass
   - SELL when strict bearish alignment thresholds pass
   - otherwise HOLD
6. Post-signal enforcement:
   - confidence threshold enforcement (`<0.60` => HOLD for non-HOLD signals)
   - invalid risk envelope enforcement (`target/stop` invalid vs entry => HOLD)
   - HOLD outputs use deterministic target/stop defaults around LTP

#### B) Compatibility prediction path (`/predict/{symbol}` -> `quant_predictor.py`)

- Endpoint `/predict/{symbol}` calls `quant_predictor.predict_signal(symbol)`.
- Quant model file selection order:
  1. newest versioned `model_vN.pkl`
  2. `latest_model.json` pointer target
  3. legacy `model.pkl`
- Live data source in this path is `yfinance` 15m data (`period="60d"`).
- If confidence probability is below `MIN_SIGNAL_CONFIDENCE = 0.55`, signal is forced to HOLD.
- Any failure returns `_hold_fallback(...)` payload.

### 12.6 Latency Breakdown (Timeout Gates and Aggregation)

Bundle latency is measured in-service as:

- `latency_ms = (time.perf_counter() - started_at) * 1000`

And externally constrained by route timeout:

- `asyncio.wait_for(..., timeout=8.0)` at `/api/bundle/{symbol}`

#### Configured timeout gates currently active

- `DB_READ_TIMEOUT_SECONDS = 0.12`
- `SNAPSHOT_LIVE_TIMEOUT_SECONDS = 1.25`
- `HISTORY_LIVE_TIMEOUT_SECONDS = 2.0`
- `PREDICTION_TIMEOUT_SECONDS = 1.0`

#### Two-phase bundle critical path shape

Phase A (parallel):

- history + snapshot + market status run together
- elapsed time is dominated by `max(history_time, snapshot_time, status_time)`

Phase B (parallel):

- indicators + prediction run together
- elapsed time is dominated by `max(indicators_time, prediction_time)`

Total bundle service time approximately:

- `phaseA_max + phaseB_max + serialization/normalization overhead`

#### Practical code-path latency contributors

- Cache hit path: typically bounded by serialization and minimal compute (no live broker round-trips).
- Live history path can include connector-init timeout gate and history-fetch timeout gate.
- Prediction retry path can add:
  - first prediction timeout window
  - session refresh timeout window
  - refreshed history acquisition
  - second prediction timeout window
- Because retry is nested under bundle flow while route timeout is fixed at 8 seconds, route-level timeout can terminate request before internal retries fully complete.

### 12.7 Error Propagation Flow (From Internal Failures to API Contract)

Current backend behavior favors degradation-to-payload over request failure for most internal errors.

#### Route-level response outcomes (`/api/bundle/{symbol}`)

- Success path: `{"success": true, "data": ..., "error": null, ...}`
- Route timeout (`asyncio.TimeoutError`): HTTP 504, error code `BUNDLE_TIMEOUT`
- Unhandled route exception: HTTP 500, error code `BUNDLE_ERROR`

#### Internal bundle error handling model

- `_with_timeout(...)` converts timeout/exception into deterministic default values.
- `get_snapshot(...)` falls back live -> DB -> mock.
- `get_history(...)` falls back cache -> DB -> live -> DB -> mock.
- `get_prediction(...)` falls back to HOLD on:
  - market closed
  - insufficient candles
  - prediction timeout
  - prediction exception after refresh/retry
- `get_bundle(...)` enforces additional safety:
  - if history count `< MIN_CANDLES_FOR_BUNDLE (100)`, prediction payload is replaced with HOLD fallback.

#### Persistence/cache failure propagation

- `_save_prediction_record(...)` exceptions are caught and logged; bundle response continues.
- Redis operations (`set_cache/get_cache/delete_cache`) catch Redis errors and continue via in-memory fallback.
- Candle-store DB errors return empty/0 responses and are absorbed by higher-level fallback logic.

#### WebSocket error propagation behavior

- Tick callback errors are caught and logged in `_on_smartapi_tick`.
- Scheduled coroutine errors are captured in `_schedule_async` done callback and logged.
- Reconnect failures are retried with exponential backoff and circuit-breaker-style reset delay.

Net effect in current runtime:

- Internal subsystem failures most often surface as conservative HOLD or mock/cache-backed payloads.
- Hard HTTP failure is primarily route-timeout or top-level unhandled exception.