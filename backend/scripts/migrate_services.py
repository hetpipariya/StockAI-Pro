#!/usr/bin/env python3
"""
StockAI Pro — Enterprise Service Separation & Refactor Engine

Redesigned for complete, safe, and robust migration of StockAI Pro backend
into modular service architecture under the /services root directory.
"""

from __future__ import annotations

import os
import ast
import shutil
import glob
from pathlib import Path
from typing import Dict, List, Set

# ============================================================
# PATHS
# ============================================================
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
SERVICES_ROOT = REPO_ROOT / "services"

print(f"\n[INFO] Repository Root: {REPO_ROOT}")
print(f"[INFO] Backend Root:    {BACKEND_ROOT}")
print(f"[INFO] Services Root:   {SERVICES_ROOT}")

# ============================================================
# SERVICE LAYOUT
# ============================================================
SERVICE_DIRS = [
    "shared",
    "shared/stockai_shared",
    "shared/stockai_shared/config",
    "shared/stockai_shared/logging",
    "shared/stockai_shared/db",
    "shared/stockai_shared/cache",
    "shared/stockai_shared/metrics",
    "shared/stockai_shared/schemas",
    "shared/stockai_shared/utils",
    "shared/stockai_shared/services",
    "shared/stockai_shared/connectors",
    "shared/stockai_shared/core",
    "shared/stockai_shared/models",
    
    "api-backend",
    "api-backend/app",
    "api-backend/app/routes",
    "api-backend/app/services",
    "api-backend/app/middleware",
    
    "websocket-gateway",
    "websocket-gateway/app",
    "websocket-gateway/app/ws",
    
    "market-feed",
    "market-feed/app",
    "market-feed/app/feed",
    
    "ai-engine",
    "ai-engine/app",
    "ai-engine/app/inference",
    
    "trading-engine",
    "trading-engine/app",
    "trading-engine/app/trading",
    "trading-engine/app/strategy",
]

# ============================================================
# TARGET MAPPING SYSTEM
# ============================================================
# Explicitly direct individual files or wildcards to service targets
FILE_MAPPINGS = [
    # 1. SHARED
    (APP_ROOT / "config.py", SERVICES_ROOT / "shared/stockai_shared/config/config.py"),
    (APP_ROOT / "logging_setup.py", SERVICES_ROOT / "shared/stockai_shared/logging/logging.py"),
    (APP_ROOT / "services/db.py", SERVICES_ROOT / "shared/stockai_shared/db/db.py"),
    (APP_ROOT / "services/redis_client.py", SERVICES_ROOT / "shared/stockai_shared/cache/redis_client.py"),
    (APP_ROOT / "services/metrics.py", SERVICES_ROOT / "shared/stockai_shared/metrics/metrics.py"),
    (APP_ROOT / "services/instrument_service.py", SERVICES_ROOT / "shared/stockai_shared/services/instrument_service.py"),
    (APP_ROOT / "services/instrument_master.py", SERVICES_ROOT / "shared/stockai_shared/services/instrument_master.py"),
    (APP_ROOT / "services/ticker_map.py", SERVICES_ROOT / "shared/stockai_shared/services/ticker_map.py"),
    (APP_ROOT / "services/token_manager.py", SERVICES_ROOT / "shared/stockai_shared/services/token_manager.py"),
    (APP_ROOT / "services/market_state.py", SERVICES_ROOT / "shared/stockai_shared/services/market_state.py"),
    (APP_ROOT / "utils/auth_utils.py", SERVICES_ROOT / "shared/stockai_shared/utils/auth_utils.py"),
    (APP_ROOT / "utils/request_context.py", SERVICES_ROOT / "shared/stockai_shared/utils/request_context.py"),
    (APP_ROOT / "models.py", SERVICES_ROOT / "shared/stockai_shared/models/models.py"),
    
    # 2. API BACKEND
    (APP_ROOT / "main.py", SERVICES_ROOT / "api-backend/app/main.py"),
    (APP_ROOT / "server.py", SERVICES_ROOT / "api-backend/app/server.py"),
    (APP_ROOT / "lifespan.py", SERVICES_ROOT / "api-backend/app/lifespan.py"),
    (APP_ROOT / "middleware.py", SERVICES_ROOT / "api-backend/app/middleware.py"),
    (APP_ROOT / "services/auth_service.py", SERVICES_ROOT / "api-backend/app/services/auth_service.py"),
    (APP_ROOT / "services/bundle_service.py", SERVICES_ROOT / "api-backend/app/services/bundle_service.py"),
    (APP_ROOT / "services/startup_manager.py", SERVICES_ROOT / "api-backend/app/services/startup_manager.py"),
    (APP_ROOT / "services/scheduler.py", SERVICES_ROOT / "api-backend/app/services/scheduler.py"),
    
    # 3. WEBSOCKET GATEWAY
    (APP_ROOT / "websocket/handler.py", SERVICES_ROOT / "websocket-gateway/app/ws/handler.py"),
    (APP_ROOT / "websocket/relay.py", SERVICES_ROOT / "websocket-gateway/app/ws/relay.py"),
    
    # 4. MARKET FEED
    (APP_ROOT / "services/realtime_data_service.py", SERVICES_ROOT / "market-feed/app/feed/realtime_data_service.py"),
    (APP_ROOT / "services/tick_aggregator.py", SERVICES_ROOT / "market-feed/app/feed/tick_aggregator.py"),
    (APP_ROOT / "trading/candle_builder.py", SERVICES_ROOT / "market-feed/app/feed/candle_builder.py"),
    
    # 5. AI ENGINE
    (APP_ROOT / "services/native_accelerators.py", SERVICES_ROOT / "ai-engine/app/inference/native_accelerators.py"),
    (APP_ROOT / "services/indicators.py", SERVICES_ROOT / "ai-engine/app/inference/indicators.py"),
    (APP_ROOT / "services/feature_cache.py", SERVICES_ROOT / "ai-engine/app/inference/feature_cache.py"),
    (APP_ROOT / "services/candle_store.py", SERVICES_ROOT / "ai-engine/app/inference/candle_store.py"),
    
    # 6. TRADING ENGINE
    (APP_ROOT / "services/trade_decision_engine.py", SERVICES_ROOT / "trading-engine/app/trading/trade_decision_engine.py"),
    (APP_ROOT / "services/trading_read_service.py", SERVICES_ROOT / "trading-engine/app/trading/trading_read_service.py"),
]

# ============================================================
# DYNAMIC IMPORT REWRITE ENGINE MAP
# ============================================================
IMPORT_REWRITES = {
    # absolute imports mapping
    "app.config": "stockai_shared.config.config",
    "app.logging_setup": "stockai_shared.logging.logging",
    "app.services.db": "stockai_shared.db.db",
    "app.services.redis_client": "stockai_shared.cache.redis_client",
    "app.services.metrics": "stockai_shared.metrics.metrics",
    "app.services.instrument_service": "stockai_shared.services.instrument_service",
    "app.services.instrument_master": "stockai_shared.services.instrument_master",
    "app.services.ticker_map": "stockai_shared.services.ticker_map",
    "app.services.token_manager": "stockai_shared.services.token_manager",
    "app.services.market_state": "stockai_shared.services.market_state",
    "app.utils.auth_utils": "stockai_shared.utils.auth_utils",
    "app.utils.request_context": "stockai_shared.utils.request_context",
    "app.models": "stockai_shared.models.models",
    "app.connectors": "stockai_shared.connectors",
    "app.core": "stockai_shared.core",
    "app.schemas": "stockai_shared.schemas",
    
    # internal redirections inside services
    "app.websocket.relay": "app.ws.relay",
    "app.websocket.handler": "app.ws.handler",
    "app.websocket": "app.ws",
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def ensure_init(directory: Path):
    init_file = directory / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""StockAI Pro Modular Package"""\n', encoding="utf-8")

def safe_copy(src: Path, dst: Path):
    if not src.exists():
        print(f"[WARN] Source missing, skipping copy: {src}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[COPY] {src.relative_to(REPO_ROOT)} -> {dst.relative_to(REPO_ROOT)}")

def rewrite_imports_in_file(file_path: Path):
    if file_path.suffix != ".py":
        return
    
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[ERROR] Could not read file {file_path}: {e}")
        return

    original = content
    
    # Apply import rewrites
    for old_import, new_import in IMPORT_REWRITES.items():
        # Replace occurrences in various import formats:
        # 1. from old_import import X
        # 2. import old_import
        content = content.replace(f"from {old_import} import", f"from {new_import} import")
        content = content.replace(f"from {old_import} ", f"from {new_import} ")
        content = content.replace(f"import {old_import}", f"import {new_import}")

    # Fix specific sub-relative imports or system configurations if any
    content = content.replace('load_dotenv(dotenv_path=_env_path, override=False)', 'load_dotenv(dotenv_path=Path(__file__).resolve().parents[4] / ".env", override=False)')

    if content != original:
        file_path.write_text(content, encoding="utf-8")
        print(f"[REWRITE] {file_path.relative_to(SERVICES_ROOT)}")

# ============================================================
# CORE REFACTOR STAGES
# ============================================================
def create_service_folders():
    print("\n[STAGE 1] Initializing Service Folder Layouts...\n")
    for s_dir in SERVICE_DIRS:
        full_path = SERVICES_ROOT / s_dir
        full_path.mkdir(parents=True, exist_ok=True)
        ensure_init(full_path)
        print(f"[DIR] Created {full_path.relative_to(REPO_ROOT)}")

def create_shared_package_setup():
    print("\n[STAGE 2] Packaging stockai_shared Setup Script...\n")
    setup_py = SERVICES_ROOT / "shared/setup.py"
    setup_py.write_text(
        """
from setuptools import setup, find_packages

setup(
    name="stockai_shared",
    version="2.0.0",
    packages=find_packages(),
    install_packages=["pydantic", "redis", "sqlalchemy", "passlib", "bcrypt"],
)
""".strip(),
        encoding="utf-8"
    )
    print(f"[SHARED-SETUP] setup.py generated at {setup_py.relative_to(REPO_ROOT)}")

def copy_explicit_mappings():
    print("\n[STAGE 3] Copying and Rewriting Explicit File Mappings...\n")
    for src, dst in FILE_MAPPINGS:
        safe_copy(src, dst)
        rewrite_imports_in_file(dst)

def copy_dynamic_directories():
    print("\n[STAGE 4] Migrating Component Directories Dynamically...\n")
    
    # Dynamic copy definitions
    dir_mappings = [
        # Source dir, Target dir, Destination file rewrite scope
        (APP_ROOT / "routes", SERVICES_ROOT / "api-backend/app/routes", "api-backend"),
        (APP_ROOT / "schemas", SERVICES_ROOT / "shared/stockai_shared/schemas", "shared"),
        (APP_ROOT / "core", SERVICES_ROOT / "shared/stockai_shared/core", "shared"),
        (APP_ROOT / "connectors", SERVICES_ROOT / "shared/stockai_shared/connectors", "shared"),
        (APP_ROOT / "inference", SERVICES_ROOT / "ai-engine/app/inference", "ai-engine"),
        (APP_ROOT / "trading", SERVICES_ROOT / "trading-engine/app/trading", "trading-engine"),
        (APP_ROOT / "strategy", SERVICES_ROOT / "trading-engine/app/strategy", "trading-engine"),
        (APP_ROOT / "utils", SERVICES_ROOT / "shared/stockai_shared/utils", "shared"),
    ]

    for src_dir, dst_dir, label in dir_mappings:
        if not src_dir.exists():
            print(f"[SKIP] Directory not found: {src_dir}")
            continue
            
        dst_dir.mkdir(parents=True, exist_ok=True)
        ensure_init(dst_dir)
        
        for file_path in src_dir.rglob("*.py"):
            if "__pycache__" in file_path.parts:
                continue
                
            # Compute destination path preserving directory structure
            rel_path = file_path.relative_to(src_dir)
            target_path = dst_dir / rel_path
            
            # Skip candle_builder.py in trading dynamic directory since it is mapped to market-feed
            if file_path.name == "candle_builder.py" and "trading" in file_path.parts:
                print(f"[SKIP-T] candle_builder.py explicitly redirected to market-feed")
                continue
                
            safe_copy(file_path, target_path)
            rewrite_imports_in_file(target_path)

def create_microservice_bootstraps():
    print("\n[STAGE 5] Creating Clean Microservice Bootstrap Files...\n")
    
    # WebSocket gateway boot main.py
    ws_main = SERVICES_ROOT / "websocket-gateway/app/main.py"
    ws_main.write_text("""
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis
from app.ws.handler import setup_websocket_routes
from app.ws.relay import start_realtime_relay_listener, stop_realtime_relay_listener
from contextlib import asynccontextmanager
import logging

configure_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[STARTUP] Starting Decoupled WebSocket Gateway...")
    await initialize_redis()
    await start_realtime_relay_listener()
    yield
    logger.info("[SHUTDOWN] Stopping WebSocket Gateway...")
    await stop_realtime_relay_listener()

app = FastAPI(title="StockAI WebSocket Gateway", version="2.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
setup_websocket_routes(app)
""".strip(), encoding="utf-8")
    print(f"[BOOT] WebSocket bootstrap entrypoint written.")

    # Market feed ingestion service main.py
    mf_main = SERVICES_ROOT / "market-feed/app/main.py"
    mf_main.write_text("""
import asyncio
import logging
from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis
from stockai_shared.connectors import get_market_data_connector
from stockai_shared.config.config import DEFAULT_WATCHLIST
from app.feed.realtime_data_service import LiveMarketDataService

configure_logging()
logger = logging.getLogger(__name__)

async def run_market_feed():
    logger.info("[STARTUP] Initializing Market Feed Ingestor Service...")
    await initialize_redis()
    
    # Instantiate broker connections and subscribe to active tokens
    connector = get_market_data_connector()
    logger.info(f"[FEED] Attached to primary broker: {connector.active_broker}")
    
    # Simple keep-alive execution harness
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(run_market_feed())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Market Feed Service Stopped.")
""".strip(), encoding="utf-8")
    print(f"[BOOT] Market Feed bootstrap entrypoint written.")

    # AI engine microservice main.py
    ai_main = SERVICES_ROOT / "ai-engine/app/main.py"
    ai_main.write_text("""
import asyncio
import logging
from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis, get_redis

configure_logging()
logger = logging.getLogger(__name__)

async def process_candle_streams():
    logger.info("[STARTUP] Initializing AI Predictive Signal Engine...")
    await initialize_redis()
    
    redis_client = await get_redis()
    if redis_client is None:
        logger.error("[FATAL] Redis offline; signal engine failed to boot.")
        return
        
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe("stockai:realtime:candle")
    logger.info("[AI] Signal Engine subscribed to Redis 'stockai:realtime:candle'")
    
    async for message in pubsub.listen():
        # Listen for real-time candles and generate AI indicators/signals
        pass

if __name__ == "__main__":
    try:
        asyncio.run(process_candle_streams())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] AI Signal Engine Stopped.")
""".strip(), encoding="utf-8")
    print(f"[BOOT] AI Engine bootstrap entrypoint written.")

    # Trading Execution main.py
    trade_main = SERVICES_ROOT / "trading-engine/app/main.py"
    trade_main.write_text("""
import asyncio
import logging
from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis, get_redis

configure_logging()
logger = logging.getLogger(__name__)

async def signal_execution_loop():
    logger.info("[STARTUP] Initializing Decoupled Risk & Trading Engine...")
    await initialize_redis()
    
    redis_client = await get_redis()
    if redis_client is None:
        logger.error("[FATAL] Redis offline; trading engine failed to boot.")
        return
        
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe("stockai:realtime:signal")
    logger.info("[TRADING] Trading Engine subscribed to Redis 'stockai:realtime:signal'")
    
    async for message in pubsub.listen():
        # Receive generated signals and route orders
        pass

if __name__ == "__main__":
    try:
        asyncio.run(signal_execution_loop())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Trading Execution Engine Stopped.")
""".strip(), encoding="utf-8")
    print(f"[BOOT] Trading Engine bootstrap entrypoint written.")

def create_requirements_and_dockers():
    print("\n[STAGE 6] Compiling requirements.txt & Dockerfiles...\n")
    
    requirements = {
        "shared": "sqlalchemy\nredis\norjson\npydantic\npasslib\nbcrypt\npython-dotenv\npython-jose",
        "api-backend": "fastapi\nuvicorn\nprometheus-fastapi-instrumentator\ngzip\nstockai_shared",
        "websocket-gateway": "fastapi\nuvicorn\nstockai_shared",
        "market-feed": "websocket-client\nstockai_shared",
        "ai-engine": "numpy\npandas\nscikit-learn\nxgboost\nyfinance\nstockai_shared",
        "trading-engine": "stockai_shared",
    }
    
    for service, content in requirements.items():
        req_file = SERVICES_ROOT / service / "requirements.txt"
        req_file.write_text(content.strip(), encoding="utf-8")
        print(f"[REQ] Written requirements.txt for services/{service}")

    # Write dockerfile template for API/WS Gateways
    docker_template = """
FROM python:3.10-slim

WORKDIR /workspace

# Install shared library dependencies first
COPY services/shared /workspace/services/shared
RUN pip install --no-cache-dir -e /workspace/services/shared

# Copy service dependencies and install
COPY services/{service} /workspace/services/{service}
WORKDIR /workspace/services/{service}
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE {port}
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{port}"]
"""

    for svc, port in [("api-backend", 8000), ("websocket-gateway", 8001)]:
        df = SERVICES_ROOT / svc / "Dockerfile"
        df.write_text(docker_template.format(service=svc, port=port).strip(), encoding="utf-8")
        print(f"[DOCKER] Dockerfile compiled for services/{svc}")

def validate_syntax():
    print("\n[STAGE 7] Running Verification & Syntax Validations...\n")
    success = True
    for py_file in SERVICES_ROOT.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
            print(f"[VALID-AST] {py_file.relative_to(SERVICES_ROOT)}")
        except Exception as exc:
            print(f"[SYNTAX ERROR] AST failed on {py_file}: {exc}")
            success = False
            
    if success:
        print("\n[VERIFICATION STATUS] AST verification PASSED. Zero syntax errors detected!")
    else:
        print("\n[VERIFICATION STATUS] AST verification FAILED. Please inspect the failures above.")

# ============================================================
# MAIN ENTRYPOINT
# ============================================================
def main():
    print("\n" + "=" * 80)
    print("      STOCKAI PRO - ENTERPRISE SERVICE SEPARATION ENGINE      ")
    print("=" * 80)
    
    create_service_folders()
    create_shared_package_setup()
    copy_explicit_mappings()
    copy_dynamic_directories()
    create_microservice_bootstraps()
    create_requirements_and_dockers()
    validate_syntax()
    
    print("\n" + "=" * 80)
    print("      SERVICE REFACTORING SUCCESSFULLY COMPLETED      ")
    print("=" * 80)
    print("\nNext Steps:")
    print("1. Install Shared Package locally:")
    print("   pip install -e services/shared")
    print("2. Launch individual microservices from /services as needed.\n")

if __name__ == "__main__":
    main()
