#!/bin/sh
set -eu

echo "[DOCKER] Starting StockAI Pro Backend..."

DB_URL="${DATABASE_URL:-}"
RUN_MIGRATIONS_ON_START="${RUN_MIGRATIONS_ON_START:-true}"
ALLOW_START_WITH_FAILED_MIGRATIONS="${ALLOW_START_WITH_FAILED_MIGRATIONS:-false}"

if [ "${RUN_MIGRATIONS_ON_START}" = "true" ]; then
  if printf "%s" "${DB_URL}" | grep -qi "^sqlite"; then
    echo "[STARTUP] SQLite detected - skipping migrations"
  else
    echo "[STARTUP] Running alembic migrations"
    if ! alembic upgrade head; then
      if [ "${ALLOW_START_WITH_FAILED_MIGRATIONS}" = "true" ]; then
        echo "[WARNING] Migration failed but ALLOW_START_WITH_FAILED_MIGRATIONS=true, continuing startup"
      else
        echo "[ERROR] Migration failed; aborting startup"
        exit 1
      fi
    fi
  fi
fi

ACCESS_LOG_FLAG="--no-access-log"
if [ "${UVICORN_ACCESS_LOG:-false}" = "true" ]; then
  ACCESS_LOG_FLAG="--access-log"
fi

echo "[STARTUP] Starting Uvicorn on port ${PORT:-8000}"
exec uvicorn app.server:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --workers "${UVICORN_WORKERS:-2}" \
  --timeout-keep-alive "${UVICORN_TIMEOUT_KEEP_ALIVE:-20}" \
  --loop "${UVICORN_LOOP:-uvloop}" \
  --log-level "${LOG_LEVEL:-warning}" \
  ${ACCESS_LOG_FLAG}
