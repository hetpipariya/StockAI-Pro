import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.anyio
async def test_order_proxy_success_paper(client, auth_headers):
    """Success: Placing a paper order returns successful simulation payload."""
    payload = {
        "symbol": "SBIN",
        "transactiontype": "BUY",
        "quantity": 10,
        "ordertype": "MARKET",
        "mode": "paper"
    }
    response = await client.post("/api/order", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] is True
    assert "PAPER_ORDER_SIMULATED" in body["message"]
    assert "orderid" in body

@pytest.mark.anyio
async def test_order_proxy_unauthorized(client):
    """Auth: Querying order endpoint without headers returns 401."""
    payload = {
        "symbol": "SBIN",
        "transactiontype": "BUY",
        "quantity": 10,
        "mode": "paper"
    }
    response = await client.post("/api/order", json=payload)
    assert response.status_code == 401

@pytest.mark.anyio
async def test_order_proxy_validation_failure(client, auth_headers):
    """Validation: Invalid transaction types return 422 schema errors."""
    payload = {
        "symbol": "SBIN",
        "transactiontype": "INVALID_TYPE",
        "quantity": 10,
        "mode": "paper"
    }
    response = await client.post("/api/order", json=payload, headers=auth_headers)
    assert response.status_code == 422

@pytest.mark.anyio
async def test_portfolio_balance_success(client, auth_headers, monkeypatch):
    """Success: Fetches active portfolio balance and margin metrics."""
    async def mock_get_balance(*args, **kwargs):
        return {
            "user_id": 1,
            "available_balance": 100000.0,
            "equity": 100000.0,
            "realized_pnl": 250.0,
            "unrealized_pnl": 0.0,
            "gross_exposure": 0.0,
            "open_positions": 0,
            "can_trade": True,
            "can_trade_reason": "Margin limits normal",
            "trading_halted": False,
            "as_of": "2026-05-29T15:00:00Z"
        }
    monkeypatch.setattr("app.routes.portfolio.get_portfolio_balance_data", mock_get_balance)

    response = await client.get("/api/v1/portfolio/balance", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["equity"] == 100000.0

@pytest.mark.anyio
async def test_portfolio_balance_unauthorized(client):
    """Auth: Querying portfolio balance without JWT returns 401."""
    response = await client.get("/api/v1/portfolio/balance")
    assert response.status_code == 401

@pytest.mark.anyio
async def test_positions_alias_endpoint(client, auth_headers, monkeypatch):
    """Success: Fetches scoped positions for active user."""
    async def mock_get_active(*args, **kwargs):
        return {
            "positions": [],
            "positions_count": 0,
            "as_of": "2026-05-29T15:00:00Z"
        }
    monkeypatch.setattr("app.routes.trade_api.get_active_trades_data", mock_get_active)

    response = await client.get("/api/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "positions" in body["data"]

@pytest.mark.anyio
async def test_market_instruments_search_success(client, monkeypatch):
    """Success: Searching active trading symbols suggestions."""
    def mock_search(*args, **kwargs):
        return [{"symbol": "RELIANCE", "token": "2885", "exchange": "NSE"}]
    def mock_suggest(*args, **kwargs):
        return ["RELIANCE"]
    
    monkeypatch.setattr("app.routes.instruments.search_symbols", mock_search)
    monkeypatch.setattr("app.routes.instruments.suggest_symbols", mock_suggest)

    response = await client.get("/api/v1/instruments/search?symbol=RELI")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "RELI"
    assert len(body["results"]) == 1
    assert body["results"][0]["symbol"] == "RELIANCE"

@pytest.mark.anyio
async def test_market_instruments_token_not_found(client, monkeypatch):
    """Failure: Querying token for invalid symbol returns 404."""
    def mock_get_token(*args, **kwargs):
        raise KeyError("Symbol not found: INVALID_SYM")
    monkeypatch.setattr("app.routes.instruments.get_token_by_symbol", mock_get_token)

    response = await client.get("/api/v1/instruments/token?symbol=INVALID_SYM")
    assert response.status_code == 404

@pytest.mark.anyio
async def test_signals_endpoint_success(client, auth_headers, monkeypatch):
    """Success: Fetches calculated active trading signals."""
    async def mock_get_signals(*args, **kwargs):
        return {
            "signals": [
                {
                    "symbol": "SBIN",
                    "signal": "BUY",
                    "confidence": 0.85,
                    "confidence_pct": 85,
                    "prediction": 1.0,
                    "target": 670.0,
                    "stop_loss": 645.0,
                    "horizon": "15m",
                    "timestamp": "2026-05-29T15:00:00Z",
                    "source": "ML_ENSEMBLE"
                }
            ],
            "count": 1,
            "as_of": "2026-05-29T15:00:00Z"
        }
    monkeypatch.setattr("app.routes.signals.get_signals_data", mock_get_signals)

    response = await client.get("/api/v1/signals", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert len(body["data"]["signals"]) == 1
    assert body["data"]["signals"][0]["symbol"] == "SBIN"

@pytest.mark.anyio
async def test_trades_active_endpoint_success(client, auth_headers, monkeypatch):
    """Success: Queries direct active trades logged inside database."""
    async def mock_get_active(*args, **kwargs):
        return {
            "user_id": 1,
            "positions": [],
            "pending_orders": [],
            "positions_count": 0,
            "pending_orders_count": 0,
            "as_of": "2026-05-29T15:00:00Z"
        }
    monkeypatch.setattr("app.routes.trades.get_active_trades_data", mock_get_active)

    response = await client.get("/api/v1/trades/active", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
