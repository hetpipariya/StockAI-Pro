from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.broker_router import BrokerRouter


class _FailingSmartAPI:
    def login(self, force: bool = False):
        raise RuntimeError("SmartAPI token expired")

    def ensure_login(self):
        raise RuntimeError("SmartAPI token expired")

    def refresh_session(self):
        raise RuntimeError("SmartAPI token expired")

    def fetch_history(self, *args, **kwargs):
        raise RuntimeError("SmartAPI token expired")

    def fetch_latest(self, *args, **kwargs):
        raise RuntimeError("SmartAPI token expired")

    def subscribe(self, *args, **kwargs):
        raise RuntimeError("SmartAPI token expired")

    def unsubscribe(self, *args, **kwargs):
        return True


class _HealthyUpstox:
    def __init__(self):
        self.calls = []

    def login(self, force: bool = False):
        self.calls.append(("login", force))
        return {"status": True, "accessToken": "demo"}

    def ensure_login(self):
        self.calls.append(("ensure_login", None))

    def refresh_session(self):
        self.calls.append(("refresh_session", None))
        return True

    def fetch_history(self, *args, **kwargs):
        self.calls.append(("fetch_history", args))
        return [["2026-05-21T09:15:00Z", 1, 2, 0.5, 1.5, 100]]

    def fetch_latest(self, *args, **kwargs):
        self.calls.append(("fetch_latest", args))
        return {"ltp": 1.5, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}

    def subscribe(self, *args, **kwargs):
        self.calls.append(("subscribe", args))
        return True

    def unsubscribe(self, *args, **kwargs):
        self.calls.append(("unsubscribe", args))
        return True


def test_router_falls_back_to_upstox_on_auth_failure():
    router = BrokerRouter(primary="smartapi", fallback="upstox")
    upstox = _HealthyUpstox()
    router._connectors = {"smartapi": _FailingSmartAPI(), "upstox": upstox}
    router._active_broker = "smartapi"
    router._breaker_until = {"smartapi": 0.0, "upstox": 0.0}
    router._breaker_reason = {"smartapi": "", "upstox": ""}

    history = router.fetch_history("123", "NSE", "1m", None, None, 1)

    assert history
    assert router.active_broker == "upstox"
    assert upstox.calls[-1][0] == "fetch_history"


def test_router_uses_active_broker_for_login_then_recovers():
    router = BrokerRouter(primary="smartapi", fallback="upstox")
    upstox = _HealthyUpstox()
    router._connectors = {"smartapi": _FailingSmartAPI(), "upstox": upstox}
    router._active_broker = "smartapi"
    router._breaker_until = {"smartapi": 0.0, "upstox": 0.0}
    router._breaker_reason = {"smartapi": "", "upstox": ""}

    payload = router.login(force=True)

    assert payload["status"] is True
    assert router.active_broker == "upstox"
