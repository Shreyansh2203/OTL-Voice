
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from fastapi import Cookie, HTTPException, status

from ..models import Employee

SESSION_COOKIE_NAME = "otl_session"


def _ttl_seconds() -> int:
    return int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))  # 8h default


def cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "true").strip().lower() != "false"


# --------------------------------------------------------------------------- #
# Session store (Stateless JWT)
# --------------------------------------------------------------------------- #
import jwt

JWT_ALGORITHM = "HS256"

def _jwt_secret() -> str:
    return os.getenv("SESSION_SECRET_KEY", "insecure-default-secret-change-in-production")


@dataclass
class SessionContext:

    employee_id: str  # -> Employee_Number_c
    username: str
    full_name: str  # -> Employee_Name_c


def create_session(employee: Employee) -> str:
    payload = {
        "sub": employee.employee_id,
        "username": employee.username,
        "full_name": employee.full_name,
        "exp": time.time() + _ttl_seconds(),
        "iat": time.time(),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def resolve(token: str | None) -> SessionContext | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        return SessionContext(
            employee_id=payload["sub"],
            username=payload["username"],
            full_name=payload["full_name"],
        )
    except jwt.PyJWTError:
        return None


def destroy(sid: str | None) -> None:
    # JWTs are stateless and cannot be destroyed server-side without a blocklist.
    # We rely on the client deleting the cookie.
    pass


# --------------------------------------------------------------------------- #
# FastAPI dependency
# --------------------------------------------------------------------------- #
def current_session(
    otl_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionContext:
    ctx = resolve(otl_session)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again."
        )
    return ctx
