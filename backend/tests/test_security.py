"""Security-focused API tests: auth hardening, injection, and websocket checks."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config
from app.websocket.handler import setup_websocket_routes


@pytest.mark.anyio
async def test_tampered_access_token_is_rejected(client, signup_user):
    created = await signup_user("tamper")
    token = created["tokens"]["access_token"]
    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert "invalid token" in body["message"].lower()


@pytest.mark.anyio
async def test_expired_access_token_is_rejected(client):
    now = datetime.now(tz=timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": "9999",
            "email": "expired_user@example.com",
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(minutes=5),
        },
        config.JWT_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert "expired" in body["message"].lower()


@pytest.mark.anyio
async def test_login_bruteforce_rate_limit_blocks_after_threshold(client):
    headers = {"Origin": "https://stockai-pro.in"}

    for _ in range(5):
        attempt = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown_user@example.com", "password": "WrongPass123"},
            headers=headers,
        )
        assert attempt.status_code == 401

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "unknown_user@example.com", "password": "WrongPass123"},
        headers=headers,
    )
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["status"] == "error"
    assert "too many login attempts" in body["message"].lower()
    allow_origin = blocked.headers.get("access-control-allow-origin")
    assert allow_origin in {"*", headers["Origin"]}
    assert blocked.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.anyio
async def test_signup_rejects_invalid_email_format(client):
    payload = {
        "password": "SecurePass123",
        "email": "' OR 1=1 --",
    }

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Request validation failed"


@pytest.mark.anyio
async def test_signup_rejects_xss_payload_email(client):
    payload = {
        "password": "SecurePass123",
        "email": "<script>alert(1)</script>",
    }

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Request validation failed"


@pytest.mark.anyio
async def test_unhandled_exceptions_are_sanitized(client, monkeypatch):
    async def _raise_secret(*_args, **_kwargs):
        raise RuntimeError("db_password=SUPER_SECRET_VALUE")

    monkeypatch.setattr("app.routes.news.get_cache", _raise_secret)

    headers = {"Origin": "https://stockai-pro.in"}
    response = await client.get("/api/v1/news?symbol=RELIANCE", headers=headers)

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Internal server error"
    assert "SUPER_SECRET_VALUE" not in response.text
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin in {"*", headers["Origin"]}
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.fixture
def websocket_test_app() -> FastAPI:
    """Minimal app containing only websocket routes for auth handshake tests."""
    ws_app = FastAPI()
    setup_websocket_routes(ws_app)
    return ws_app


@pytest.mark.parametrize("path", ["/ws", "/live"])
def test_websocket_rejects_missing_auth_token(path, websocket_test_app):
    with TestClient(websocket_test_app) as test_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect(path):
                pass

    assert exc_info.value.code == 4001


@pytest.mark.parametrize("path", ["/ws", "/live"])
def test_websocket_rejects_invalid_auth_token(path, websocket_test_app):
    with TestClient(websocket_test_app) as test_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect(f"{path}?token=invalid.jwt.token"):
                pass

    assert exc_info.value.code == 4001
