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
        
    # Spawn background uvicorn task on port 8004 exposing /health/live, /health/ready and /metrics
    import uvicorn
    from fastapi import FastAPI, Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    health_app = FastAPI(title="Trading Engine Health & Metrics API")
    
    @health_app.get("/health/live")
    async def live():
        return {"status": "OK"}
        
    @health_app.get("/health/ready")
    async def ready():
        from stockai_shared.cache.redis_client import get_redis
        redis_client = await get_redis()
        if redis_client is None:
            return Response(content='{"status": "degraded", "reason": "redis offline"}', status_code=503, media_type="application/json")
        from stockai_shared.db.db import check_db_connection
        db_ok = await check_db_connection(retries=1, delay=0.1)
        if not db_ok:
            return Response(content='{"status": "degraded", "reason": "db offline"}', status_code=503, media_type="application/json")
        return {"status": "ready"}
        
    @health_app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
        
    config = uvicorn.Config(app=health_app, host="0.0.0.0", port=8004, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    logger.info("[TRADING] Health and metrics server spawned on port 8004 [OK]")
    
    # Ensure streams and consumer groups exist dynamically
    for stream_name, group_name in [("stockai:candle_stream", "ai-engine-group"), ("stockai:signal_stream", "trading-engine-group")]:
        try:
            await redis_client.xgroup_create(stream_name, group_name, id="$", mkstream=True)
            logger.info("[TRADING] Created Redis Stream Consumer Group: %s -> %s", stream_name, group_name)
        except Exception:
            pass

    import uuid
    consumer_name = f"trading-engine-instance-{uuid.uuid4().hex[:8]}"
    logger.info("[TRADING] Trading Engine stream consumer '%s' initialized for 'stockai:signal_stream'", consumer_name)

    try:
        while not server_task.done():
            try:
                messages = await redis_client.xreadgroup(
                    groupname="trading-engine-group",
                    consumername=consumer_name,
                    streams={"stockai:signal_stream": ">"},
                    count=1,
                    block=1000
                )
                if not messages:
                    continue
                    
                for stream, msg_list in messages:
                    for msg_id, payload in msg_list:
                        # Exactly-once signal processing / routing (currently decoupled pass block)
                        # Always XACK immediately to confirm delivery and clear PEL.
                        await redis_client.xack("stockai:signal_stream", "trading-engine-group", msg_id)
            except Exception as loop_err:
                logger.error("[TRADING] Error reading from Redis Stream: %s", loop_err)
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        server_task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(signal_execution_loop())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Trading Execution Engine Stopped.")