from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core import auth
from ...core.auth import SessionContext
from ...services import fusion_catalogue, otl_client

router = APIRouter(tags=["health", "admin"])


def _assert_admin(request: Request) -> None:
    key = os.getenv("ADMIN_API_KEY")
    if not key:
        return
    if request.headers.get("X-Admin-Key") != key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key required.",
        )


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health/otl")
async def health_otl(
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    return await otl_client.avalidate(otl_client.service_credential())


@router.post("/api/admin/refresh-catalogue")
async def refresh_catalogue(
    request: Request,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    _assert_admin(request)
    await fusion_catalogue.refresh_catalogue()
    return fusion_catalogue.status()


@router.get("/api/admin/catalogue-status")
async def catalogue_status(
    request: Request,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    _assert_admin(request)
    return fusion_catalogue.status()
