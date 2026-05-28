"""Authentication flow and contract tests for API v1."""

import asyncio

import pytest

from app import config


@pytest.mark.anyio
async def test_signup_success_returns_token_pair(client, make_user_payload):
    payload = make_user_payload("signup")
    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["token_type"] == "bearer"
    assert "access_token" in body["data"]
    assert "refresh_token" in body["data"]
    assert body["data"]["user"]["email"] == payload["email"]


@pytest.mark.anyio
async def test_signup_duplicate_email_returns_conflict(client, make_user_payload):
    payload = make_user_payload("dup")
    first = await client.post("/api/v1/auth/signup", json=payload)
    assert first.status_code == 201

    second_payload = {
        "password": "SecurePass123",
        "email": payload["email"],
    }
    second = await client.post("/api/v1/auth/signup", json=second_payload)

    assert second.status_code == 409
    body = second.json()
    assert body["status"] == "error"
    assert "Email already registered" in body["message"]


@pytest.mark.anyio
async def test_signup_validation_errors_for_weak_password(client, make_user_payload):
    payload = make_user_payload("weak")
    payload["password"] = "weakpass"

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Request validation failed"
    error_fields = {err["field"] for err in body["data"]["errors"]}
    assert "body.password" in error_fields


@pytest.mark.anyio
async def test_login_is_case_insensitive_for_email(client, make_user_payload):
    payload = make_user_payload("login")
    signup = await client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"].upper(), "password": payload["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["user"]["email"] == payload["email"]


@pytest.mark.anyio
async def test_login_wrong_password_returns_generic_401(client, make_user_payload):
    payload = make_user_payload("badpwd")
    signup = await client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "WrongPass999"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Invalid email or password"


@pytest.mark.anyio
async def test_me_requires_bearer_token(client):
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Not authenticated"


@pytest.mark.anyio
async def test_me_returns_current_user_profile(client, signup_user):
    created = await signup_user("me")
    headers = {"Authorization": f"Bearer {created['tokens']['access_token']}"}

    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["id"] == created["user"]["id"]
    assert body["data"]["email"] == created["request"]["email"]


@pytest.mark.anyio
async def test_refresh_rejects_access_token(client, signup_user):
    created = await signup_user("refresh_type")
    access_token = created["tokens"]["access_token"]

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": access_token}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert "Invalid token type" in body["message"]


@pytest.mark.anyio
async def test_refresh_rotation_invalidates_old_refresh_token(client, signup_user):
    created = await signup_user("refresh_rotate")
    refresh_1 = created["tokens"]["refresh_token"]

    # JWT payload uses second-level timestamps; wait so refreshed token gets a new iat/exp.
    await asyncio.sleep(1.1)

    first_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_1}
    )
    assert first_refresh.status_code == 200
    refresh_2 = first_refresh.json()["data"]["refresh_token"]
    assert refresh_2 != refresh_1

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_1}
    )
    assert replay.status_code == 401
    replay_body = replay.json()
    assert replay_body["status"] == "error"
    assert "already been used" in replay_body["message"]


@pytest.mark.anyio
async def test_logout_invalidates_refresh_token(client, signup_user):
    created = await signup_user("logout")
    headers = {"Authorization": f"Bearer {created['tokens']['access_token']}"}
    refresh = created["tokens"]["refresh_token"]

    logout_response = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert replay.status_code == 401
    body = replay.json()
    assert body["status"] == "error"
    assert "invalid" in body["message"].lower() or "used" in body["message"].lower()


@pytest.mark.anyio
async def test_signup_blocks_sixth_user_in_beta_mode(client, make_user_payload):
    for idx in range(max(1, int(config.MAX_BETA_USERS))):
        payload = make_user_payload(f"cap_{idx}")
        response = await client.post("/api/v1/auth/signup", json=payload)
        assert response.status_code == 201

    overflow = make_user_payload("cap_overflow")
    blocked = await client.post("/api/v1/auth/signup", json=overflow)

    assert blocked.status_code == 403
    body = blocked.json()
    assert body["status"] == "error"
    assert body["message"] == "User limit reached (beta phase)"


@pytest.mark.anyio
async def test_login_expires_in_uses_one_hour_default(client, make_user_payload):
    payload = make_user_payload("expires")
    signup = await client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200

    body = login.json()
    assert body["status"] == "ok"
    assert body["data"]["expires_in"] == int(config.ACCESS_TOKEN_EXPIRE_MINUTES) * 60
