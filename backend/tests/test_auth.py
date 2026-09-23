import os
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

os.environ["SESSION_SECRET_KEY"] = "test-secret-key-for-testing-only"
from backend.core.auth import (
    JWT_ALGORITHM,
    _jwt_secret,
    create_session,
    current_session,
    destroy,
    resolve,
)
from backend.models import Employee


def test_create_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "123"
    assert payload["username"] == "testuser"
    assert payload["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_resolve():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    ctx = await resolve(token)
    assert ctx is not None
    assert ctx.employee_id == "123"
    assert await resolve(None) is None
    assert await resolve("invalid") is None


@pytest.mark.asyncio
async def test_resolve_expired():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    with patch("backend.core.auth._ttl_seconds", return_value=-10):
        token = create_session(employee)
    assert await resolve(token) is None


@pytest.mark.asyncio
async def test_destroy():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    await destroy(token)
    await destroy(None)


@pytest.mark.asyncio
async def test_current_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    ctx = await current_session(otl_session=token)
    assert ctx.employee_id == "123"
    with pytest.raises(HTTPException) as exc:
        await current_session(otl_session=None)
    assert exc.value.status_code == 401


def test_cookie_secure():
    import os

    from backend.core.auth import cookie_secure

    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
        assert cookie_secure() is False
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
        assert cookie_secure() is True


@pytest.mark.asyncio
async def test_current_session_bearer_header():
    from starlette.requests import Request

    employee = Employee(employee_id="456", username="beareruser", full_name="Bearer User")
    token = create_session(employee)

    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    req = Request(scope)
    ctx = await current_session(request=req, otl_session=None)
    assert ctx.employee_id == "456"
    assert ctx.username == "beareruser"


@pytest.mark.asyncio
async def test_token_blocklist_redis_connect_and_reconnect():
    from unittest.mock import AsyncMock, MagicMock

    from backend.core.auth import _blocklist

    bl = _blocklist()
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.exists = AsyncMock(return_value=1)
    mock_redis.close = AsyncMock()

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}), \
         patch("redis.asyncio.from_url", return_value=mock_redis):
        bl._redis = None
        bl._last_reconnect = 0.0
        r = await bl._ensure_redis()
        assert r is mock_redis
        assert bl._use_redis is True

        # Now simulate connection failure on ping
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis connection refused"))
        bl._last_reconnect = 0.0
        r_fail = await bl._ensure_redis()
        assert r_fail is None
        assert bl._use_redis is False
        assert bl._backoff > 1.0


@pytest.mark.asyncio
async def test_rate_limiter_redis_reconnect():
    from unittest.mock import AsyncMock, MagicMock

    from backend.core.limiter import RateLimiter

    limiter = RateLimiter(max_requests=10, window_seconds=60, redis_url="redis://fake:6379/0")
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        r = await limiter._get_redis()
        assert r is None
        assert limiter._use_redis is False
        assert limiter._reconnect_backoff > 1.0

        # Immediate retry throttled by backoff
        r2 = await limiter._get_redis()
        assert r2 is None

        # When backoff expires and ping succeeds, it recovers
        limiter._last_reconnect_attempt = 0.0
        mock_redis.ping = AsyncMock(return_value=True)
        r3 = await limiter._get_redis()
        assert r3 is mock_redis
        assert limiter._use_redis is True
        assert limiter._reconnect_backoff == 1.0

