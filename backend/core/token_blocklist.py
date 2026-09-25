from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, ClassVar, Self, cast

import jwt

from .config import memory_fallback_allowed, redis_required

logger = logging.getLogger(__name__)


def _redis_required() -> bool:
    return redis_required()


class SessionStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSession:
    employee_id: str
    username: str
    full_name: str
    expires_at: float

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StoredSession:
        employee_id = value.get("employee_id")
        username = value.get("username")
        full_name = value.get("full_name")
        expires_at = value.get("expires_at")
        if not isinstance(employee_id, str) or not employee_id:
            raise ValueError("invalid employee id")
        if not isinstance(username, str) or not username:
            raise ValueError("invalid username")
        if not isinstance(full_name, str):
            raise TypeError("invalid full name")
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            raise TypeError("invalid expiry")
        return cls(
            employee_id=employee_id,
            username=username,
            full_name=full_name,
            expires_at=float(expires_at),
        )


class _TokenBlocklist:
    _instance: ClassVar[_TokenBlocklist | None] = None
    _init_lock: ClassVar[Lock] = Lock()
    _local_sessions: dict[str, StoredSession]
    _local_revoked: dict[str, float]
    _local_lock: asyncio.Lock
    _redis: Any
    _redis_url: str | None
    _last_reconnect: float
    _backoff: float

    def __new__(cls) -> Self:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._redis = None
                    instance._redis_url = None
                    instance._local_sessions = {}
                    instance._local_revoked = {}
                    instance._local_lock = asyncio.Lock()
                    instance._last_reconnect = 0.0
                    instance._backoff = 1.0
                    cls._instance = instance
        return cast(Self, cls._instance)

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
        self._redis = None
        self._last_reconnect = time.monotonic()
        self._backoff = min(60.0, max(1.0, self._backoff) * 2.0)

    def _get_redis(self) -> Any:
        configured_url = os.getenv("REDIS_URL", "").strip() or None
        if configured_url != self._redis_url:
            self._redis = None
            self._redis_url = configured_url
            self._last_reconnect = 0.0
            self._backoff = 1.0
        if configured_url is None:
            return None
        now = time.monotonic()
        if self._redis is not None:
            return self._redis
        if now - self._last_reconnect < self._backoff:
            return None
        self._last_reconnect = now
        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(configured_url, decode_responses=True)
        except Exception:
            self._mark_redis_failure()
            logger.warning("Redis session store initialization failed")
        return self._redis

    async def _ensure_redis(self) -> Any:
        redis_client = self._get_redis()
        if redis_client is None:
            return None
        try:
            await redis_client.ping()
            self._backoff = 1.0
            return redis_client
        except Exception:
            await self._close_redis()
            self._mark_redis_failure()
            logger.warning("Redis session store health check failed")
            return None

    async def _clean_local(self) -> None:
        now = time.time()
        for session_id, session in list(self._local_sessions.items()):
            if session.expires_at <= now:
                del self._local_sessions[session_id]
        for session_id, expires_at in list(self._local_revoked.items()):
            if expires_at <= now:
                del self._local_revoked[session_id]

    async def _deny_locally(self, session_id: str, ttl_seconds: int) -> None:
        async with self._local_lock:
            await self._clean_local()
            self._local_sessions.pop(session_id, None)
            self._local_revoked[session_id] = time.time() + max(1, ttl_seconds)

    async def _is_locally_denied(self, session_id: str) -> bool:
        async with self._local_lock:
            await self._clean_local()
            return session_id in self._local_revoked

    async def store_session(
        self, session_id: str, session: StoredSession, ttl_seconds: int
    ) -> None:
        redis_client = await self._ensure_redis()
        if redis_client is not None:
            try:
                await redis_client.set(
                    f"session:{session_id}",
                    json.dumps(asdict(session), separators=(",", ":")),
                    ex=max(1, ttl_seconds),
                )
                return
            except Exception:
                await self._close_redis()
                self._mark_redis_failure()
                if not memory_fallback_allowed():
                    raise SessionStoreUnavailable(
                        "The authoritative session store is unavailable."
                    ) from None
        if not memory_fallback_allowed():
            raise SessionStoreUnavailable(
                "Redis is required for session state; no safe fallback is enabled."
            )
        async with self._local_lock:
            await self._clean_local()
            self._local_sessions[session_id] = session
            self._local_revoked.pop(session_id, None)

    async def get_session(self, session_id: str) -> StoredSession | None:
        if await self._is_locally_denied(session_id):
            return None
        redis_client = await self._ensure_redis()
        if redis_client is not None:
            try:
                if await redis_client.exists(f"revoked:{session_id}") > 0:
                    return None
                raw_session = await redis_client.get(f"session:{session_id}")
                if not raw_session:
                    return None
                session = StoredSession.from_dict(json.loads(raw_session))
                if session.expires_at <= time.time():
                    return None
                return session
            except SessionStoreUnavailable:
                raise
            except Exception:
                await self._close_redis()
                self._mark_redis_failure()
                if not memory_fallback_allowed():
                    raise SessionStoreUnavailable(
                        "The authoritative session store is unavailable."
                    ) from None
        if not memory_fallback_allowed():
            raise SessionStoreUnavailable(
                "Redis is required for session state; no safe fallback is enabled."
            )
        async with self._local_lock:
            await self._clean_local()
            if session_id in self._local_revoked:
                return None
            return self._local_sessions.get(session_id)

    async def revoke_session(self, session_id: str, ttl_seconds: int) -> None:
        redis_client = await self._ensure_redis()
        if redis_client is not None:
            try:
                pipeline = redis_client.pipeline(transaction=True)
                pipeline.setex(f"revoked:{session_id}", max(1, ttl_seconds), "1")
                pipeline.delete(f"session:{session_id}")
                await pipeline.execute()
                return
            except Exception:
                await self._close_redis()
                self._mark_redis_failure()
                await self._deny_locally(session_id, ttl_seconds)
                if not memory_fallback_allowed():
                    raise SessionStoreUnavailable(
                        "The authoritative session store is unavailable."
                    ) from None
        if not memory_fallback_allowed():
            await self._deny_locally(session_id, ttl_seconds)
            raise SessionStoreUnavailable(
                "Redis is required for session revocation; no safe fallback is enabled."
            )
        async with self._local_lock:
            await self._clean_local()
            self._local_sessions.pop(session_id, None)
            self._local_revoked[session_id] = time.time() + max(1, ttl_seconds)

    async def add(self, token: str) -> None:
        from . import auth

        try:
            payload = jwt.decode(
                token,
                auth._jwt_secret(),
                algorithms=[auth.JWT_ALGORITHM],
                audience=auth.SESSION_TOKEN_AUDIENCE,
                issuer=auth.SESSION_TOKEN_ISSUER,
                options={"require": ["exp", "jti", "sub", "username"]},
            )
        except jwt.PyJWTError:
            return
        ttl = max(1, int(float(payload["exp"]) - time.time()))
        await self.revoke_session(str(payload["jti"]), ttl)

    async def is_revoked(self, token: str) -> bool:
        from . import auth

        try:
            payload = jwt.decode(
                token,
                auth._jwt_secret(),
                algorithms=[auth.JWT_ALGORITHM],
                audience=auth.SESSION_TOKEN_AUDIENCE,
                issuer=auth.SESSION_TOKEN_ISSUER,
                options={"require": ["exp", "jti", "sub", "username"]},
            )
        except jwt.PyJWTError:
            return True
        session_id = str(payload["jti"])
        if await self._is_locally_denied(session_id):
            return True
        redis_client = await self._ensure_redis()
        if redis_client is not None:
            try:
                return await redis_client.exists(f"revoked:{session_id}") > 0
            except Exception:
                await self._close_redis()
                self._mark_redis_failure()
                if not memory_fallback_allowed():
                    raise SessionStoreUnavailable(
                        "The authoritative session store is unavailable."
                    ) from None
        if not memory_fallback_allowed():
            raise SessionStoreUnavailable(
                "Redis is required for session revocation; no safe fallback is enabled."
            )
        async with self._local_lock:
            await self._clean_local()
            return (
                session_id in self._local_revoked
                or session_id not in self._local_sessions
            )

    async def clear_local(self) -> None:
        async with self._local_lock:
            self._local_sessions.clear()
            self._local_revoked.clear()

    async def close(self) -> None:
        await self._close_redis()
        self._redis_url = None


_blocklist_instance: _TokenBlocklist | None = None


def _blocklist() -> _TokenBlocklist:
    global _blocklist_instance
    if _blocklist_instance is None:
        _blocklist_instance = _TokenBlocklist()
    return _blocklist_instance
