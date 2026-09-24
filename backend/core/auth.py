from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, cast

from fastapi import Cookie, HTTPException, Request, Response, status

from ..models import Employee
from .token_blocklist import _blocklist

logger = logging.getLogger(__name__)
SESSION_COOKIE_NAME = "otl_session"


def _session_cookie_name() -> str:
    return f"__Host-{SESSION_COOKIE_NAME}" if cookie_secure() else SESSION_COOKIE_NAME


def _ttl_seconds() -> int:
    return int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))


def cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "true").strip().lower() != "false"


def set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    csrf_cookie_name: str = "csrf_token",
) -> None:
    samesite_raw = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()
    samesite_valid = (
        samesite_raw if samesite_raw in ("lax", "strict", "none") else "lax"
    )
    samesite = cast(Literal["lax", "strict", "none"], samesite_valid)
    if samesite == "none" and not cookie_secure():
        raise RuntimeError(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true. "
            "Either set SESSION_COOKIE_SECURE=true or use SESSION_COOKIE_SAMESITE=lax/strict."
        )
    max_age = _ttl_seconds()
    is_secure = cookie_secure()
    response.set_cookie(
        key=_session_cookie_name(),
        value=session_token,
        httponly=True,
        secure=is_secure,
        samesite=samesite,
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key=csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=is_secure,
        samesite=samesite,
        max_age=max_age,
        path="/",
    )
    response.headers["X-CSRF-Token"] = csrf_token


import jwt

JWT_ALGORITHM = "HS256"
_fallback_jwt_secret: str | None = None
_jwt_secret_lock = Lock()


def _jwt_secret() -> str:
    global _fallback_jwt_secret
    secret = os.getenv("SESSION_SECRET_KEY")
    if _is_insecure_placeholder(secret):
        secret = None
    test_mode = os.getenv("TEST_MODE", "false").strip().lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "false").strip().lower() == "true"
    if not secret:
        if test_mode or dev_mode:
            if _fallback_jwt_secret is None:
                with _jwt_secret_lock:
                    if _fallback_jwt_secret is None:
                        logger.warning(
                            "SESSION_SECRET_KEY not set - generating temporary secret for development. "
                            "Set SESSION_SECRET_KEY in .env for production use!"
                        )
                        _fallback_jwt_secret = secrets.token_urlsafe(32)
            return _fallback_jwt_secret
        raise RuntimeError(
            "SESSION_SECRET_KEY is not set. "
            "This environment variable is REQUIRED for production use. "
            'Generate a secret with: python -c "import secrets; print(secrets.token_urlsafe(32))" '
            "and add it to your .env file. "
            "For local development only, you can set DEV_MODE=true or TEST_MODE=true to allow a temporary secret."
        )
    return secret


def _is_insecure_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return any(
        marker in normalized
        for marker in (
            "replace-with",
            "generate_a_secure",
            "your_secure",
            "your-",
            "change-me",
            "changeme",
        )
    )


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
        "jti": secrets.token_urlsafe(16),
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
    request: Request = cast(Any, None),
    otl_session: str | None = Cookie(default=None, alias=_session_cookie_name()),
) -> SessionContext:
    token = otl_session
    if not token and request is not None:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    ctx = await resolve(token)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again.",
        )
    return ctx
