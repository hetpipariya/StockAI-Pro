from fastapi import FastAPI, Response
from fastapi.middleware.gzip import GZipMiddleware
from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis
from app.ws.handler import setup_websocket_routes
from app.ws.relay import start_realtime_relay_listener, stop_realtime_relay_listener
from contextlib import asynccontextmanager
import logging
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

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

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/ping")
async def ping():
    return {"status": "pong"}