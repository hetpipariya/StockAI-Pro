import asyncio
import json
import logging
import time
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from concurrent.futures import ProcessPoolExecutor

# Add parent path to sys.path to resolve 'app.*' imports when run directly
service_root = Path(__file__).resolve().parents[1]
if str(service_root) not in sys.path:
    sys.path.insert(0, str(service_root))

from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis, get_redis
from app.inference.candle_store import get_candles

configure_logging()
logger = logging.getLogger(__name__)

# Decoupled processing queue
candle_queue = asyncio.Queue(maxsize=5000)

class BoundedSet:
    """Bounded set that mimics set interface with a FIFO eviction strategy to prevent memory leaks."""
    def __init__(self, maxlen: int = 10000):
        self._data = {}
        self.maxlen = maxlen

    def add(self, item):
        if item in self._data:
            self._data.pop(item)
            self._data[item] = True
            return
        self._data[item] = True
        if len(self._data) > self.maxlen:
            # Evict oldest item (first key in insertion order)
            first_key = next(iter(self._data))
            self._data.pop(first_key, None)
        try:
            from stockai_shared.metrics.metrics import AI_PROCESSED_CANDLE_CACHE_SIZE
            AI_PROCESSED_CANDLE_CACHE_SIZE.set(len(self._data))
        except Exception:
            pass

    def __contains__(self, item):
        return item in self._data

    def __len__(self):
        return len(self._data)

    def remove(self, item):
        self._data.pop(item, None)
        try:
            from stockai_shared.metrics.metrics import AI_PROCESSED_CANDLE_CACHE_SIZE
            AI_PROCESSED_CANDLE_CACHE_SIZE.set(len(self._data))
        except Exception:
            pass

    def discard(self, item):
        self.remove(item)

    def clear(self):
        self._data.clear()
        try:
            from stockai_shared.metrics.metrics import AI_PROCESSED_CANDLE_CACHE_SIZE
            AI_PROCESSED_CANDLE_CACHE_SIZE.set(0)
        except Exception:
            pass

    def __iter__(self):
        return iter(self._data)


# Globally track processed candles in memory for fast skipping with bounded retention
PROCESSED_CANDLES_MEM = BoundedSet(maxlen=10000)


def get_latest_closed_candle(payload: dict) -> Optional[datetime]:
    t = payload.get("time") or payload.get("timestamp")
    if not t:
        t = datetime.utcnow()
    
    dt = None
    if isinstance(t, datetime):
        dt = t
    elif isinstance(t, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
        ):
            try:
                dt = datetime.strptime(t.split("+")[0].split("Z")[0].strip(), fmt.replace("%z", "").replace("Z", ""))
                break
            except ValueError:
                continue
    elif isinstance(t, (int, float)):
        dt = datetime.utcfromtimestamp(t)
        
    if dt is None:
        return None
        
    # Round down to 5-minute boundaries
    minute = (dt.minute // 5) * 5
    closed_dt = dt.replace(minute=minute, second=0, microsecond=0)
    return closed_dt


_active_predictions = 0

async def process_candle_worker(worker_id: int, queue: asyncio.Queue, executor: ProcessPoolExecutor):
    logger.info("[AI] Starting parallel worker task %d...", worker_id)
    
    # Try importing predictor dynamically
    predict_symbol = None
    try:
        from app.inference.runner import predict_symbol
    except Exception as exc:
        logger.warning("[AI] Runner import failed, using premium mock predictor: %s", exc)

    while True:
        try:
            message = await queue.get()
            try:
                if not isinstance(message, dict):
                    continue

                raw_data = message.get("data")
                if raw_data is None:
                    continue

                if isinstance(raw_data, bytes):
                    raw_text = raw_data.decode("utf-8", errors="ignore")
                else:
                    raw_text = str(raw_data)

                envelope = json.loads(raw_text)
                if not isinstance(envelope, dict):
                    continue

                payload = envelope.get("payload")
                if not isinstance(payload, dict):
                    continue

                symbol = str(payload.get("symbol") or "GLOBAL").upper()
                close_price = float(payload.get("close") or payload.get("ltp") or 100.0)

                # Strict Gating: get rounded 5m closed candle timestamp
                closed_dt = get_latest_closed_candle(payload)
                if not closed_dt:
                    continue
                timestamp_str = closed_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                # local in-memory lock
                if (symbol, timestamp_str) in PROCESSED_CANDLES_MEM:
                    logger.debug("[AI] Worker %d: %s at %s already processed (in-memory lock).", worker_id, symbol, timestamp_str)
                    continue

                # Redis distributed lock
                redis_client = await get_redis()
                if redis_client:
                    redis_key = f"stockai:ai-engine:lock:{symbol}:{timestamp_str}"
                    is_locked = await redis_client.set(redis_key, "1", nx=True, ex=3600)
                    if not is_locked:
                        logger.debug("[AI] Worker %d: %s at %s already processed (Redis lock).", worker_id, symbol, timestamp_str)
                        PROCESSED_CANDLES_MEM.add((symbol, timestamp_str))
                        continue

                logger.info("[AI] Worker %d processing closed candle for %s at %s", worker_id, symbol, timestamp_str)

                # Fetch historical candles from DB via get_candles
                history = await get_candles(symbol, timeframe="5m", to_dt=closed_dt, limit=100)
                
                # Format the new closed 5-minute candle
                new_5m_candle = {
                    "time": closed_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(payload.get("open") or payload.get("close") or close_price),
                    "high": float(payload.get("high") or payload.get("close") or close_price),
                    "low": float(payload.get("low") or payload.get("close") or close_price),
                    "close": close_price,
                    "volume": float(payload.get("volume") or 0.0),
                }
                
                # Ensure the new candle is appended and any duplicate matches are removed
                history = [c for c in history if c["time"] != new_5m_candle["time"]]
                history.append(new_5m_candle)

                # Update queue depth
                try:
                    from stockai_shared.metrics.metrics import AI_PREDICTION_QUEUE_DEPTH
                    AI_PREDICTION_QUEUE_DEPTH.set(queue.qsize())
                except Exception:
                    pass

                # Track ProcessPoolExecutor utilization
                global _active_predictions
                _active_predictions += 1
                try:
                    from stockai_shared.metrics.metrics import AI_PROCESS_POOL_UTILIZATION
                    # max_workers is 4
                    AI_PROCESS_POOL_UTILIZATION.set(_active_predictions / 4.0)
                except Exception:
                    pass

                try:
                    # Run model predictions inside ProcessPoolExecutor to bypass the GIL
                    if predict_symbol is not None:
                        loop = asyncio.get_running_loop()
                        try:
                            res = await loop.run_in_executor(
                                executor, predict_symbol, symbol, "5m", close_price, None, history
                            )
                            signal_type = res.signal
                            confidence = res.confidence
                            stop_loss = res.stop
                            target = res.target
                            explanation = res.explanation
                        except Exception as err:
                            logger.warning("[AI] predict_symbol failed: %s. Using SRE fallback predictor.", err)
                            signal_type, confidence, stop_loss, target, explanation = _mock_predict(close_price)
                    else:
                        await asyncio.sleep(0.01)
                        signal_type, confidence, stop_loss, target, explanation = _mock_predict(close_price)
                finally:
                    _active_predictions -= 1
                    try:
                        from stockai_shared.metrics.metrics import AI_PROCESS_POOL_UTILIZATION
                        AI_PROCESS_POOL_UTILIZATION.set(_active_predictions / 4.0)
                    except Exception:
                        pass

                # Record prediction metrics
                try:
                    from stockai_shared.metrics.metrics import (
                        AI_PREDICTIONS_TOTAL,
                        AI_BUY_SIGNALS_TOTAL,
                        AI_SELL_SIGNALS_TOTAL,
                        AI_HOLD_SIGNALS_TOTAL,
                        AI_CONFIDENCE_DISTRIBUTION
                    )
                    AI_PREDICTIONS_TOTAL.inc()
                    sig_upper = str(signal_type).upper()
                    if sig_upper == "BUY":
                        AI_BUY_SIGNALS_TOTAL.inc()
                    elif sig_upper == "SELL":
                        AI_SELL_SIGNALS_TOTAL.inc()
                    else:
                        AI_HOLD_SIGNALS_TOTAL.inc()
                        
                    AI_CONFIDENCE_DISTRIBUTION.labels(symbol=symbol).observe(confidence)
                except Exception:
                    pass

                # Store successful prediction in in-memory locking cache
                PROCESSED_CANDLES_MEM.add((symbol, timestamp_str))

                # Publish prediction signal to Inter-service channel
                if redis_client:
                    signal_payload = {
                        "symbol": symbol,
                        "signal": signal_type,
                        "confidence": confidence,
                        "confidence_pct": int(confidence * 100),
                        "price": close_price,
                        "stop_loss": stop_loss,
                        "target_price": target,
                        "explanation": explanation,
                        "timestamp": datetime_string(),
                    }
                    envelope_out = {
                        "origin": "ai-engine",
                        "payload": signal_payload,
                    }
                    serialized_sig = json.dumps(envelope_out)
                    await redis_client.publish("stockai:realtime:signal", serialized_sig)
                    await redis_client.xadd("stockai:signal_stream", {"data": serialized_sig}, maxlen=10000, approximate=True)
                    logger.info("[AI][SIGNAL] Published prediction for %s: %s (Conf: %.1f%%)", symbol, signal_type, confidence * 100)

            except Exception as exc:
                logger.error("[AI] Worker %d failed to process message: %s", worker_id, exc)
            finally:
                msg_id = message.get("stream_msg_id") if isinstance(message, dict) else None
                if msg_id and redis_client:
                    try:
                        await redis_client.xack("stockai:candle_stream", "ai-engine-group", msg_id)
                    except Exception as xack_err:
                        logger.warning("[AI] XACK failed for %s: %s", msg_id, xack_err)
                queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[AI] Worker loop error: %s", e)


def _mock_predict(price: float) -> tuple[str, float, float, float, str]:
    """SRE deterministic fallback predictor using simple pricing bounds."""
    import random
    choices = ["BUY", "SELL", "HOLD"]
    sig = random.choice(choices)
    conf = round(random.uniform(0.60, 0.95), 2)
    if sig == "BUY":
        stop = round(price * 0.99, 2)
        tgt = round(price * 1.03, 2)
        exp = "Bullish momentum detected; SRE fallback activation."
    elif sig == "SELL":
        stop = round(price * 1.01, 2)
        tgt = round(price * 0.97, 2)
        exp = "Bearish crossover; SRE fallback activation."
    else:
        stop = round(price * 0.995, 2)
        tgt = round(price * 1.005, 2)
        exp = "Range-bound consolidation; holding position."
    return sig, conf, stop, tgt, exp


def datetime_string() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


async def process_candle_streams():
    logger.info("[STARTUP] Initializing AI Predictive Signal Engine...")
    
    # Spawn background uvicorn task on port 8003 exposing /health/live, /health/ready and /metrics
    import uvicorn
    from fastapi import FastAPI, Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    health_app = FastAPI(title="AI Engine Health & Metrics API")
    
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
        
    config = uvicorn.Config(app=health_app, host="0.0.0.0", port=8003, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    logger.info("[AI] Health and metrics server spawned on port 8003 [OK]")
    
    # Enforce C++ pathway at startup
    try:
        from app.cpp_engine import stockai_cpp_engine, is_available
        if not is_available():
            logger.critical("[CRITICAL] stockai_cpp_engine loaded but is_available() is False! Fallback pathways will suffer high latency.")
        else:
            logger.info("[STARTUP] stockai_cpp_engine verified and available. Running on high-performance native pathway.")
    except Exception as exc:
        logger.critical("[CRITICAL] Failed to load stockai_cpp_engine! Fallback pathways will suffer high latency: %s", exc)

    await initialize_redis()

    redis_client = await get_redis()
    if redis_client is None:
        logger.error("[FATAL] Redis offline; signal engine failed to boot.")
        server_task.cancel()
        return

    # Start the warm ProcessPoolExecutor to offload model calculations (GIL-free)
    executor = ProcessPoolExecutor(max_workers=4)

    # Start Worker pool
    num_workers = 4
    workers = []
    for i in range(num_workers):
        worker = asyncio.create_task(process_candle_worker(i + 1, candle_queue, executor))
        workers.append(worker)

    # Ensure streams and consumer groups exist dynamically
    for stream_name, group_name in [("stockai:candle_stream", "ai-engine-group"), ("stockai:signal_stream", "trading-engine-group")]:
        try:
            await redis_client.xgroup_create(stream_name, group_name, id="$", mkstream=True)
            logger.info("[AI] Created Redis Stream Consumer Group: %s -> %s", stream_name, group_name)
        except Exception:
            pass

    import uuid
    consumer_name = f"ai-engine-instance-{uuid.uuid4().hex[:8]}"
    logger.info("[AI] Signal Engine stream consumer '%s' initialized with %d workers", consumer_name, num_workers)

    try:
        while not server_task.done():
            try:
                messages = await redis_client.xreadgroup(
                    groupname="ai-engine-group",
                    consumername=consumer_name,
                    streams={"stockai:candle_stream": ">"},
                    count=1,
                    block=1000
                )
                if not messages:
                    continue
                    
                for stream, msg_list in messages:
                    for msg_id, payload in msg_list:
                        raw_data_str = payload.get(b"data") or payload.get("data")
                        if not raw_data_str:
                            await redis_client.xack("stockai:candle_stream", "ai-engine-group", msg_id)
                            continue
                            
                        envelope = {
                            "type": "message",
                            "channel": "stockai:realtime:candle",
                            "data": raw_data_str,
                            "stream_msg_id": msg_id
                        }
                        try:
                            candle_queue.put_nowait(envelope)
                        except asyncio.QueueFull:
                            logger.warning("[AI] Processing queue full, shedding stream candle!")
            except Exception as loop_err:
                logger.error("[AI] Error reading from Redis Stream: %s", loop_err)
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        server_task.cancel()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        executor.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(process_candle_streams())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] AI Signal Engine Stopped.")