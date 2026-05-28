from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.upstox_connector import UpstoxConnector
from app.data.nifty_data_loader import NiftyDataLoader


class _NoNetworkUpstox(UpstoxConnector):
    def _validate_token(self) -> bool:  # type: ignore[override]
        return True


def test_upstox_connector_reads_latest_env_token(monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "fresh-token-xyz")
    monkeypatch.setenv("UPSTOX_API_KEY", "demo-key")
    monkeypatch.setenv("UPSTOX_API_SECRET", "demo-secret")
    monkeypatch.setenv("UPSTOX_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setattr(UpstoxConnector, "_reload_runtime_env", lambda self: None)

    connector = UpstoxConnector(validate_on_init=False)

    assert connector.access_token == "fresh-token-xyz"
    assert connector.is_logged_in is False


def test_upstox_connector_fails_fast_when_token_missing(monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("UPSTOX_API_KEY", "demo-key")
    monkeypatch.setenv("UPSTOX_API_SECRET", "demo-secret")
    monkeypatch.setenv("UPSTOX_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setattr(UpstoxConnector, "_reload_runtime_env", lambda self: None)

    with pytest.raises(RuntimeError, match="missing from environment"):
        UpstoxConnector(validate_on_init=True)


def test_nifty_loader_clamps_future_window(monkeypatch):
    monkeypatch.setattr(UpstoxConnector, "_reload_runtime_env", lambda self: None)
    loader = NiftyDataLoader(symbol="NIFTY 50", connector=_NoNetworkUpstox(validate_on_init=False))

    future_from = datetime.now(timezone.utc) + timedelta(days=10)
    future_to = datetime.now(timezone.utc) + timedelta(days=20)
    clamped_from, clamped_to = loader._clamp_window(future_from, future_to)

    now_ist = datetime.now(tz=ZoneInfo("Asia/Kolkata"))
    assert clamped_to <= now_ist
    assert clamped_from <= clamped_to
    assert clamped_to.tzinfo is not None
