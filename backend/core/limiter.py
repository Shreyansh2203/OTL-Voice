from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict
from contextvars import ContextVar
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

import redis.asyncio as redis

from .config import memory_fallback_allowed, trusted_proxy_networks

logger = logging.getLogger(__name__)

_authenticated_ws_identity: ContextVar[str | None] = ContextVar(
    "authenticated_ws_identity", default=None
)


class RateLimiterUnavailable(RuntimeError):
    pass


def set_authenticated_ws_identity(employee_id: str) -> None:
    normalized = employee_id.strip()
    if normalized:
        _authenticated_ws_identity.set(f"employee:{normalized}")


def clear_authenticated_ws_identity() -> None:
    _authenticated_ws_identity.set(None)


def _rate_limit_key(namespace: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return f"{namespace}:{digest}"


class RateLimiter:
    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
        redis_url: str | None = None,
    ):
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("rate-limit values must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._use_redis = redis_url is not None
        self._local_requests: dict[str, list[float]] = defaultdict(list)
        self._local_lock = asyncio.Lock()
        self._max_local_keys = 10000
        self._last_reconnect_attempt: float = 0.0
        self._reconnect_backoff: float = 1.0

    def _configured_redis_url(self) -> str | None:
        if self.redis_url is not None:
            return self.redis_url.strip() or None
        return os.getenv("REDIS_URL", "").strip() or None

    async def _close_redis(self) -> None:
        redis_client = self._redis
        self._redis = None
        if redis_client is None:
            return
        try:
            await redis_client.close()
        except Exception:
            pass

    def _mark_redis_failure(self) -> None:
        self._use_redis = False
        self._redis = None
        self._last_reconnect_attempt = time.monotonic()
        self._reconnect_backoff = min(60.0, self._reconnect_backoff * 2.0)

    async def _get_redis(self) -> redis.Redis | None:
        url = self._configured_redis_url()
        if not url:
            self._use_redis = False
            return None
        if self._redis is not None:
            return self._redis
        now = time.monotonic()
        if now - self._last_reconnect_attempt < self._reconnect_backoff:
            return None
        self._last_reconnect_attempt = now
        try:
            self._redis = redis.from_url(url, decode_responses=True)
            await self._redis.ping()
            self._use_redis = True
            self._reconnect_backoff = 1.0
        except Exception:
            await self._close_redis()
            self._mark_redis_failure()
            logger.warning("Redis rate-limit store is unavailable")
        return self._redis

    async def _is_allowed_locally(self, key: str) -> bool:
        now = time.time()
        async with self._local_lock:
            active_timestamps = [
                timestamp
                for timestamp in self._local_requests[key]
                if now - timestamp < self.window_seconds
            ]
            if len(self._local_requests) > self._max_local_keys:
                expired_keys = [
                    candidate
                    for candidate, timestamps in self._local_requests.items()
                    if not timestamps or now - timestamps[-1] >= self.window_seconds
                ]
                for candidate in expired_keys:
                    del self._local_requests[candidate]
                overflow = len(self._local_requests) - self._max_local_keys
                if overflow > 0:
                    oldest = sorted(
                        self._local_requests.items(),
                        key=lambda item: item[1][0] if item[1] else now,
                    )
                    for candidate, _ in oldest[:overflow]:
                        del self._local_requests[candidate]
            if len(active_timestamps) >= self.max_requests:
                self._local_requests[key] = active_timestamps
                return False
            active_timestamps.append(now)
            self._local_requests[key] = active_timestamps
            return True

    async def is_allowed(self, key: str) -> bool:
        redis_client = await self._get_redis()
        redis_key = _rate_limit_key("rate-limit", key)
        if redis_client is not None:
            now = time.time()
            window_start = now - self.window_seconds
            try:
                member = f"{now}-{secrets.token_hex(8)}"
                pipeline = redis_client.pipeline()
                pipeline.zremrangebyscore(redis_key, "-inf", window_start)
                pipeline.zadd(redis_key, {member: now})
                pipeline.zcard(redis_key)
                pipeline.expire(redis_key, self.window_seconds + 1)
                results = await pipeline.execute()
                current_count = int(results[2])
                if current_count > self.max_requests:
                    await redis_client.zrem(redis_key, member)
                    return False
                return True
            except Exception:
                await self._close_redis()
                self._mark_redis_failure()
                if not memory_fallback_allowed():
                    raise RateLimiterUnavailable(
                        "The distributed rate-limit store is unavailable."
                    ) from None
        if not memory_fallback_allowed():
            raise RateLimiterUnavailable(
                "Redis is required for rate limiting; no safe fallback is enabled."
            )
        return await self._is_allowed_locally(redis_key)

    async def close(self) -> None:
        await self._close_redis()


def _parse_ip(value: str | None) -> IPv4Address | IPv6Address | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        original = candidate
        closing = original.index("]")
        candidate = original[1:closing]
        remainder = original[closing + 1 :]
        if remainder and not remainder.startswith(":"):
            return None
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.rsplit(":", 1)[0]
    try:
        return ip_address(candidate)
    except ValueError:
        return None


def _is_trusted_proxy(
    address: IPv4Address | IPv6Address,
    networks: tuple[IPv4Network | IPv6Network, ...],
) -> bool:
    return any(
        address.version == network.version and address in network
        for network in networks
    )


def resolve_client_ip(
    peer_host: str | None,
    forwarded_for: str | None = None,
    real_ip: str | None = None,
) -> str:
    peer = _parse_ip(peer_host)
    if peer is None:
        return "unknown"
    networks = trusted_proxy_networks()
    if not _is_trusted_proxy(peer, networks):
        return peer.compressed
    if forwarded_for is not None:
        chain = [_parse_ip(value) for value in forwarded_for.split(",")]
        if any(address is None for address in chain):
            return peer.compressed
        parsed_chain = [address for address in chain if address is not None]
        for address in reversed(parsed_chain):
            if not _is_trusted_proxy(address, networks):
                return address.compressed
        if parsed_chain:
            return parsed_chain[0].compressed
    if real_ip is not None:
        forwarded_address = _parse_ip(real_ip)
        if forwarded_address is not None:
            return forwarded_address.compressed
    return peer.compressed


class WSConnectionTracker:
    def __init__(self, max_connections_per_user: int = 5):
        if max_connections_per_user < 1:
            raise ValueError("WebSocket connection limit must be positive")
        self.max_connections_per_user = max_connections_per_user
        self._connections: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, client_ip: str) -> bool:
        del client_ip
        identity = _authenticated_ws_identity.get()
        if not identity:
            return False
        key = _rate_limit_key("websocket-user", identity)
        async with self._lock:
            if self._connections[key] >= self.max_connections_per_user:
                return False
            self._connections[key] += 1
            return True

    async def release(self, client_ip: str) -> None:
        del client_ip
        identity = _authenticated_ws_identity.get()
        if not identity:
            return
        key = _rate_limit_key("websocket-user", identity)
        async with self._lock:
            if self._connections[key] > 0:
                self._connections[key] -= 1
                if self._connections[key] == 0:
                    del self._connections[key]


def _ws_connection_limit() -> int:
    try:
        value = int(os.getenv("WS_MAX_CONNECTIONS_PER_USER", "5"))
    except ValueError:
        return 5
    return max(1, min(50, value))


ws_tracker = WSConnectionTracker(max_connections_per_user=_ws_connection_limit())
rate_limiter = RateLimiter(max_requests=10000, window_seconds=60)
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


__all__ = [
    "RateLimiter",
    "RateLimiterUnavailable",
    "WSConnectionTracker",
    "auth_rate_limiter",
    "clear_authenticated_ws_identity",
    "rate_limiter",
    "resolve_client_ip",
    "set_authenticated_ws_identity",
    "ws_tracker",
]
