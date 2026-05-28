#!/usr/bin/env python
"""Advanced backend testing for STEPS 3-7 of debugging."""

import sys
import asyncio
import logging
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# STEP 3: Server startup test
logger.info("=" * 60)
logger.info("STEP 3: Server Startup Test")
logger.info("=" * 60)

try:
    import uvicorn
    logger.info("✓ Uvicorn available")
    
    # Test import paths
    try:
        from app.server import app
        logger.info("✓ Can import from 'app.server:app' (correct path)")
    except ImportError:
        logger.error("✗ Cannot import from app.server:app")
    
    try:
        from app.main import app as app_main
        logger.info("✓ Can import from 'app.main:app' (alternate path)")
    except ImportError:
        logger.warning("⚠ Cannot import from app.main:app (fallback)")
    
    # Check uvicorn command
    logger.info("\nProduction startup command:")
    logger.info("  uvicorn app.server:app --host 0.0.0.0 --port 8000 --workers 4")
    logger.info("  OR for development:")
    logger.info("  uvicorn app.server:app --reload --port 8000")
    
except Exception as e:
    logger.error(f"✗ Server startup issue: {e}")

# STEP 4: Full Redis + Database integration
logger.info("\n" + "=" * 60)
logger.info("STEP 4: Redis + Database Integration")
logger.info("=" * 60)

async def test_redis_db_integration():
    try:
        # Test database
        from app.core.database import engine, healthcheck
        result = await healthcheck(retries=1)
        if result:
            logger.info("✓ Database: Connection successful")
        
        # Get session for testing
        from app.core.database import get_session
        async for session in get_session():
            # Try a real query
            from sqlalchemy import text
            result = await session.execute(text("SELECT COUNT(*) as cnt FROM users"))
            row = result.first()
            logger.info(f"✓ Database: Executed query (users count: {row[0] if row else 'N/A'})")
            break
        
        # Test Redis integration with trading data
        from app.services.redis_client import RedisClient
        redis_client = RedisClient()
        
        # Check connection
        if redis_client.client:
            logger.info("✓ Redis: Client initialized")
            
            # Test cache operations
            test_key = "test:integration:key"
            test_value = {"symbol": "SBIN", "price": 500.25}
            
            try:
                redis_client.client.setex(test_key, 60, json.dumps(test_value))
                cached = redis_client.client.get(test_key)
                if cached:
                    logger.info(f"✓ Redis: Set/Get operations working")
                redis_client.client.delete(test_key)
            except Exception as e:
                logger.warning(f"⚠ Redis operations: {e}")
        else:
            logger.warning("⚠ Redis: Client not available")
            
    except Exception as e:
        logger.error(f"✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test_redis_db_integration())

# STEP 5: WebSocket testing
logger.info("\n" + "=" * 60)
logger.info("STEP 5: WebSocket Endpoint Testing")
logger.info("=" * 60)

try:
    from app.websocket.handler import socket_manager
    logger.info("✓ WebSocket manager imported")
    
    # Check the handler has required methods
    required_methods = ['connect', 'disconnect', 'broadcast', 'send_personal']
    for method in required_methods:
        if hasattr(socket_manager, method):
            logger.info(f"✓ WebSocket manager has '{method}' method")
        else:
            logger.warning(f"⚠ WebSocket manager missing '{method}' method")
    
    # List WebSocket routes
    from app.server import app
    ws_routes = [r for r in app.routes if hasattr(r, 'path') and 'ws' in getattr(r, 'path', '').lower() or 'live' in getattr(r, 'path', '').lower()]
    
    logger.info(f"\nWebSocket routes found:")
    if ws_routes:
        for route in ws_routes:
            logger.info(f"  - {route.path}")
    else:
        logger.warning("⚠ No WebSocket routes detected")
        
        # Check for specific endpoints
        all_paths = [getattr(r, 'path', '') for r in app.routes]
        for path in all_paths:
            if 'live' in path.lower() or 'ws' in path.lower():
                logger.info(f"  Found: {path}")
                
except Exception as e:
    logger.error(f"✗ WebSocket test failed: {e}")
    import traceback
    traceback.print_exc()

# STEP 6: Predict/AI endpoint testing
logger.info("\n" + "=" * 60)
logger.info("STEP 6: AI/Predict Endpoint Testing")
logger.info("=" * 60)

async def test_predict_endpoint():
    try:
        # Check if predict route exists
        from app.routes.predict import router as predict_router
        logger.info("✓ Predict router imported")
        
        # Check endpoints
        routes = [r for r in predict_router.routes]
        logger.info(f"  Predict endpoints: {len(routes)} routes")
        for route in routes:
            if hasattr(route, 'path'):
                methods = getattr(route, 'methods', set())
                logger.info(f"    - {route.path} [{', '.join(methods)}]")
        
        # Test model loading
        from app.inference.models import ModelEnsemble, ensure_models_loaded
        logger.info("✓ ModelEnsemble imported")
        
        # Try to get a prediction signature
        try:
            if hasattr(ModelEnsemble, 'predict'):
                logger.info("✓ ModelEnsemble has 'predict' method")
        except Exception as e:
            logger.warning(f"⚠ Model method check: {e}")
            
    except Exception as e:
        logger.error(f"✗ Predict endpoint test failed: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test_predict_endpoint())

# STEP 7: Error handling & 500 responses
logger.info("\n" + "=" * 60)
logger.info("STEP 7: Error Handling & Response Format")
logger.info("=" * 60)

try:
    # Check exception handlers in middleware
    from app.middleware import add_exception_handlers
    logger.info("✓ add_exception_handlers imported successfully")
    
    # Check for custom error responses
    from app.server import app
    from starlette.middleware.exceptions import ServerErrorMiddleware
    
    middleware_names = [type(m.cls).__name__ if hasattr(m, 'cls') else str(m) for m in app.user_middleware]
    
    if 'ServerErrorMiddleware' in middleware_names or any('Exception' in str(m) for m in middleware_names):
        logger.info("✓ Exception handling middleware installed")
    else:
        # Check if app has exception handlers
        if app.exception_handlers:
            logger.info(f"✓ {len(app.exception_handlers)} exception handlers registered")
        else:
            logger.warning("⚠ Limited exception handler configuration detected")
    
    # Verify error response format expectations
    logger.info("\nExpected error response format:")
    logger.info("  {")
    logger.info("    'detail': 'Error message',")
    logger.info("    'status_code': 500,")
    logger.info("    'timestamp': 'ISO timestamp',")
    logger.info("    'request_id': 'UUID',")
    logger.info("    'path': '/api/v1/...'")
    logger.info("  }")
    
except Exception as e:
    logger.error(f"✗ Error handling test failed: {e}")

logger.info("\n" + "=" * 60)
logger.info("Advanced Diagnostic Testing Complete")
logger.info("=" * 60)
