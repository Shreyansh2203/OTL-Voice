from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60, redis_url: str | None = None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self._redis: redis.Redis | None = None
        self._use_redis = self.redis_url is not None
        self._local_requests: dict[str, list[float]] = defaultdict(list)
        self._local_lock = asyncio.Lock()
        self._max_local_keys = 10000

    async def _get_redis(self) -> redis.Redis | None:
        if not self._use_redis:
            return None
        if self._redis is None:
            if not self.redis_url:
                self._use_redis = False
                return None
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception:
                self._use_redis = False
                self._redis = None
                logger.warning("Redis unavailable for rate limiter, falling back to in-memory mode")
        return self._redis

    async def is_allowed(self, key: str) -> bool:
        r = await self._get_redis()
        now = time.time()
        window_start = now - self.window_seconds
        if r is not None:
            try:
                member = f"{now}-{time.perf_counter()}"
                pipe = r.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zadd(key, {member: now})
                pipe.expire(key, self.window_seconds + 1)
                results = await pipe.execute()
                current_count = results[1]
                if current_count > self.max_requests:
                    await r.zrem(key, member)
                    return False
                return True
            except Exception:
                pass
        async with self._local_lock:
            self._local_requests[key] = [t for t in self._local_requests[key] if now - t < self.window_seconds]
            if len(self._local_requests) > self._max_local_keys:
                sorted_keys = sorted(
                    self._local_requests.items(),
                    key=lambda kv: kv[1][0] if kv[1] else now,
                )
                for k, _ in sorted_keys[: len(self._local_requests) - self._max_local_keys]:
                    del self._local_requests[k]
            if len(self._local_requests[key]) >= self.max_requests:
                return False
            self._local_requests[key].append(now)
            return True

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()


class WSConnectionTracker:
    def __init__(self, max_connections_per_ip: int = 5):
        self.max_connections_per_ip = max_connections_per_ip
        self._connections: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, client_ip: str) -> bool:
        async with self._lock:
            if self._connections[client_ip] >= self.max_connections_per_ip:
                return False
            self._connections[client_ip] += 1
            return True

    async def release(self, client_ip: str) -> None:
        async with self._lock:
            if self._connections[client_ip] > 0:
                self._connections[client_ip] -= 1
                if self._connections[client_ip] == 0:
                    del self._connections[client_ip]


ws_tracker = WSConnectionTracker(max_connections_per_ip=5)
rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

