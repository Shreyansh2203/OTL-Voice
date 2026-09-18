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
    assert response.json()["username"] == "testuser"
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


def test_login_passwordless_success(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "208",
        "fullName": "Jessy Brown",
    }
    mock_otl_client.aget_worker.side_effect = None
    response = client.post("/api/auth/login", json={"username": "208", "password": ""})
    assert response.status_code == 200
    assert response.json()["fullName"] == "Jessy Brown"
    assert response.json()["username"] == "208"


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
