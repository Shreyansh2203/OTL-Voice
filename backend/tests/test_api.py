import os
from unittest.mock import patch

import pytest

from backend.main import (
    _otl_config_error_handler,
    _otl_error_handler,
)
from backend.services.otl_client import OtlConfigError, OtlError


@pytest.fixture(autouse=True)
def disable_secure_cookies():
    with patch("backend.main.auth.cookie_secure", return_value=False):
        yield


@pytest.mark.asyncio
async def test_otl_error_handler():
    res = await _otl_error_handler(None, OtlError(status_code=400, message="bad"))
    assert res.status_code == 400
    res = await _otl_error_handler(None, OtlError(status_code=500, message="server"))
    assert res.status_code == 502
    res = await _otl_config_error_handler(None, OtlConfigError("bad"))
    assert res.status_code == 500


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_health_otl(auth_client, mock_otl_client):
    mock_otl_client.avalidate.return_value = {"ok": True, "username": "test"}
    assert auth_client.get("/api/health/otl").status_code == 200


def test_session_unauthorized(client):
    assert client.get("/api/auth/session").status_code == 401


def test_login_success(client):
    response = client.post(
        "/api/auth/login", json={"username": "testuser", "password": "dummy-password"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "authenticated"
    assert data["employee"]["username"] == "testuser"
    assert "sessionToken" not in data
    assert "otl_session" in response.headers.get("set-cookie", "").lower()


def test_login_failure(client):
    with patch(
        "backend.api.v1.auth.otl_client.aget_worker", side_effect=Exception("error")
    ):
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "dummy-password"},
        )
        assert response.status_code == 500


def test_login_not_found(client):
    with patch("backend.api.v1.auth.otl_client.aget_worker", return_value=None):
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "dummy-password"},
        )
        assert response.status_code == 401


def test_login_empty_password_rejected(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "208",
        "fullName": "Jessy Brown",
    }
    mock_otl_client.aget_worker.side_effect = None
    response = client.post("/api/auth/login", json={"username": "208", "password": ""})
    assert response.status_code == 401
    assert "password" in response.json()["detail"].lower()


def test_login_invalid_password(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "208",
        "fullName": "Jessy Brown",
    }
    response = client.post(
        "/api/auth/login", json={"username": "208", "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_passwordless_not_found(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = None
    mock_otl_client.aget_worker.side_effect = None
    response = client.post("/api/auth/login", json={"username": "9999", "password": ""})
    assert response.status_code == 401


@pytest.fixture
def auth_client(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "testuser",
        "fullName": "Pytest User",
    }
    mock_otl_client.aget_worker.side_effect = None
    res = client.post(
        "/api/auth/login", json={"username": "testuser", "password": "dummy-password"}
    )
    assert res.status_code == 200
    return client


def test_session_authorized(auth_client):
    assert auth_client.get("/api/auth/session").status_code == 200


def test_logout(auth_client):
    response = auth_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "signed out" in response.json()["status"]


def test_chat_requires_auth(client):
    assert (
        client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        ).status_code
        == 401
    )


def test_chat_stream(auth_client):
    with patch("backend.services.chat.stream_sse") as mock_stream:
        mock_stream.return_value = iter(["data: hello\n\n"])
        response = auth_client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )
        assert response.status_code == 200
        assert "hello" in response.text


def test_logout_clears_cookies(auth_client):
    response = auth_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json()["status"] == "signed out"
    cookies_headers = [
        v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"
    ]
    all_cookies = "; ".join(cookies_headers).lower()
    assert "otl_session" in all_cookies
    assert "csrf_token" in all_cookies
    assert auth_client.get("/api/auth/session").status_code == 401


def test_bearer_token_is_rejected(client):
    from backend.core import auth
    from backend.models import Employee

    emp = Employee(employee_id="999", username="revokeme", full_name="Revoke Me")
    token = auth.create_session(emp)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/session", headers=headers).status_code == 401
    assert client.post("/api/auth/logout", headers=headers).status_code == 200


def test_admin_fail_closed_when_key_unset(auth_client):
    with patch.dict(os.environ, {}, clear=False):
        if "ADMIN_API_KEY" in os.environ:
            del os.environ["ADMIN_API_KEY"]
        res = auth_client.get("/api/admin/catalogue-status")
        assert res.status_code == 403
        assert res.json()["detail"] == "Admin key not configured"


def test_admin_rejects_invalid_key(auth_client):
    with patch.dict(os.environ, {"ADMIN_API_KEY": "supersecretkey"}):
        res = auth_client.get(
            "/api/admin/catalogue-status",
            headers={"X-Admin-Key": "wrongkey"},
        )
        assert res.status_code == 403
        assert res.json()["detail"] == "Admin key required."


def test_admin_allows_valid_key(auth_client):
    with patch.dict(os.environ, {"ADMIN_API_KEY": "supersecretkey"}):
        res = auth_client.get(
            "/api/admin/catalogue-status",
            headers={"X-Admin-Key": "supersecretkey"},
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_auth_rate_limiting(client):
    from backend.core.limiter import RateLimiter, auth_rate_limiter

    assert auth_rate_limiter.max_requests == 10
    auth_rate_limiter._local_requests.clear()
    try:
        with patch.dict(os.environ, {"TEST_MODE": "false"}):
            headers = {"Authorization": "Bearer test-csrf-bypass"}
            for _ in range(10):
                res = client.post(
                    "/api/auth/login",
                    json={"username": "testuser", "password": "wrong"},
                    headers=headers,
                )
                assert res.status_code == 401
            res = client.post(
                "/api/auth/login",
                json={"username": "testuser", "password": "wrong"},
                headers=headers,
            )
            assert res.status_code == 429
            assert "Too many requests" in res.json()["detail"]

        # Also directly test unit logic of RateLimiter
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        for _ in range(10):
            assert await limiter.is_allowed("unit_test_ip") is True
        assert await limiter.is_allowed("unit_test_ip") is False
    finally:
        auth_rate_limiter._local_requests.clear()
