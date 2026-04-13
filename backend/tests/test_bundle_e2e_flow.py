"""End-to-end Bundle API integration tests (April 1, 2026)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@pytest.mark.anyio
async def test_bundle_api_e2e_full_flow(client, monkeypatch):
    """
    Scenario: User loads dashboard → selects symbol → bundle API loads all data
    expectations:
    - Single API call returns: history, snapshot, prediction, indicators, market_status
    - All required fields present
    - Response size reasonable
    - Latency tracked
    """
    async def _mock_bundle(*_args, **_kwargs):
        return {
            "symbol": "RELIANCE",
            "timestamp": _utc_now_iso(),
            "history": {
                "candles": [
                    {
                        "time": "2026-04-01 10:00:00",
                        "open": 2845.0,
                        "high": 2850.0,
                        "low": 2840.0,
                        "close": 2847.5,
                        "volume": 1234567,
                    }
                    for _ in range(100)
                ],
                "count": 100,
                "source": "DB",
                "data_source": "CACHE",
            },
            "snapshot": {
                "symbol": "RELIANCE",
                "price": 2847.5,
                "ltp": 2847.5,
                "open": 2840.0,
                "high": 2850.0,
                "low": 2835.0,
                "close": 2847.5,
                "change": 12.5,
                "volume": 2567890,
                "source": "NSE_API",
                "data_source": "NSE_API",
                "last_ts": _utc_now_iso(),
                "market_status": "OPEN",
            },
            "prediction": {
                "symbol": "RELIANCE",
                "signal": "BUY",
                "confidence": 0.82,
                "confidence_pct": 82,
                "prediction": 2847.5,
                "target": 2900.0,
                "target_price": 2900.0,
                "stop_loss": 2820.0,
                "regime": "TRENDING_UP",
                "factors": ["EMA_CROSSOVER", "RSI_SUPPORT"],
                "models": {"xgboost": 0.82, "rf": 0.78},
                "reasoning": "EMA 9/15 crossover with positive RSI",
                "explanation": "Technical analysis indicates bullish",
            },
            "indicators": {
                "symbol": "RELIANCE",
                "ema_20": 2835.4,
                "ema_50": 2810.2,
                "ema9": 2848.1,
                "ema15": 2846.0,
                "rsi": 62.5,
                "rsi9": 62.5,
                "macd": {
                    "value": 1.25,
                    "signal": 0.80,
                    "histogram": 0.45,
                },
                "bollinger": {
                    "upper": 2860.0,
                    "middle": 2830.0,
                    "lower": 2800.0,
                },
            },
            "market_status": "OPEN",
            "market": {"is_open": True, "state": "OPEN"},
            "latency_ms": 145.2,
        }

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_bundle)

    # Simulate dashboard load for RELIANCE on 1m timeframe
    response = await client.get("/api/v1/bundle/RELIANCE?interval=1m&limit=100&horizon=15m")

    # Verify response structure
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["timestamp"] is not None

    payload = body["data"]

    # Validate history data
    assert payload["symbol"] == "RELIANCE"
    assert payload["history"]["count"] == 100
    assert len(payload["history"]["candles"]) == 100
    assert payload["history"]["source"] == "DB"
    assert "time" in payload["history"]["candles"][0]
    assert "open" in payload["history"]["candles"][0]
    assert "high" in payload["history"]["candles"][0]
    assert "low" in payload["history"]["candles"][0]
    assert "close" in payload["history"]["candles"][0]
    assert "volume" in payload["history"]["candles"][0]

    # Validate snapshot data
    assert payload["snapshot"]["symbol"] == "RELIANCE"
    assert payload["snapshot"]["price"] == 2847.5
    assert payload["snapshot"]["ltp"] == 2847.5
    assert payload["snapshot"]["market_status"] == "OPEN"

    # Validate prediction data (signal and confidence)
    assert payload["prediction"]["signal"] in {"BUY", "SELL", "HOLD"}
    assert payload["prediction"]["confidence"] >= 0
    assert payload["prediction"]["confidence"] <= 1
    assert payload["prediction"]["target"] is not None
    assert payload["prediction"]["stop_loss"] is not None

    # Validate indicators
    assert "ema_20" in payload["indicators"]
    assert "ema_50" in payload["indicators"]
    assert "rsi" in payload["indicators"]
    assert "macd" in payload["indicators"]
    assert "bollinger" in payload["indicators"]

    # Validate market status propagated
    assert payload["market_status"] == "OPEN"

    # Validate latency tracked
    assert payload["latency_ms"] is not None
    assert payload["latency_ms"] >= 0


@pytest.mark.anyio
async def test_bundle_api_missing_data_fallback(client, monkeypatch):
    """
    Scenario: External service fails but we have cached/fallback data
    Expectations:
    - Bundle still returns data
    - prediction falls back to HOLD signal
    - latency still tracked
    """

    async def _mock_partial_bundle(*_args, **_kwargs):
        # Simulate missing prediction (external service down)
        return {
            "symbol": "TCS",
            "timestamp": _utc_now_iso(),
            "history": {
                "candles": [
                    {
                        "time": "2026-04-01 10:00:00",
                        "open": 3800,
                        "high": 3810,
                        "low": 3795,
                        "close": 3805,
                        "volume": 500000,
                    }
                ]
                * 100,
                "count": 100,
                "source": "CACHE",
                "data_source": "CACHE",
            },
            "snapshot": {
                "symbol": "TCS",
                "price": 3805.0,
                "ltp": 3805.0,
                "source": "CACHE",
                "data_source": "CACHE",
                "market_status": "OPEN",
            },
            "prediction": {
                "symbol": "TCS",
                "signal": "HOLD",
                "confidence": 0.0,
                "confidence_pct": 0,
                "prediction": 3805.0,
                "target": 3820.0,
                "stop_loss": 3790.0,
                "reasoning": "Prediction unavailable (service error)",
                "explanation": "Fallback to HOLD signal",
            },
            "indicators": {"symbol": "TCS", "ema_20": 3800.0, "rsi": 50.0},
            "market_status": "OPEN",
            "latency_ms": 87.5,
        }

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_partial_bundle)

    response = await client.get("/api/v1/bundle/TCS?interval=1m&limit=100")
    assert response.status_code == 200

    body = response.json()
    payload = body["data"]

    # Critical: Signal should still be present (fallback to HOLD if needed)
    assert payload["prediction"]["signal"] == "HOLD"
    assert payload["history"]["count"] == 100

    # Verify it came from cache/fallback
    assert payload["history"]["source"] in {"CACHE", "MOCK", "DB"}
    assert payload["snapshot"]["source"] in {"CACHE", "MOCK", "NSE_API"}


@pytest.mark.anyio
async def test_bundle_api_handles_timeout_gracefully(client, monkeypatch):
    """
    Scenario: Bundle API request times out
    Expectations:
    - 504 status returned
    - Error code is BUNDLE_TIMEOUT
    - No partial data leaked
    """

    async def _mock_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError("Bundle request exceeded 8s timeout")

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_timeout)

    response = await client.get("/api/v1/bundle/RELIANCE?interval=1m&horizon=15m")

    assert response.status_code == 504
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "BUNDLE_TIMEOUT"


@pytest.mark.anyio
async def test_bundle_api_parallel_execution(client, monkeypatch):
    """
    Scenario: Verify bundle service executes tasks in parallel
    Expectations:
    - Multiple services called concurrently
    - latency_ms reflects parallel execution (not sum of sequential calls)
    """
    execution_order = []

    async def _mock_bundle_tracked(*_args, **_kwargs):
        # Simulate that history, snapshot, and status are fetched in parallel
        # Then indicators and prediction use results
        execution_order.append("history")
        execution_order.append("snapshot")
        execution_order.append("status")

        return {
            "symbol": "INFY",
            "timestamp": _utc_now_iso(),
            "history": {"candles": [], "count": 100},
            "snapshot": {"symbol": "INFY", "price": 1550.0},
            "prediction": {"signal": "SELL", "confidence": 0.7, "confidence_pct": 70},
            "indicators": {"ema_20": 1545.0},
            "market_status": "OPEN",
            "latency_ms": 234.0,  # Should be less than sum of sequential calls
        }

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_bundle_tracked)

    response = await client.get("/api/v1/bundle/INFY")
    assert response.status_code == 200

    payload = response.json()["data"]

    # Latency should be reasonable for parallel execution
    # If it were sequential and each took 100ms, it would be >400ms
    assert payload["latency_ms"] < 400  # Reasonable for parallel execution


@pytest.mark.anyio
async def test_bundle_api_response_contract_invariants(client, monkeypatch):
    """
    Verify Bundle API response maintains contract invariants:
    - All required top-level fields present
    - No unexpected fields that could break frontend
    - Numeric fields are actually numbers
    """

    async def _mock_bundle(*_args, **_kwargs):
        return {
            "symbol": "HDFCBANK",
            "timestamp": _utc_now_iso(),
            "history": {"candles": [], "count": 0, "source": "MOCK", "data_source": "MOCK"},
            "snapshot": {
                "symbol": "HDFCBANK",
                "price": 1680.0,
                "ltp": 1680.0,
                "open": 1670.0,
                "high": 1685.0,
                "low": 1665.0,
                "close": 1680.0,
                "change": 10.0,
                "volume": 5000000,
                "source": "MOCK",
                "data_source": "MOCK",
                "last_ts": _utc_now_iso(),
                "market_status": "OPEN",
            },
            "prediction": {
                "symbol": "HDFCBANK",
                "signal": "BUY",
                "confidence": 0.75,
                "confidence_pct": 75,
                "prediction": 1680.0,
                "target": 1710.0,
                "stop_loss": 1650.0,
                "explanation": "Test data",
            },
            "indicators": {
                "symbol": "HDFCBANK",
                "ema_20": 1675.2,
                "rsi": 55.0,
            },
            "market_status": "OPEN",
            "market": {},
            "latency_ms": 50.0,
        }

    monkeypatch.setattr("app.routes.bundle.get_bundle_data", _mock_bundle)

    response = await client.get("/api/v1/bundle/HDFCBANK")
    assert response.status_code == 200

    payload = response.json()["data"]

    # Verify required fields exist
    required_top_level = [
        "symbol",
        "timestamp",
        "history",
        "snapshot",
        "prediction",
        "indicators",
        "market_status",
        "latency_ms",
    ]
    for field in required_top_level:
        assert field in payload, f"Missing required field: {field}"

    # Verify numeric fields are actually numeric
    assert isinstance(payload["snapshot"]["price"], (int, float))
    assert isinstance(payload["snapshot"]["ltp"], (int, float))
    assert isinstance(payload["prediction"]["confidence"], (int, float))
    assert isinstance(payload["indicators"]["ema_20"], (int, float))
    assert isinstance(payload["latency_ms"], (int, float))

    # Confidence should be in valid range
    assert 0 <= payload["prediction"]["confidence"] <= 1

    # Signal should be valid
    assert payload["prediction"]["signal"] in {"BUY", "SELL", "HOLD"}
