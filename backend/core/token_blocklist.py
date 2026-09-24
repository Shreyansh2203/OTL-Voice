from __future__ import annotations

import asyncio
import logging
import os
import time
from threading import Lock
from typing import Any, ClassVar, Self, cast

import jwt

logger = logging.getLogger(__name__)


def _redis_required() -> bool:
    return os.getenv("REDIS_REQUIRED", "false").strip().lower() == "true"


class _TokenBlocklist:
    _instance: ClassVar[_TokenBlocklist | None] = None
    _init_lock: ClassVar[Lock] = Lock()
    _local_revoked: dict[str, float]
    _local_lock: asyncio.Lock
    _redis: Any
    _use_redis: bool
    _last_reconnect: float
    _backoff: float

    def __new__(cls) -> Self:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._redis = None
                    cls._instance._use_redis = bool(os.getenv("REDIS_URL"))
                    cls._instance._local_revoked = {}
                    cls._instance._local_lock = asyncio.Lock()
                    cls._instance._last_reconnect = 0.0
                    cls._instance._backoff = 1.0
        return cast(Self, cls._instance)

    def _get_redis(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            self._use_redis = False
            return None
        now = time.time()
        if self._redis is None:
            if now - getattr(self, "_last_reconnect", 0.0) < getattr(
                self, "_backoff", 1.0
            ):
                return None
            self._last_reconnect = now
            try:
                import redis.asyncio as redis

                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._use_redis = True
                self._backoff = 1.0
            except Exception:
                self._use_redis = False
                self._redis = None
                self._backoff = min(60.0, getattr(self, "_backoff", 1.0) * 2)
                logger.warning(
                    "Redis unavailable for token blocklist, falling back to in-memory mode"
                )
        return self._redis

    async def _ensure_redis(self):
        r = self._get_redis()
        if r is not None:
            try:
                await r.ping()
                self._use_redis = True
                self._backoff = 1.0
                return self._redis
            except Exception:
                self._use_redis = False
                if self._redis:
                    try:
                        await self._redis.close()
                    except Exception:
                        pass
                self._redis = None
                self._backoff = min(60.0, getattr(self, "_backoff", 1.0) * 2)
                self._last_reconnect = time.time()
                logger.warning(
                    "Redis ping failed for token blocklist, falling back to in-memory mode"
                )
        return None

    async def _remember_local(self, token: str, exp: float) -> None:
        async with self._local_lock:
            current = time.time()
            expired = [t for t, e in self._local_revoked.items() if e < current]
            for t in expired:
                del self._local_revoked[t]
            self._local_revoked[token] = exp

    async def _is_local_revoked(self, token: str) -> bool:
        async with self._local_lock:
            current = time.time()
            expired = [t for t, exp in self._local_revoked.items() if exp < current]
            for t in expired:
                del self._local_revoked[t]
            return token in self._local_revoked

    async def add(self, token: str) -> None:
        from . import auth

        try:
            payload = jwt.decode(
                token,
                auth._jwt_secret(),
                algorithms=[auth.JWT_ALGORITHM],
                options={"verify_signature": True},
            )
            exp = float(payload.get("exp", time.time() + auth._ttl_seconds()))
        except jwt.PyJWTError:
            return

        ttl = int(max(1, exp - time.time()))

        r = await self._ensure_redis()
        if r:
            try:
                await r.setex(f"revoked:{token}", ttl, "1")
            except Exception:
                self._use_redis = False
                self._redis = None
                self._last_reconnect = time.time()

        await self._remember_local(token, exp)

    async def is_revoked(self, token: str) -> bool:
        if await self._is_local_revoked(token):
            return True

        r = await self._ensure_redis()
        if r:
            try:
                return await r.exists(f"revoked:{token}") > 0
            except Exception:
                self._use_redis = False
                self._redis = None
                self._last_reconnect = time.time()
                return _redis_required()
        return _redis_required()

    async def close(self):
        if self._redis:
            await self._redis.close()
            self._redis = None


_blocklist_instance: _TokenBlocklist | None = None


def _blocklist() -> _TokenBlocklist:
    global _blocklist_instance
    if _blocklist_instance is None:
        _blocklist_instance = _TokenBlocklist()
    return _blocklist_instance
