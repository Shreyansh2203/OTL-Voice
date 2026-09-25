import os
from unittest.mock import patch

import pytest

from backend.core.limiter import (
    RateLimiter,
    RateLimiterUnavailable,
    WSConnectionTracker,
    clear_authenticated_ws_identity,
    resolve_client_ip,
    set_authenticated_ws_identity,
)


def test_forwarded_headers_are_ignored_from_untrusted_peers():
    with patch.dict(
        os.environ,
        {"TRUSTED_PROXY_IPS": "", "TRUSTED_PROXY_CIDRS": ""},
        clear=False,
    ):
        assert (
            resolve_client_ip(
                "198.51.100.25",
                "203.0.113.9",
                "203.0.113.10",
            )
            == "198.51.100.25"
        )


def test_trusted_proxy_chain_selects_rightmost_untrusted_address():
    env = {
        "TRUSTED_PROXY_IPS": "10.0.0.5,10.0.0.4",
        "TRUSTED_PROXY_CIDRS": "",
    }
    with patch.dict(os.environ, env, clear=False):
        assert (
            resolve_client_ip(
                "10.0.0.5",
                "203.0.113.7, 198.51.100.2, 10.0.0.4",
            )
            == "198.51.100.2"
        )


def test_trusted_proxy_cidr_and_real_ip_support():
    env = {
        "TRUSTED_PROXY_IPS": "",
        "TRUSTED_PROXY_CIDRS": "10.0.0.0/8,2001:db8:1::/48",
    }
    with patch.dict(os.environ, env, clear=False):
        assert (
            resolve_client_ip("10.20.30.40", None, "198.51.100.44") == "198.51.100.44"
        )
        assert resolve_client_ip("2001:db8:1::9", "2001:db8:2::7") == "2001:db8:2::7"


def test_wildcards_and_malformed_forwarded_values_fail_to_peer():
    env = {
        "TRUSTED_PROXY_IPS": "*",
        "TRUSTED_PROXY_CIDRS": "not-a-network",
    }
    with patch.dict(os.environ, env, clear=False):
        assert resolve_client_ip("10.0.0.5", "203.0.113.7") == "10.0.0.5"
        assert resolve_client_ip("10.0.0.5", "unknown") == "10.0.0.5"


@pytest.mark.asyncio
async def test_websocket_limit_is_per_authenticated_user_not_proxy_ip():
    tracker = WSConnectionTracker(max_connections_per_user=1)
    set_authenticated_ws_identity("10021")
    assert await tracker.acquire("10.0.0.5") is True
    assert await tracker.acquire("203.0.113.7") is False

    set_authenticated_ws_identity("10022")
    assert await tracker.acquire("10.0.0.5") is True
    await tracker.release("10.0.0.5")
    assert await tracker.acquire("10.0.0.5") is True
    set_authenticated_ws_identity("10021")
    assert await tracker.acquire("10.0.0.5") is False


@pytest.mark.asyncio
async def test_resolved_session_arms_websocket_user_quota():
    from backend.core import auth
    from backend.models import Employee

    employee = Employee(
        employee_id="authenticated-user",
        username="authenticated-user",
        full_name="Employee Name",
    )
    token = await auth.issue_session(employee)
    context = await auth.resolve(token)
    assert context is not None
    tracker = WSConnectionTracker(max_connections_per_user=1)
    assert await tracker.acquire("198.51.100.1") is True
    assert await tracker.acquire("10.0.0.5") is False


@pytest.mark.asyncio
async def test_websocket_tracker_rejects_unresolved_identity():
    tracker = WSConnectionTracker(max_connections_per_user=5)
    clear_authenticated_ws_identity()
    assert await tracker.acquire("198.51.100.1") is False


@pytest.mark.asyncio
async def test_memory_rate_limit_requires_explicit_dev_fallback():
    env = {
        "DEV_MODE": "true",
        "TEST_MODE": "false",
        "REDIS_REQUIRED": "false",
        "ALLOW_IN_MEMORY_SESSIONS": "false",
        "REDIS_URL": "",
    }
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(RateLimiterUnavailable):
            await limiter.is_allowed("198.51.100.1")

    env["ALLOW_IN_MEMORY_SESSIONS"] = "true"
    with patch.dict(os.environ, env, clear=False):
        assert await limiter.is_allowed("198.51.100.1") is True
        assert await limiter.is_allowed("198.51.100.1") is False


@pytest.mark.asyncio
async def test_production_rate_limiter_never_uses_memory_fallback():
    env = {
        "DEV_MODE": "false",
        "TEST_MODE": "false",
        "REDIS_REQUIRED": "false",
        "ALLOW_IN_MEMORY_SESSIONS": "true",
        "REDIS_URL": "",
    }
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(RateLimiterUnavailable):
            await limiter.is_allowed("198.51.100.1")
