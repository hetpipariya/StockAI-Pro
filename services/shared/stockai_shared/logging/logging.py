from __future__ import annotations

import atexit
import json
import logging
import sys
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from datetime import datetime, timezone

from stockai_shared.config.config import (APP_ENV, LOG_FORMAT, LOG_LEVEL, LOG_QUEUE_MAXSIZE,
                        SQLALCHEMY_ECHO, UVICORN_ACCESS_LOG)
from stockai_shared.utils.request_context import get_request_id


_queue_listener: QueueListener | None = None


class NonBlockingQueueHandler(QueueHandler):
    """Drop log records if the queue is saturated to protect request latency."""

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            qsize = self.queue.qsize()
            maxsize = self.queue.maxsize if self.queue.maxsize > 0 else 10000
            utilization = qsize / maxsize if maxsize > 0 else 0.0
            
            from stockai_shared.metrics.metrics import LOG_QUEUE_SIZE, LOG_QUEUE_UTILIZATION
            LOG_QUEUE_SIZE.set(qsize)
            LOG_QUEUE_UTILIZATION.set(utilization)
        except Exception:
            pass

        try:
            self.queue.put_nowait(record)
        except Exception:
            # Intentionally drop when queue is full/unavailable to avoid blocking.
            try:
                from stockai_shared.metrics.metrics import DROPPED_LOG_ENTRIES_TOTAL
                DROPPED_LOG_ENTRIES_TOTAL.inc()
            except Exception:
                pass
            return


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def _configure_noisy_logger_levels(root_level: int) -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.setLevel(logging.WARNING)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.disabled = not UVICORN_ACCESS_LOG
    uvicorn_access.propagate = UVICORN_ACCESS_LOG
    if UVICORN_ACCESS_LOG:
        uvicorn_access.setLevel(root_level)

    sqlalchemy_level = logging.INFO if SQLALCHEMY_ECHO else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)
    logging.getLogger("sqlalchemy.pool").setLevel(sqlalchemy_level)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Silence startup/runtime chatter from internal modules; lifespan prints
    # concise high-level status lines instead.
    for noisy_logger in (
        "app.trading.trading_state",
        "app.trading.risk_manager",
        "app.connectors.order_router",
        "app.trading.live_executor",
        "app.trading.live_executor_5m",
        "app.services.token_manager",
        "app.services.redis_client",
        "app.services.db",
        "app.connectors.smartapi_connector",
        "app.websocket.handler",
        "app.services.instrument_service",
        "app.services.scheduler",
        "app.middleware",
        "websocket",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)


def shutdown_logging() -> None:
    global _queue_listener
    if _queue_listener is not None:
        _queue_listener.stop()
        _queue_listener = None


def configure_logging() -> None:
    global _queue_listener

    root = logging.getLogger()
    if getattr(root, "_stockai_logging_configured", False):
        return

    level = getattr(logging, str(LOG_LEVEL).upper(), logging.INFO)
    sink_handler = logging.StreamHandler(sys.stdout)

    if str(LOG_FORMAT).lower() == "json":
        sink_handler.setFormatter(JsonLogFormatter())
    else:
        sink_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s [req=%(request_id)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    sink_handler.setLevel(level)

    log_queue: Queue = Queue(maxsize=LOG_QUEUE_MAXSIZE) if LOG_QUEUE_MAXSIZE else Queue()
    queue_handler = NonBlockingQueueHandler(log_queue)
    queue_handler.addFilter(RequestContextFilter())
    queue_handler.setLevel(level)

    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(queue_handler)

    _queue_listener = QueueListener(log_queue, sink_handler, respect_handler_level=True)
    _queue_listener.start()
    atexit.register(shutdown_logging)

    logging.getLogger("uvicorn").setLevel(level)
    _configure_noisy_logger_levels(level)

    setattr(root, "_stockai_logging_configured", True)
