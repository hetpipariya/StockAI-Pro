#!/usr/bin/env python
"""Comprehensive backend diagnostics script."""

import sys
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Test 1: Import all routes
logger.info("=" * 60)
logger.info("TEST 1: Route Imports")
logger.info("=" * 60)
try:
    from app.routes import (auth, backtest, bundle, indicators, market, news,
                            portfolio, predict, sentiment, signals, symbols,
                            trades, trading)
    logger.info("✓ All route modules imported successfully")
except Exception as e:
    logger.error(f"✗ Route import failed: {e}")
    sys.exit(1)

# Test 2: Check app initialization
logger.info("\n" + "=" * 60)
logger.info("TEST 2: App Initialization")
logger.info("=" * 60)
try:
    from app.server import app
    logger.info(f"✓ FastAPI app created: {app.title}")
    logger.info(f"  Routes registered: {len(app.routes)}")
except Exception as e:
    logger.error(f"✗ App initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: List all routes
logger.info("\n" + "=" * 60)
logger.info("TEST 3: Registered Routes")
logger.info("=" * 60)
try:
    api_routes = []
    for route in app.routes:
        path = getattr(route, 'path', '')
        methods = getattr(route, 'methods', set())
        if path.startswith('/api'):
            api_routes.append(f"{path:50} {str(methods)}")
    
    logger.info(f"Total API routes: {len(api_routes)}")
    for route in sorted(api_routes)[:20]:
        logger.info(f"  {route}")
    if len(api_routes) > 20:
        logger.info(f"  ... and {len(api_routes) - 20} more routes")
except Exception as e:
    logger.error(f"✗ Route listing failed: {e}")

# Test 4: Check critical dependencies
logger.info("\n" + "=" * 60)
logger.info("TEST 4: Critical Dependencies")
logger.info("=" * 60)

deps_to_check = {
    'redis': 'redis',
    'sqlalchemy': 'sqlalchemy',
    'SmartApi': 'smartapi-python',
    'numpy': 'numpy',
    'pandas': 'pandas',
    'sklearn': 'scikit-learn',
    'xgboost': 'xgboost',
    'joblib': 'joblib',
}

for module_name, package_name in deps_to_check.items():
    try:
        __import__(module_name)
        logger.info(f"✓ {package_name}")
    except ImportError as e:
        logger.error(f"✗ {package_name}: {e}")

# Test 5: Database connection
logger.info("\n" + "=" * 60)
logger.info("TEST 5: Database Connection")
logger.info("=" * 60)
try:
    from app.config import DATABASE_URL
    logger.info(f"✓ Database URL configured: {DATABASE_URL[:50]}...")
    
    async def test_db():
        from app.core.database import healthcheck
        result = await healthcheck(retries=1)
        if result:
            logger.info("✓ Database connection successful")
        else:
            logger.warning("⚠ Database connection failed (may not be running)")
    
    try:
        asyncio.run(test_db())
    except Exception as e:
        logger.warning(f"⚠ Database test skipped: {type(e).__name__}")
except Exception as e:
    logger.error(f"✗ Database config error: {e}")

# Test 6: Redis connection
logger.info("\n" + "=" * 60)
logger.info("TEST 6: Redis Connection")
logger.info("=" * 60)
try:
    from app.services.redis_client import get_redis
    try:
        client = get_redis()
        if client:
            logger.info("✓ Redis client available")
        else:
            logger.warning("⚠ Redis client not available")
    except Exception as e:
        logger.warning(f"⚠ Redis connection test failed: {e}")
except Exception as e:
    logger.error(f"✗ Redis import error: {e}")

# Test 7: Config validation
logger.info("\n" + "=" * 60)
logger.info("TEST 7: Environment Configuration")
logger.info("=" * 60)
try:
    from app import config
    logger.info(f"✓ Config loaded")
    logger.info(f"  App Env: {config.APP_ENV}")
    logger.info(f"  JWT Secret: {'*' * 8}{config.JWT_SECRET[-8:] if len(config.JWT_SECRET) > 8 else '***'}")
    logger.info(f"  DB Backend: {'PostgreSQL' if 'postgres' in config.DATABASE_URL else 'SQLite'}")
except Exception as e:
    logger.error(f"✗ Config error: {e}")

logger.info("\n" + "=" * 60)
logger.info("Backend Diagnostic Complete")
logger.info("=" * 60)
