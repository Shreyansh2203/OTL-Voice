from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...core import auth
from ...core.auth import SessionContext
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


@router.post("/login")
async def login(body: LoginBody, response: Response) -> dict[str, Any]:
    person_number = (body.username or body.personNumber).strip()
    if not person_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Person Number is required.",
        )

    # TODO: In a production environment, you MUST validate body.password against your IdP (e.g. LDAP, Entra ID, Okta).
    # Currently, this validates that the user exists in Oracle HCM via the service account.

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

    employee = Employee(
        employee_id=worker_data["personNumber"],
        username=worker_data["personNumber"],
        full_name=worker_data["fullName"],
    )
    sid = auth.create_session(employee)
    csrf_token = _generate_csrf_token()
    auth.set_auth_cookies(response, sid, csrf_token, CSRF_COOKIE_NAME)
    res = identity_dict(employee)
    res["sessionToken"] = sid
    return res


@router.get("/session")
def session(ctx: SessionContext = Depends(auth.current_session)) -> dict[str, Any]:
    return identity_dict(ctx)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    await auth.destroy(request.cookies.get(auth._session_cookie_name()))
    response.delete_cookie(auth._session_cookie_name(), path="/")
    return {"status": "signed out"}


@router.post("/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    old_token = request.cookies.get(auth._session_cookie_name())
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
