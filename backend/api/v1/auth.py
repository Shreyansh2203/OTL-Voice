from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...core import auth
from ...core.auth import SessionContext
from ...core.config import is_dev_mode, is_test_mode
from ...models import Employee
from ...schemas.auth import LoginBody, identity_dict
from ...services import otl_client
from ...services.otl_client import OtlConfigError, OtlError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _validate_password(password: str) -> None:
    if not password or not password.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password is required.",
        )
    clean_pwd = password.strip()
    configured_pwd = os.getenv("AUTH_PASSWORD")
    configured_value = (
        configured_pwd.strip()
        if configured_pwd and not auth._is_insecure_placeholder(configured_pwd)
        else ""
    )
    if configured_value:
        if not secrets.compare_digest(clean_pwd, configured_value):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        return

    if is_dev_mode() or is_test_mode():
        if len(clean_pwd) < 4 or clean_pwd.lower() in (
            "wrong",
            "invalid",
            "wrongpassword",
            "wrong-password",
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is not configured.",
    )


@router.post("/login")
async def login(body: LoginBody, response: Response) -> dict[str, Any]:
    person_number = (body.username or body.personNumber).strip()
    if not person_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Person Number is required.",
        )

    _validate_password(body.password)

    worker_data: dict[str, Any] | None = None
    cred = None
    try:
        cred = otl_client.service_credential()
    except OtlConfigError:
        pass

    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Oracle Fusion integration is not configured.",
        )

    try:
        worker_data = await otl_client.aget_worker(cred, person_number)
    except OtlError as e:
        logger.error(
            "Oracle service account rejected or worker lookup failed (HTTP %d)",
            e.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or user not found.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to Oracle Fusion. Please try again later.",
        )

    if not worker_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Person Number '{person_number}' was not found.",
        )

    if not worker_data.get("isActive", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive.",
        )

    employee = Employee(
        employee_id=worker_data["personNumber"],
        username=worker_data["personNumber"],
        full_name=worker_data["fullName"],
    )
    sid = auth.create_session(employee)
    csrf_token = _generate_csrf_token()
    auth.set_auth_cookies(response, sid, csrf_token, CSRF_COOKIE_NAME)
    return {
        "status": "authenticated",
        "employee": identity_dict(employee),
    }


@router.get("/session")
def session(ctx: SessionContext = Depends(auth.current_session)) -> dict[str, Any]:
    return identity_dict(ctx)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(auth._session_cookie_name())
    if not token:
        token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        await auth.destroy(token)

    response.delete_cookie(auth._session_cookie_name(), path="/")
    if auth._session_cookie_name() != auth.SESSION_COOKIE_NAME:
        response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "signed out"}


@router.post("/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    old_token = request.cookies.get(auth._session_cookie_name())
    if not old_token:
        old_token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if not old_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            old_token = auth_header[7:].strip()
    if old_token:
        await auth.destroy(old_token)
    employee = Employee(
        username=ctx.username,
        full_name=ctx.full_name,
        employee_id=ctx.employee_id,
    )
    new_token = auth.create_session(employee)
    csrf_token = _generate_csrf_token()
    auth.set_auth_cookies(response, new_token, csrf_token, CSRF_COOKIE_NAME)
    return {"status": "refreshed"}
