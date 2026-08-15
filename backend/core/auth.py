
from __future__ import annotations

import os
import secrets
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
# Session store
# --------------------------------------------------------------------------- #
@dataclass
class _SessionRecord:
    employee_id: str
    username: str
    full_name: str
    expires_at: float


@dataclass
class SessionContext:

    employee_id: str  # -> Employee_Number_c
    username: str
    full_name: str  # -> Employee_Name_c


_STORE: dict[str, _SessionRecord] = {}
_LAST_PRUNE: float = 0.0
MAX_SESSIONS: int = 10000

def create_session(employee: Employee) -> str:
    _prune()
    if len(_STORE) >= MAX_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is under heavy load. Please try again later."
        )
    sid = secrets.token_urlsafe(32)
    _STORE[sid] = _SessionRecord(
        employee_id=employee.employee_id,
        username=employee.username,
        full_name=employee.full_name,
        expires_at=time.time() + _ttl_seconds(),
    )
    return sid


def resolve(sid: str | None) -> SessionContext | None:
    if not sid:
        return None
    record = _STORE.get(sid)
    if record is None:
        return None
    if record.expires_at < time.time():
        _STORE.pop(sid, None)
        return None
    return SessionContext(
        employee_id=record.employee_id,
        username=record.username,
        full_name=record.full_name,
    )


def destroy(sid: str | None) -> None:
    if sid:
        _STORE.pop(sid, None)


def _prune() -> None:
    global _LAST_PRUNE
    now = time.time()
    if now - _LAST_PRUNE < 60.0:  # Only prune at most once per minute
        return
    _LAST_PRUNE = now
    expired = [s for s, r in _STORE.items() if r.expires_at < now]
    for s in expired:
        _STORE.pop(s, None)


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
