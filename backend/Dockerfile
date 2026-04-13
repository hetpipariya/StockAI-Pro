# ====================================================================
# STOCKAI PRO - Backend Dockerfile (FastAPI + Python)
# Optimized for production with multi-stage build
# ====================================================================

# ========== STAGE 1: BUILD WHEELS ==========
# Compile dependencies to wheels for faster installation
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Build wheels (this caches the expensive compilation step)
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt


# ========== STAGE 2: RUNTIME ==========
# Minimal runtime image with only necessary dependencies
FROM python:3.11-slim

WORKDIR /app

# ========== Set metadata ==========
LABEL maintainer="StockAI Pro Team"
LABEL description="StockAI Pro Backend - FastAPI with async workers"
LABEL version="1.0.0"

# ========== Install runtime dependencies only ==========
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ========== Copy wheels and requirements ==========
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

# ========== Install Python dependencies from wheels ==========
RUN pip install --no-cache-dir /wheels/*

# ========== Copy application ==========
COPY . .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# ========== Set environment variables ==========
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
  PORT=8000 \
  RUN_MIGRATIONS_ON_START=true \
  ALLOW_START_WITH_FAILED_MIGRATIONS=false \
  FORWARDED_ALLOW_IPS=*

RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
  useradd --create-home --home-dir /home/appuser --shell /usr/sbin/nologin appuser && \
  chown -R appuser:appuser /app

USER appuser

# ========== Verify models directory ==========
RUN mkdir -p /app/models && \
    echo "[DOCKER] Models directory structure:" && \
    ls -la /app/models/ 2>/dev/null || echo "Models directory (may be empty - loaded at runtime)"

# ========== Health check ==========
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/v1/health" || exit 1

# ========== Expose port ==========
EXPOSE 8000

# ========== Start command ==========
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

