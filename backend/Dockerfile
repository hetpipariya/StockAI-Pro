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
# Ensure ML models available at /app/models
COPY models/ ./models/

# Set model path for the application
ENV MODEL_PATH=/app/models

# Run alembic migrations (PostgreSQL only) and start uvicorn
CMD ["sh", "-c", "echo '[DOCKER] Model files:' && ls -la /app/models/*.pkl 2>/dev/null || echo 'WARNING: No model files found'; python -c \"from app.config import DATABASE_URL; exit(0 if DATABASE_URL.startswith('sqlite') else 1)\" && echo '[STARTUP] SQLite — skipping migrations' || (echo '[STARTUP] PostgreSQL — running migrations' && alembic upgrade head); uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=\"*\""]
