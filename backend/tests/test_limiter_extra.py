import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.limiter import (
    RateLimiter,
    WSConnectionTracker,
    _parse_ip,
    _rate_limit_key,
    clear_authenticated_ws_identity,
    resolve_client_ip,
    set_authenticated_ws_identity,
)


def test_rate_limiter_invalid_max_requests():
    """Cover limiter.py:50-51 - constructor validation."""
    with pytest.raises(ValueError, match="rate-limit values must be positive"):
        RateLimiter(max_requests=0, window_seconds=60)
    with pytest.raises(ValueError, match="rate-limit values must be positive"):
        RateLimiter(max_requests=10, window_seconds=0)


def test_rate_limit_key():
    """Cover limiter.py:38-40 - _rate_limit_key."""
    key1 = _rate_limit_key("ns", "value1")
    key2 = _rate_limit_key("ns", "value1")
    key3 = _rate_limit_key("ns", "value2")
    assert key1 == key2
    assert key1 != key3
    assert key1.startswith("ns:")


def test_close_redis_exception_handling():
    """Cover limiter.py:73-76 - _close_redis exception swallowed."""

    limiter = RateLimiter(max_requests=10, window_seconds=60)
    mock_redis = MagicMock()
    mock_redis.close = AsyncMock(side_effect=Exception("close failed"))
    limiter._redis = mock_redis
    # Should not raise
    asyncio.run(limiter._close_redis())


def test_get_redis_returns_existing_client():
    """Cover limiter.py:89-90 - _get_redis returns existing client."""

    limiter = RateLimiter(
        max_requests=10, window_seconds=60, redis_url="redis://localhost:6379/0"
    )
    mock_redis = MagicMock()
    limiter._redis = mock_redis
    result = asyncio.run(limiter._get_redis())
    assert result is mock_redis


def test_mark_redis_failure():
    """Cover limiter.py:78-82 - _mark_redis_failure."""

    limiter = RateLimiter(
        max_requests=10, window_seconds=60, redis_url="redis://localhost:6379/0"
    )
    limiter._use_redis = True
    limiter._redis = MagicMock()
    limiter._mark_redis_failure()
    assert limiter._use_redis is False
    assert limiter._redis is None
    assert limiter._reconnect_backoff == 2.0


def test_local_key_eviction_when_over_max():
    """Cover limiter.py:114-129 - local key eviction when over max_local_keys."""

    limiter = RateLimiter(max_requests=1000, window_seconds=60)
    limiter._max_local_keys = 3
    # Fill up with old keys
    now = time.time()
    for i in range(5):
        limiter._local_requests[f"key-{i}"] = [now - 100]  # old timestamps
    # Now add a new key - should trigger eviction
    result = asyncio.run(limiter._is_allowed_locally("new-key"))
    assert result is True
    # Old keys should have been evicted
    assert "key-0" not in limiter._local_requests or len(limiter._local_requests) <= 3


@pytest.mark.asyncio
async def test_redis_pipeline_rate_limit_allows():
    """Cover limiter.py:141-155 - Redis pipeline rate limit allows request."""

    limiter = RateLimiter(
        max_requests=10, window_seconds=60, redis_url="redis://localhost:6379/0"
    )
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
    mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
    mock_pipeline.execute = AsyncMock(return_value=[None, None, None, 1, None])
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.zrem = AsyncMock()

    limiter._redis = mock_redis
    limiter._use_redis = True

    with patch.dict(os.environ, {"ALLOW_IN_MEMORY_SESSIONS": "true"}, clear=False):
        result = await limiter.is_allowed("test-key")
    assert result is True


@pytest.mark.asyncio
async def test_redis_pipeline_rate_limit_rejects():
    """Cover limiter.py:152-154 - Redis pipeline rejects when over limit."""

    limiter = RateLimiter(
        max_requests=1, window_seconds=60, redis_url="redis://localhost:6379/0"
    )
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
    mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
    mock_pipeline.execute = AsyncMock(return_value=[None, None, 2, None, None])
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.zrem = AsyncMock()

    limiter._redis = mock_redis
    limiter._use_redis = True

    with patch.dict(os.environ, {"ALLOW_IN_MEMORY_SESSIONS": "true"}, clear=False):
        result = await limiter.is_allowed("test-key")
    assert result is False


def test_parse_ip_bracket_ipv6_with_remainder():
    """Cover limiter.py:179-185 - _parse_ip bracket IPv6 with invalid remainder."""
    # Valid bracket IPv6
    result = _parse_ip("[2001:db8::1]")
    assert result is not None
    # Bracket IPv6 with remainder not starting with colon
    result = _parse_ip("[2001:db8::1]rest")
    assert result is None


def test_parse_ip_ipv4_with_port():
    """Cover limiter.py:186-187 - _parse_ip IPv4 with port."""
    result = _parse_ip("192.168.1.1:8080")
    assert result is not None
    assert str(result) == "192.168.1.1"


def test_resolve_client_ip_forwarded_with_none_address():
    """Cover limiter.py:217-218 - forwarded_for chain with None address."""
    with patch.dict(
        os.environ,
        {"TRUSTED_PROXY_IPS": "10.0.0.5", "TRUSTED_PROXY_CIDRS": ""},
        clear=False,
    ):
        # forwarded_for contains an unparseable address
        result = resolve_client_ip("10.0.0.5", "invalid,,203.0.113.7")
        assert result == "10.0.0.5"


def test_resolve_client_ip_real_ip_fallback():
    """Cover limiter.py:225-229 - real_ip fallback when peer trusted but forwarders unusable."""
    with patch.dict(
        os.environ,
        {"TRUSTED_PROXY_IPS": "198.51.100.1", "TRUSTED_PROXY_CIDRS": ""},
        clear=False,
    ):
        # Peer IS trusted, forwarded_for is None, so real_ip is used
        result = resolve_client_ip("198.51.100.1", None, "10.0.0.1")
        assert result == "10.0.0.1"


def test_ws_tracker_invalid_max_connections():
    """Cover limiter.py:234-235 - WSConnectionTracker max_connections validation."""
    with pytest.raises(ValueError, match="WebSocket connection limit must be positive"):
        WSConnectionTracker(max_connections_per_user=0)


@pytest.mark.asyncio
async def test_ws_tracker_release_removes_key_when_zero():
    """Cover limiter.py:258-262 - WSConnectionTracker release deletes key at zero."""
    tracker = WSConnectionTracker(max_connections_per_user=1)
    set_authenticated_ws_identity("user-1")
    assert await tracker.acquire("10.0.0.1") is True
    await tracker.release("10.0.0.1")
    # Key should be deleted from _connections
    assert (
        "websocket-user:" not in str(tracker._connections) or tracker._connections == {}
    )
    # Can acquire again
    assert await tracker.acquire("10.0.0.1") is True
    clear_authenticated_ws_identity()


def test_ws_connection_limit_env_invalid():
    """Cover limiter.py:267-269 - _ws_connection_limit invalid env value."""
    import backend.core.limiter as limiter_mod

    with patch.dict(
        os.environ, {"WS_MAX_CONNECTIONS_PER_USER": "not-a-number"}, clear=False
    ):
        limit = limiter_mod._ws_connection_limit()
        assert limit == 5


def test_ws_connection_limit_env_bounds():
    """Cover limiter.py:269 - _ws_connection_limit clamps to bounds."""
    import backend.core.limiter as limiter_mod

    with patch.dict(os.environ, {"WS_MAX_CONNECTIONS_PER_USER": "100"}, clear=False):
        limit = limiter_mod._ws_connection_limit()
        assert limit == 50  # clamped to max

    with patch.dict(os.environ, {"WS_MAX_CONNECTIONS_PER_USER": "0"}, clear=False):
        limit = limiter_mod._ws_connection_limit()
        assert limit == 1  # clamped to min
