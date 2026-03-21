# Stage 1: Build
FROM python:3.9-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Stage 2: Runtime
FROM python:3.9-slim

WORKDIR /app

# Install runtime dependencies for psycopg2 and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache /wheels/*

COPY . .

# Run alembic migrations (PostgreSQL only) then start the server.
# If DATABASE_URL is absent, points to the docker-compose 'postgres' hostname,
# or starts with 'sqlite', migrations are skipped and the app uses SQLite.
CMD ["sh", "-c", "\
  DB=${DATABASE_URL:-}; \
  if echo \"$DB\" | grep -qE '^postgres(ql)?[+:]' && ! echo \"$DB\" | grep -qE '@postgres(:|/)'; then \
    echo '[DOCKER] Running alembic migrations for PostgreSQL...' && alembic upgrade head; \
  else \
    echo '[DOCKER] Skipping alembic migrations (SQLite or local docker hostname detected)'; \
  fi && \
  gunicorn app.server:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000"]
