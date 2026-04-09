from __future__ import annotations

import asyncio

import pytest


@pytest.mark.anyio
async def test_bundle_endpoint_success_contract(client, monkeypatch):
    async def _mock_bundle(*_args, **_kwargs):
        return {
            "symbol": "RELIANCE",
            "timestamp": "2026-03-30T10:30:00Z",
            "history": {
                "candles": [
                    {
                        "time": "2026-03-30 10:00:00",
                        "open": 1,
                        "high": 2,
                        "low": 1,
                        "close": 2,
                        "volume": 10,
                    }
                ]
                * 100,
                "count": 100,
            },
            "snapshot": {
                "price": 2847.50,
                "change": 12.30,
                "volume": 1234567,
                "market_status": "OPEN",
            },
            "prediction": {
                "signal": "BUY",
                "confidence": 0.85,
                "confidence_pct": 85,
                "target": 2900,
                "stop_loss": 2820,
                "reasoning": "EMA crossover + RSI support",
            },
            "indicators": {
                "ema_20": 2835.4,
                "ema_50": 2810.2,
                "rsi": 62.5,
                "macd": {"value": 1.2, "signal": 0.8, "histogram": 0.4},
                "bollinger": {"upper": 2860, "middle": 2830, "lower": 2800},
            },
            "market_status": "OPEN",
        }

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_bundle)

    response = await client.get("/api/bundle/RELIANCE")
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None

    payload = body["data"]
    assert payload["symbol"] == "RELIANCE"
    assert payload["history"]["count"] == 100
    assert payload["snapshot"]["market_status"] == "OPEN"
    assert payload["prediction"]["signal"] in {"BUY", "SELL", "HOLD"}
    assert "macd" in payload["indicators"]


@pytest.mark.anyio
async def test_bundle_endpoint_timeout_contract(client, monkeypatch):
    async def _mock_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_timeout)

    response = await client.get("/api/bundle/RELIANCE")
    assert response.status_code == 504

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "BUNDLE_TIMEOUT"


@pytest.mark.anyio
async def test_legacy_routes_are_deprecated(app_with_overrides):
    openapi = app_with_overrides.openapi()

    history_deprecated = openapi["paths"]["/api/market/history"]["get"]["deprecated"]
    snapshot_deprecated = openapi["paths"]["/api/market/snapshot"]["get"]["deprecated"]
    predict_deprecated = openapi["paths"]["/api/predict"]["get"]["deprecated"]
    indicators_deprecated = openapi["paths"]["/api/indicators"]["get"]["deprecated"]

    assert history_deprecated is True
    assert snapshot_deprecated is True
    assert predict_deprecated is True
    assert indicators_deprecated is True
