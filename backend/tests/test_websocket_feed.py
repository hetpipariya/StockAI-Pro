"""WebSocket feed fallback tests for off-hours and idle-stream behavior."""

import asyncio

import pytest

from app.websocket import handler, relay


@pytest.fixture(autouse=True)
def reset_ws_feed_state():
    handler._last_known_prices.clear()
    relay._last_push.clear()
    relay._last_tick.clear()
    yield
    handler._last_known_prices.clear()
    relay._last_push.clear()
    relay._last_tick.clear()


@pytest.mark.anyio
async def test_mock_ws_data_job_emits_seeded_ticks_off_hours(monkeypatch):
    emitted: list[tuple[str, dict]] = []

    async def _capture(symbol: str, payload: dict):
        emitted.append((symbol, payload))

    monkeypatch.setattr(handler.config, "ENABLE_MOCK_DATA", True)
    monkeypatch.setattr(handler, "is_market_open", lambda: False)
    monkeypatch.setattr(handler, "DEFAULT_WATCHLIST", ["RELIANCE", "TCS"])
    monkeypatch.setattr(handler, "broadcast_tick", _capture)

    await handler.mock_ws_data_job()

    assert len(emitted) == 2
    for symbol, payload in emitted:
        assert payload["is_mock"] is True
        assert payload["unavailable"] is True
        assert payload["data_source"] == "MOCK"
        assert payload["ltp"] > 0
        assert payload["mock_reason"] in {"OFF_HOURS_SEEDED", "OFF_HOURS_STALE"}
        assert symbol in handler._last_known_prices


@pytest.mark.anyio
async def test_mock_ws_data_job_marks_seeded_idle_ticks_unavailable(monkeypatch):
    emitted: list[tuple[str, dict]] = []

    async def _capture(symbol: str, payload: dict):
        emitted.append((symbol, payload))

    monkeypatch.setattr(handler.config, "ENABLE_MOCK_DATA", True)
    monkeypatch.setattr(handler, "is_market_open", lambda: True)
    monkeypatch.setattr(handler, "get_last_tick_age_seconds", lambda: 30.0)
    monkeypatch.setattr(handler, "DEFAULT_WATCHLIST", ["RELIANCE", "TCS"])
    monkeypatch.setattr(handler, "broadcast_tick", _capture)

    handler._last_known_prices["RELIANCE"] = 2460.25

    await handler.mock_ws_data_job()

    by_symbol = {symbol: payload for symbol, payload in emitted}
    assert set(by_symbol.keys()) == {"RELIANCE", "TCS"}

    assert by_symbol["RELIANCE"]["unavailable"] is False
    assert by_symbol["RELIANCE"]["mock_reason"] == "IDLE_FEED_STALE"

    assert by_symbol["TCS"]["unavailable"] is True
    assert by_symbol["TCS"]["mock_reason"] == "IDLE_FEED_SEEDED"
    assert by_symbol["TCS"]["ltp"] > 0


@pytest.mark.anyio
async def test_relay_allows_repeated_mock_ticks_without_dedup(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def _capture(symbol: str, payload: dict):
        sent.append((symbol, payload))

    monkeypatch.setattr(relay.socket_manager, "broadcast_tick", _capture)

    live_tick = {"ltp": 101.5, "volume": 0, "is_mock": False}
    await relay.broadcast_tick("RELIANCE", live_tick)
    await asyncio.sleep((relay.THROTTLE_MS + 20) / 1000)
    await relay.broadcast_tick("RELIANCE", live_tick)

    live_messages = [payload for symbol, payload in sent if symbol == "RELIANCE"]
    assert len(live_messages) == 1

    mock_tick = {
        "ltp": 250.0,
        "volume": 0,
        "is_mock": True,
        "unavailable": True,
        "mock_reason": "OFF_HOURS_SEEDED",
        "data_source": "MOCK",
    }
    await relay.broadcast_tick("TCS", mock_tick)
    await asyncio.sleep((relay.THROTTLE_MS + 20) / 1000)
    await relay.broadcast_tick("TCS", mock_tick)

    mock_messages = [payload for symbol, payload in sent if symbol == "TCS"]
    assert len(mock_messages) == 2
    assert all(msg["is_mock"] is True for msg in mock_messages)
    assert all(msg["mock_reason"] == "OFF_HOURS_SEEDED" for msg in mock_messages)


def test_resolve_mock_base_price_corrects_paise_cached_value():
    handler._last_known_prices["RELIANCE"] = 134810.0

    price, seeded = handler._resolve_mock_base_price("RELIANCE")

    assert seeded is False
    assert price == 1348.1
    assert handler._last_known_prices["RELIANCE"] == 1348.1


@pytest.mark.anyio
async def test_on_smartapi_tick_normalizes_reliance_paise(monkeypatch):
    emitted: list[tuple[str, dict]] = []

    async def _capture(symbol: str, payload: dict):
        emitted.append((symbol, payload))

    class _DummyCandleBuilder:
        def process_tick(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(handler, "broadcast_tick", _capture)
    monkeypatch.setattr(
        handler.tick_aggregator, "process_tick", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(handler, "_cached_candle_builder_15m", _DummyCandleBuilder())
    monkeypatch.setattr(
        handler, "_schedule_async", lambda coro: asyncio.create_task(coro)
    )

    msg = {
        "tradingsymbol": "RELIANCE-EQ",
        "ltp": 134810,
        "volume": 100,
    }

    handler._on_smartapi_tick(msg)
    await asyncio.sleep(0)

    assert handler._last_known_prices["RELIANCE"] == 1348.1
    assert emitted
    assert emitted[0][0] == "RELIANCE"
    assert emitted[0][1]["ltp"] == 1348.1
