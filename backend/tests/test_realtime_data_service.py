from __future__ import annotations

import pytest

from app.services.realtime_data_service import LiveMarketDataService


@pytest.mark.anyio
async def test_fetch_snapshot_uses_local_symbol_resolution(monkeypatch):
    calls: dict[str, object] = {}

    def _mock_get_token(symbol: str) -> str:
        calls["token_symbol"] = symbol
        return "2885"

    def _mock_get_tradingsymbol(symbol: str) -> str:
        calls["tradingsymbol_symbol"] = symbol
        return "RELIANCE-EQ"

    class _DummyConnector:
        def get_ltp(self, token: str, exchange: str, tradingsymbol: str):
            calls["ltp_args"] = (token, exchange, tradingsymbol)
            return {
                "ltp": 2500.5,
                "open": 2490.0,
                "high": 2512.0,
                "low": 2488.0,
                "close": 2499.0,
                "volume": 1500,
            }

    monkeypatch.setattr(
        "app.services.realtime_data_service.get_token_by_symbol",
        _mock_get_token,
    )
    monkeypatch.setattr(
        "app.services.realtime_data_service.get_tradingsymbol",
        _mock_get_tradingsymbol,
    )

    service = LiveMarketDataService(connector_provider=lambda: _DummyConnector(), exchange="NSE")
    payload = await service.fetch_snapshot("reliance")

    assert payload["symbol"] == "RELIANCE"
    assert calls["token_symbol"] == "RELIANCE"
    assert calls["tradingsymbol_symbol"] == "RELIANCE"
    assert calls["ltp_args"] == ("2885", "NSE", "RELIANCE-EQ")


@pytest.mark.anyio
async def test_fetch_snapshot_unknown_symbol_raises_before_connector(monkeypatch):
    connector_called = {"value": False}

    def _mock_get_token(_symbol: str) -> str:
        raise KeyError("Instrument token not found for symbol: UNKNOWN")

    def _connector_provider():
        connector_called["value"] = True

        class _NeverUsedConnector:
            def get_ltp(self, *_args, **_kwargs):
                return None

        return _NeverUsedConnector()

    monkeypatch.setattr(
        "app.services.realtime_data_service.get_token_by_symbol",
        _mock_get_token,
    )

    service = LiveMarketDataService(connector_provider=_connector_provider, exchange="NSE")

    with pytest.raises(KeyError):
        await service.fetch_snapshot("unknown")

    assert connector_called["value"] is False


@pytest.mark.anyio
async def test_fetch_history_rows_uses_local_token(monkeypatch):
    def _mock_get_token(_symbol: str) -> str:
        return "3045"

    def _mock_get_tradingsymbol(_symbol: str) -> str:
        return "SBIN-EQ"

    class _DummyConnector:
        def fetch_history(
            self,
            token: str,
            exchange: str,
            interval: str,
            from_date,
            to_date,
            limit: int,
        ):
            assert token == "3045"
            assert exchange == "NSE"
            assert interval == "1m"
            assert limit == 2
            return [["2026-04-11 09:15:00", 1, 2, 1, 2, 100]]

    monkeypatch.setattr(
        "app.services.realtime_data_service.get_token_by_symbol",
        _mock_get_token,
    )
    monkeypatch.setattr(
        "app.services.realtime_data_service.get_tradingsymbol",
        _mock_get_tradingsymbol,
    )

    service = LiveMarketDataService(connector_provider=lambda: _DummyConnector(), exchange="NSE")
    rows = await service.fetch_history_rows("sbin", "1m", None, None, 2)

    assert isinstance(rows, list)
    assert len(rows) == 1
