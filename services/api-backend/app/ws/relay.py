import logging

logger = logging.getLogger(__name__)

def get_client_count() -> int:
    """Mock client count for separated API backend health check."""
    return 0

async def start_realtime_relay_listener() -> str:
    logger.info("[WS-MOCK] start_realtime_relay_listener called")
    return "mocked"

async def stop_realtime_relay_listener() -> None:
    logger.info("[WS-MOCK] stop_realtime_relay_listener called")
    pass
