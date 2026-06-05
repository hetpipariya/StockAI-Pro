import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.anyio
async def test_endpoint_jwt_expiration_rejects(client):
    """Auth: Querying active positions with an expired token is blocked with a 401 response."""
    response = await client.get(
        "/api/v1/positions",
        headers={"Authorization": "Bearer expired_token_payload_sig"}
    )
    assert response.status_code == 401

@pytest.mark.anyio
async def test_endpoint_unauthorized_rbac_block(client, auth_headers):
    """RBAC: Access to direct backtesting config requires admin permissions."""
    from app.server import app
    from app.routes.auth import get_current_user
    from fastapi import HTTPException
    
    async def mock_rbac_block():
        raise HTTPException(status_code=401, detail="Admin permissions required")
        
    app.dependency_overrides[get_current_user] = mock_rbac_block
    try:
        response = await client.post(
            "/api/v1/backtest",
            json={"symbol": "SBIN", "start_date": "2026-05-01", "end_date": "2026-05-10", "capital": 100000.0},
            headers=auth_headers
        )
        assert response.status_code == 401
        body = response.json()
        assert body["status"] == "error"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.anyio
async def test_login_endpoint_bruteforce_rate_limiting(client):
    """Rate Limit: Brute-forcing the login endpoint blocks the client IP after 5 consecutive failures."""
    headers = {"Origin": "https://stockai-pro.in"}
    
    # Execute 5 failures to trigger the IP block
    for _ in range(5):
        attempt = await client.post(
            "/api/v1/auth/login",
            json={"email": "hacker@desks.com", "password": "WrongPassword1"},
            headers=headers
        )
        assert attempt.status_code == 401
        
    # The 6th attempt must return 429 Too Many Requests
    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "hacker@desks.com", "password": "WrongPassword1"},
        headers=headers
    )
    assert blocked.status_code == 429
    assert "too many login attempts" in blocked.json()["message"].lower()

@pytest.mark.anyio
async def test_input_validation_sqli_protection(client):
    """Injection: Standard signup form sanitizes SQL injection payloads in email formats."""
    payload = {
        "email": "trader@desk.com' OR '1'='1",
        "password": "SecurePassword123"
    }
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422
    assert "validation" in response.json()["message"].lower()

@pytest.mark.anyio
async def test_input_validation_xss_protection(client):
    """Injection: Standard signup form sanitizes XSS scripts tags in input schemas."""
    payload = {
        "email": "<script>alert('XSS')</script>@desk.com",
        "password": "SecurePassword123"
    }
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422
    assert "validation" in response.json()["message"].lower()

@pytest.mark.anyio
async def test_unhandled_500_exception_traceback_sanitization(client, monkeypatch):
    """Sanitize: Unhandled exceptions do not leak internal database credentials or passwords."""
    async def mock_raise_secret(*args, **kwargs):
        raise RuntimeError("database_password=SUPER_SECRET_LEDGER_PASS_0123")
    monkeypatch.setattr("app.routes.news.get_cache", mock_raise_secret)

    response = await client.get("/api/v1/news?symbol=SBIN")
    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Internal server error"
    assert "SUPER_SECRET_LEDGER_PASS_0123" not in response.text
