from __future__ import annotations
import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import ClassVar
from fastapi import Cookie, HTTPException, status
from ..models import Employee
logger = logging.getLogger(__name__)
SESSION_COOKIE_NAME = "otl_session"
def _session_cookie_name() -> str:
    return f"__Host-{SESSION_COOKIE_NAME}" if cookie_secure() else SESSION_COOKIE_NAME
def _ttl_seconds() -> int:
    return int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))  
def cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "true").strip().lower() != "false"
import jwt
JWT_ALGORITHM = "HS256"
def _jwt_secret() -> str:
    secret = os.getenv("SESSION_SECRET_KEY")
    test_mode = os.getenv("TEST_MODE", "false").strip().lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "false").strip().lower() == "true"
    if not secret:
        if test_mode or dev_mode:
            logger.warning(
                "SESSION_SECRET_KEY not set - generating temporary secret for development. "
                "Set SESSION_SECRET_KEY in .env for production use!"
            )
            secret = secrets.token_urlsafe(32)
        else:
            raise RuntimeError(
                "SESSION_SECRET_KEY is not set. "
                "This environment variable is REQUIRED for production use. "
                "Generate a secret with: python -c \"import secrets; print(secrets.token_urlsafe(32))\" "
                "and add it to your .env file. "
                "For local development only, you can set DEV_MODE=true or TEST_MODE=true to allow a temporary secret."
            )
    return secret
class _TokenBlocklist:
    _instance: ClassVar[_TokenBlocklist | None] = None
    _init_lock: ClassVar[Lock] = Lock()
    _local_revoked: dict[str, float]
    _local_lock: asyncio.Lock
    def __new__(cls) -> _TokenBlocklist:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._redis = None
                    cls._instance._use_redis = False
                    cls._instance._local_revoked = {}
                    cls._instance._local_lock = asyncio.Lock()
        return cls._instance
    def _get_redis(self):
        if not self._use_redis:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as redis
                redis_url = os.getenv("REDIS_URL")
                if redis_url:
                    self._redis = redis.from_url(redis_url, decode_responses=True)
            except Exception:
                self._use_redis = False
                self._redis = None
                logger.warning("Redis unavailable for token blocklist, falling back to in-memory mode")
        return self._redis
    async def _ensure_redis(self):
        r = self._get_redis()
        if r:
            try:
                await r.ping()
                self._use_redis = True
            except Exception:
                self._use_redis = False
                self._redis = None
    async def add(self, token: str) -> None:
        r = await self._ensure_redis()
        if r:
            try:
                try:
                    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM], options={"verify_signature": False})
                    exp = float(payload.get("exp", time.time() + _ttl_seconds()))
                except jwt.PyJWTError:
                    exp = float(time.time() + _ttl_seconds())
                ttl = max(1, exp - int(time.time()))
                await r.setex(f"revoked:{token}", ttl, "1")
                return
            except Exception:
                pass  
        async with self._local_lock:
            try:
                payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM], options={"verify_signature": False})
                exp = float(payload.get("exp", time.time() + _ttl_seconds()))
            except jwt.PyJWTError:
                exp = float(time.time() + _ttl_seconds())
            current = time.time()
            expired = [t for t, e in self._local_revoked.items() if e < current]
            for t in expired:
                del self._local_revoked[t]
            self._local_revoked[token] = exp
    async def is_revoked(self, token: str) -> bool:
        r = await self._ensure_redis()
        if r:
            try:
                return await r.exists(f"revoked:{token}") > 0
            except Exception:
                pass  
        async with self._local_lock:
            current = time.time()
            expired = [t for t, exp in self._local_revoked.items() if exp < current]
            for t in expired:
                del self._local_revoked[t]
            return token in self._local_revoked
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
@dataclass(frozen=True)
class SessionContext:
    employee_id: str  
    username: str
    full_name: str  
def create_session(employee: Employee) -> str:
    payload = {
        "sub": employee.employee_id,
        "username": employee.username,
        "full_name": employee.full_name,
        "exp": time.time() + _ttl_seconds(),
        "iat": time.time(),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
async def resolve(token: str | None) -> SessionContext | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        if await _blocklist().is_revoked(token):
            return None
        return SessionContext(
            employee_id=payload["sub"],
            username=payload["username"],
            full_name=payload["full_name"],
        )
    except jwt.PyJWTError:
        return None
async def destroy(sid: str | None) -> None:
    if sid:
        await _blocklist().add(sid)
async def current_session(
    otl_session: str | None = Cookie(default=None, alias=_session_cookie_name()),
) -> SessionContext:
    ctx = await resolve(otl_session)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again."
        )
    return ctx