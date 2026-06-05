# ====================================================================
# STOCKAI PRO - Backend Dockerfile (FastAPI + Python)
# Optimized for production with multi-stage build
# ====================================================================

# ========== STAGE 1: BUILD WHEELS ==========
# Compile dependencies to wheels for faster installation
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and the shared package source from the repo root build context
COPY backend/requirements.txt ./backend/requirements.txt
COPY services/shared ./services/shared

# Install build-time helpers for the native acceleration module
# RUN pip install --no-cache-dir pybind11
    
# # Copy native sources and build the extension module
# COPY cpp ./cpp
# WORKDIR /app/cpp



# RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" \
#     && cmake --build build --config Release \
#     && find build -name "stockai_cpp*.so" -exec cp {} /app/ \;

# WORKDIR /app

# Build wheels (this caches the expensive compilation step)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r backend/requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /wheels ./services/shared


# ========== STAGE 2: RUNTIME ==========
# Minimal runtime image with only necessary dependencies
FROM python:3.11-slim

WORKDIR /app/backend

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
COPY --from=builder /wheels /wheels
COPY backend/requirements.txt ./requirements.txt
#  COPY --from=builder /app/stockai_cpp*.so /app/

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

# ========== Install Python dependencies from wheels ==========
RUN pip install --no-cache-dir /wheels/*

# ========== Copy application ==========
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# ========== Set environment variables ==========
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
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

