"""Multi-user isolation and protected endpoint coverage tests."""

from datetime import datetime

import pytest

from app.services.db import OrderModel, PositionModel, TradeLogModel


@pytest.mark.anyio
async def test_kill_switch_isolated_per_user(client, signup_user):
    user_1 = await signup_user("iso1")
    user_2 = await signup_user("iso2")

    headers_1 = {"Authorization": f"Bearer {user_1['tokens']['access_token']}"}
    headers_2 = {"Authorization": f"Bearer {user_2['tokens']['access_token']}"}

    disable = await client.post("/api/v1/trading/kill-switch?enable=false", headers=headers_1)
    assert disable.status_code == 200
    assert disable.json()["user_halted"] is True

    risk_1 = await client.get("/api/v1/trading/risk", headers=headers_1)
    risk_2 = await client.get("/api/v1/trading/risk", headers=headers_2)

    assert risk_1.status_code == 200
    assert risk_2.status_code == 200
    assert risk_1.json()["is_halted"] is True
    assert risk_2.json()["is_halted"] is False


@pytest.mark.anyio
async def test_positions_orders_and_logs_are_filtered_by_user(client, signup_user, db_session):
    user_1 = await signup_user("scope1")
    user_2 = await signup_user("scope2")

    headers_1 = {"Authorization": f"Bearer {user_1['tokens']['access_token']}"}
    headers_2 = {"Authorization": f"Bearer {user_2['tokens']['access_token']}"}

    now = datetime.utcnow()
    db_session.add_all(
        [
            PositionModel(
                user_id=user_1["user"]["id"],
                symbol="ALPHA",
                direction="BUY",
                quantity=10,
                entry_price=100.0,
                stop_loss=95.0,
                target=110.0,
                mode="paper",
                opened_at=now,
            ),
            PositionModel(
                user_id=user_2["user"]["id"],
                symbol="BETA",
                direction="SELL",
                quantity=6,
                entry_price=220.0,
                stop_loss=230.0,
                target=205.0,
                mode="paper",
                opened_at=now,
            ),
            OrderModel(
                user_id=user_1["user"]["id"],
                order_id="U1-ORDER-1",
                symbol="ALPHA",
                transaction_type="BUY",
                quantity=10,
                filled_quantity=10,
                price=100.0,
                stop_loss=95.0,
                target=110.0,
                status="FILLED",
                mode="paper",
                confidence=70,
                reason="test",
                timestamp=now,
            ),
            OrderModel(
                user_id=user_2["user"]["id"],
                order_id="U2-ORDER-1",
                symbol="BETA",
                transaction_type="SELL",
                quantity=6,
                filled_quantity=6,
                price=220.0,
                stop_loss=230.0,
                target=205.0,
                status="FILLED",
                mode="paper",
                confidence=75,
                reason="test",
                timestamp=now,
            ),
            TradeLogModel(
                user_id=user_1["user"]["id"],
                event="OPEN",
                order_id="U1-ORDER-1",
                symbol="ALPHA",
                direction="BUY",
                quantity=10,
                price=100.0,
                status="FILLED",
                mode="paper",
                timestamp=now,
            ),
            TradeLogModel(
                user_id=user_2["user"]["id"],
                event="OPEN",
                order_id="U2-ORDER-1",
                symbol="BETA",
                direction="SELL",
                quantity=6,
                price=220.0,
                status="FILLED",
                mode="paper",
                timestamp=now,
            ),
        ]
    )
    await db_session.commit()

    u1_positions = await client.get("/api/v1/trading/positions", headers=headers_1)
    u2_positions = await client.get("/api/v1/trading/positions", headers=headers_2)
    assert u1_positions.status_code == 200
    assert u2_positions.status_code == 200
    assert [p["symbol"] for p in u1_positions.json()["positions"]] == ["ALPHA"]
    assert [p["symbol"] for p in u2_positions.json()["positions"]] == ["BETA"]

    u1_orders = await client.get("/api/v1/trading/orders", headers=headers_1)
    u2_orders = await client.get("/api/v1/trading/orders", headers=headers_2)
    assert u1_orders.status_code == 200
    assert u2_orders.status_code == 200
    assert [o["symbol"] for o in u1_orders.json()["orders"]] == ["ALPHA"]
    assert [o["symbol"] for o in u2_orders.json()["orders"]] == ["BETA"]

    u1_logs = await client.get("/api/v1/trading/logs", headers=headers_1)
    u2_logs = await client.get("/api/v1/trading/logs", headers=headers_2)
    assert u1_logs.status_code == 200
    assert u2_logs.status_code == 200
    assert [l["symbol"] for l in u1_logs.json()["logs"]] == ["ALPHA"]
    assert [l["symbol"] for l in u2_logs.json()["logs"]] == ["BETA"]


@pytest.mark.anyio
async def test_execute_trade_requires_symbol_query_with_auth(client, signup_user):
    user = await signup_user("exec")
    headers = {"Authorization": f"Bearer {user['tokens']['access_token']}"}

    response = await client.post("/api/v1/trading/execute", headers=headers)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Request validation failed"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/api/v1/auth/me", None),
        ("POST", "/api/v1/auth/logout", None),
        ("POST", "/api/v1/backtest", {"symbol": "RELIANCE", "start_date": "2026-01-01", "end_date": "2026-01-05", "capital": 100000}),
        ("GET", "/api/v1/trading/status", None),
        ("GET", "/api/v1/trading/risk", None),
        ("GET", "/api/v1/trading/safety", None),
        ("GET", "/api/v1/trading/positions", None),
        ("GET", "/api/v1/trading/orders", None),
        ("GET", "/api/v1/trading/logs", None),
        ("GET", "/api/v1/trading/candles?symbol=RELIANCE", None),
        ("POST", "/api/v1/trading/execute?symbol=RELIANCE", None),
        ("POST", "/api/v1/trading/kill-switch?enable=true", None),
        ("POST", "/api/v1/trading/confirm/ORDER-TEST", None),
    ],
)
async def test_protected_endpoints_require_authentication(client, method, path, payload):
    if method == "GET":
        response = await client.get(path)
    else:
        response = await client.post(path, json=payload)

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert "authenticated" in body["message"].lower() or "token" in body["message"].lower()
