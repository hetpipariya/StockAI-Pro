# StockAI Pro Backend

Production-ready FastAPI backend with strict `/api/v1` routing, PostgreSQL primary storage, Redis cache/session support, and SmartAPI broker integration.

## API Contract

All REST endpoints are exposed under:

- `/api/v1/auth/*`
- `/api/v1/trades/*`
- `/api/v1/portfolio/*`
- `/api/v1/signals`
- `/api/v1/bundle/*`
- `/api/v1/market/*`
- `/api/v1/trading/*`
- `/api/v1/backtest`
- `/api/v1/news/*`
- `/api/v1/sentiment/*`
- `/api/v1/indicators/*`
- `/api/v1/symbols/*`

Health endpoints:

- `/api/v1/health`
- `/api/v1/health/detailed`
- `/api/v1/system/db-ping`

## Requirements

- Python 3.11+
- PostgreSQL 15+
- Redis 7+

## Environment Variables

Required:

- `DATABASE_URL` (example: `postgresql+asyncpg://postgres:postgres@localhost:5432/stockai`)
- `JWT_SECRET` (32+ chars)
- `REDIS_URL` (example: `redis://localhost:6379/0`)

Broker (SmartAPI) for live trading/data:

- `SMARTAPI_API_KEY`
- `SMARTAPI_CLIENT_ID`
- `SMARTAPI_CLIENT_PWD`
- `SMARTAPI_TOTP_SECRET`

Optional safety flags:

- `REQUIRE_POSTGRES=true`
- `APP_ENV=production`
- `LOG_FORMAT=json`

DB + concurrency tuning (recommended for multi-user):

- `DB_POOL_SIZE=20`
- `DB_MAX_OVERFLOW=40`
- `DB_POOL_TIMEOUT_SECONDS=30`
- `DB_POOL_RECYCLE_SECONDS=1800`
- `DB_COMMAND_TIMEOUT_SECONDS=30`
- `DB_STATEMENT_TIMEOUT_MS=5000`
- `DB_LOCK_TIMEOUT_MS=3000`
- `DB_MAX_RETRIES=3`
- `DB_RETRY_BASE_DELAY_SECONDS=0.2`
- `WS_AUTH_DB_TIMEOUT_SECONDS=2.0`
- `BUNDLE_PREWARM_CONCURRENCY=3`
- `SCHEDULER_JOB_TIMEOUT_SECONDS=120`
- `SCHEDULER_JOB_MAX_INSTANCES=1`
- `FAST_STARTUP_MODE=true`
- `FAST_STARTUP_DB_INIT_TIMEOUT_SECONDS=6.0`
- `RESET_SQLITE_ON_START=true` (SQLite-only dev mode)
- `INSTRUMENT_MASTER_URL=https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json`
- `INSTRUMENT_FETCH_TIMEOUT_SECONDS=30`
- `INSTRUMENT_FETCH_RETRIES=3`
- `INSTRUMENT_REDIS_TTL_SECONDS=86400`
- `INSTRUMENT_REFRESH_HOUR=8`
- `INSTRUMENT_REFRESH_MINUTE=0`

## Fast Startup Behavior

- API returns readiness immediately after essential schema setup.
- Heavy services run in background tasks: trading state restore, Redis init,
  instrument bootstrap, SmartAPI login/WebSocket start, model warmup, and
  bundle prewarm.
- Startup logs include `🚀 FAST API READY` when health endpoints are available.

## Dynamic Instrument Cache

- Startup loads instrument data from Redis snapshot or PostgreSQL, then refreshes from Angel One OpenAPI.
- Symbol-to-token and token-to-symbol lookups use in-memory dictionaries for O(1) access.
- Redis snapshot cache (default TTL 24h) avoids repeated full API fetches across restarts.
- Daily refresh runs through scheduler with retry and fallback to last cached/persisted snapshot.

Instrument endpoints:

- `GET /api/v1/instruments/search?symbol=RELI&exchange=NSE`
- `GET /api/v1/instruments/token?symbol=RELIANCE&exchange=NSE`
- `GET /api/v1/instruments/suggestions?q=RELI&exchange=NSE`

Compatibility aliases are also available under `/api/instruments/*`.

## PostgreSQL Migration

1. Set `DATABASE_URL` to PostgreSQL with async driver:

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/stockai
export REQUIRE_POSTGRES=true
```

2. Run migrations:

```bash
alembic upgrade head
```

3. Start API and verify:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/api/v1/system/db-ping
```

## Local Run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start PostgreSQL and Redis.

3. Run backend:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker Run

From repo root:

```bash
docker compose up --build
```

Backend service health is verified via `/api/v1/health`.
