import os
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

os.environ["SESSION_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["TEST_MODE"] = "true"
os.environ["DEV_MODE"] = "true"
os.environ["AUTH_PASSWORD"] = "dummy-password"
os.environ["ALLOW_IN_MEMORY_SESSIONS"] = "true"
os.environ["REDIS_REQUIRED"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["SESSION_COOKIE_SECURE"] = "false"

from backend.core.auth import (
    JWT_ALGORITHM,
    SESSION_TOKEN_AUDIENCE,
    SESSION_TOKEN_ISSUER,
    _jwt_secret,
    create_session,
    current_session,
    destroy,
    issue_session,
    resolve,
)
from backend.models import Employee


def test_create_session_uses_minimal_identity_claims():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    payload = jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        audience=SESSION_TOKEN_AUDIENCE,
        issuer=SESSION_TOKEN_ISSUER,
    )
    assert payload["sub"] == "123"
    assert payload["username"] == "testuser"
    assert "full_name" not in payload
    assert set(payload) == {
        "sub",
        "username",
        "iss",
        "aud",
        "iat",
        "exp",
        "jti",
    }


@pytest.mark.asyncio
async def test_resolve_requires_active_server_side_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    assert await resolve(token) is None
    token = await issue_session(employee)
    context = await resolve(token)
    assert context is not None
    assert context.employee_id == "123"
    assert context.full_name == "Test User"
    assert await resolve(None) is None
    assert await resolve("invalid") is None


@pytest.mark.asyncio
async def test_resolve_expired():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    with patch("backend.core.auth._ttl_seconds", return_value=-10):
        token = create_session(employee)
    assert await resolve(token) is None


@pytest.mark.asyncio
async def test_destroy_revokes_active_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = await issue_session(employee)
    assert await resolve(token) is not None
    await destroy(token)
    assert await resolve(token) is None
    await destroy(None)
    await destroy("invalid")


@pytest.mark.asyncio
async def test_current_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = await issue_session(employee)
    context = await current_session(otl_session=token)
    assert context.employee_id == "123"
    with pytest.raises(HTTPException) as exc:
        await current_session(otl_session=None)
    assert exc.value.status_code == 401


def test_cookie_secure():
    from backend.core.auth import cookie_secure

    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
        assert cookie_secure() is False
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
        assert cookie_secure() is True


def test_auth_exposes_token_blocklist_accessor():
    from backend.core import auth
    from backend.core.token_blocklist import _blocklist

    assert auth._blocklist is _blocklist


@pytest.mark.asyncio
async def test_token_blocklist_redis_connect_and_reconnect():
    from backend.core.auth import _blocklist

    blocklist = _blocklist()
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.close = AsyncMock()

    with (
        patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}),
        patch("redis.asyncio.from_url", return_value=mock_redis),
    ):
        blocklist._redis = None
        blocklist._redis_url = None
        blocklist._last_reconnect = 0.0
        redis_client = await blocklist._ensure_redis()
        assert redis_client is mock_redis

        mock_redis.ping = AsyncMock(side_effect=Exception("Redis unavailable"))
        blocklist._last_reconnect = 0.0
        redis_client = await blocklist._ensure_redis()
        assert redis_client is None
        assert blocklist._backoff > 1.0


@pytest.mark.asyncio
async def test_rate_limiter_redis_reconnect():
    from backend.core.limiter import RateLimiter

    limiter = RateLimiter(
        max_requests=10, window_seconds=60, redis_url="redis://fake:6379/0"
    )
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))
    mock_redis.close = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        assert await limiter._get_redis() is None
        assert limiter._use_redis is False
        assert limiter._reconnect_backoff > 1.0
        assert await limiter._get_redis() is None

        limiter._last_reconnect_attempt = 0.0
        mock_redis.ping = AsyncMock(return_value=True)
        redis_client = await limiter._get_redis()
        assert redis_client is mock_redis
        assert limiter._use_redis is True
        assert limiter._reconnect_backoff == 1.0
        await limiter.close()
