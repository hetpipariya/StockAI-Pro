import time
import logging

logger = logging.getLogger(__name__)

class DummyWSConnector:
    def login(self, force: bool = False) -> None:
        logger.info("[WS-MOCK] DummyWSConnector.login called")
        pass

    def stop_ws(self) -> None:
        logger.info("[WS-MOCK] DummyWSConnector.stop_ws called")
        pass

    def terminate_session(self) -> None:
        logger.info("[WS-MOCK] DummyWSConnector.terminate_session called")
        pass

    def start_ws(self) -> None:
        logger.info("[WS-MOCK] DummyWSConnector.start_ws called")
        pass

    def setup_ws(self) -> None:
        logger.info("[WS-MOCK] DummyWSConnector.setup_ws called")
        pass

_dummy_connector = DummyWSConnector()

def get_ws_state() -> str:
    """Mock connection state for separated API backend health check."""
    return "CONNECTED"

def is_ws_streaming() -> bool:
    """Mock websocket streaming indicator for api-backend health check."""
    return True

def get_last_tick_age_seconds() -> float:
    """Mock last tick age for api-backend health check."""
    return 1.0

def setup_websocket_routes(app) -> None:
    """No-op route setup in separated API backend service."""
    pass

def get_ws_connector() -> DummyWSConnector:
    return _dummy_connector

def get_or_create_ws_connector() -> DummyWSConnector:
    return _dummy_connector

def set_event_loop(loop) -> None:
    pass

def set_ws_connector(connector) -> None:
    pass

async def auto_start_ws() -> None:
    logger.info("[WS-MOCK] auto_start_ws called")
    pass
