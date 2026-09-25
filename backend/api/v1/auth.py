from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from ...core import auth
from ...core.auth import AuthVerification, SessionContext
from ...core.token_blocklist import SessionStoreUnavailable
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


async def _verify_login(identifier: str, credential: str) -> AuthVerification:
    if not credential or len(credential) > 32768:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password or credentials are required.",
        )
    try:
        verifier = auth.get_credential_verifier()
        verification = await verifier.verify(identifier, credential)
    except auth.AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from exc
    except auth.IdentityProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification is temporarily unavailable.",
            headers={"Retry-After": "1"},
        ) from exc
    except auth.AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or credentials.",
        ) from exc
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or credentials.",
        )
    return verification


async def _load_active_employee(verification: AuthVerification) -> Employee:
    try:
        credential = otl_client.service_credential()
    except OtlConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Employee directory is not configured.",
        ) from exc
    try:
        worker_data = await otl_client.aget_worker(credential, verification.employee_id)
    except OtlError as exc:
        logger.error("Oracle employee lookup failed (HTTP %d)", exc.status_code)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or user not found.",
        ) from exc
    except Exception as exc:
        logger.error("Oracle employee lookup failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Employee directory is temporarily unavailable.",
        ) from exc
    if not worker_data or not worker_data.get("isActive", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or user not found.",
        )
    directory_id = str(worker_data.get("personNumber") or "").strip()
    if not directory_id or directory_id != verification.employee_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or user not found.",
        )
    full_name = str(worker_data.get("fullName") or "").strip()
    return Employee(
        employee_id=directory_id,
        username=directory_id,
        full_name=full_name,
    )


async def _issue_session(employee: Employee) -> str:
    try:
        return await auth.issue_session(employee)
    except SessionStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session creation is temporarily unavailable.",
            headers={"Retry-After": "1"},
        ) from exc


@router.post("/login")
async def login(body: LoginBody, response: Response) -> dict[str, Any]:
    supplied_identifier = (body.username or body.personNumber).strip()
    verification = await _verify_login(supplied_identifier, body.password)
    employee = await _load_active_employee(verification)
    session_token = await _issue_session(employee)
    csrf_token = _generate_csrf_token()
    auth.set_auth_cookies(response, session_token, csrf_token, CSRF_COOKIE_NAME)
    return {
        "status": "authenticated",
        "employee": identity_dict(employee),
    }


@router.get("/session")
def session(
    response: Response, ctx: SessionContext = Depends(auth.current_session)
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return identity_dict(ctx)


@router.post("/logout", response_model=None)
async def logout(request: Request, response: Response) -> Any:
    token = auth.session_cookie_token(request)
    try:
        await auth.destroy(token)
    except SessionStoreUnavailable:
        error_response = JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Session revocation is temporarily unavailable."},
            headers={"Retry-After": "1", "Cache-Control": "no-store"},
        )
        auth.clear_auth_cookies(error_response, CSRF_COOKIE_NAME)
        return error_response
    auth.clear_auth_cookies(response, CSRF_COOKIE_NAME)
    return {"status": "signed out"}


@router.post("/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    old_token = auth.session_cookie_token(request)
    if not old_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again.",
        )
    verification = AuthVerification(
        employee_id=ctx.employee_id,
        username=ctx.username,
    )
    employee = await _load_active_employee(verification)
    try:
        await auth.destroy(old_token)
    except SessionStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session rotation is temporarily unavailable.",
            headers={"Retry-After": "1"},
        ) from exc
    new_token = await _issue_session(employee)
    csrf_token = _generate_csrf_token()
    auth.set_auth_cookies(response, new_token, csrf_token, CSRF_COOKIE_NAME)
    return {"status": "refreshed"}
