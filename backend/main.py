from __future__ import annotations

import asyncio
import inspect
import logging
import mimetypes
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import sentry_sdk

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.v1.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, _generate_csrf_token
from .api.v1.chat import _speech_client
from .api.v1.router import api_v1_router
from .api.v1.timecards import (
    _extract_entries,
    _options_hint,
    _strict_assignment,
)
from .core import auth
from .core.config import cors_origins

_cors_origins = cors_origins
from .core.limiter import (
    auth_rate_limiter,
    rate_limiter,
    ws_tracker,
)
from .services import (
    chat,
    fusion_catalogue,
    otl_client,
)
from .services.otl_client import OtlConfigError, OtlError

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from .core.auth import _jwt_secret

    _jwt_secret()
    fusion_catalogue.load_catalogue()

    async def _periodic_refresh():
        interval = int(os.getenv("CATALOGUE_REFRESH_SECONDS", str(6 * 3600)))
        while True:
            try:
                await asyncio.sleep(interval)
                fusion_catalogue.load_catalogue()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Catalogue refresh failed: %s", e)

    refresh_task = asyncio.create_task(_periodic_refresh())
    try:
        yield
    finally:
        refresh_task.cancel()
        await rate_limiter.close()
        await auth_rate_limiter.close()
        close_result = otl_client.close_shared_client()
        if inspect.isawaitable(close_result):
            await close_result
        from .core.auth import _blocklist

        await _blocklist().close()


app = FastAPI(
    title="OTL Timesheet Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    MAX_SIZE = 10 * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large. Maximum size is 10MB."},
                )
        except ValueError:
            pass

    receive = request.receive
    received = 0

    async def wrapped_receive():
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > MAX_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="Request body too large. Maximum size is 10MB.",
                )
        return message

    request._receive = wrapped_receive

    try:
        return await call_next(request)
    except HTTPException as e:
        if e.status_code == 413:
            return JSONResponse(status_code=413, content={"detail": str(e.detail)})
        raise


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", CSRF_HEADER_NAME],
    expose_headers=["X-CSRF-Token"],
)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        return await call_next(request)
    if request.method in ("GET", "HEAD", "OPTIONS") or request.url.path in (
        "/api/health",
        "/api/health/otl",
    ):
        response = await call_next(request)
        csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_token:
            csrf_token = _generate_csrf_token()
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_token,
                httponly=False,
                secure=auth.cookie_secure(),
                samesite="lax",
                max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
                path="/",
            )
        response.headers["X-CSRF-Token"] = csrf_token
        return response
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return await call_next(request)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if (
        not cookie_token
        or not header_token
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF token missing or invalid"},
        )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    csp_dev = os.getenv("CSP_DEV_MODE", "false").strip().lower() == "true"
    if csp_dev:
        logger.warning(
            "CSP_DEV_MODE is enabled - this weakens Content-Security-Policy. "
            "Must be 'false' in production!"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "worker-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' wss: https: ws:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "worker-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "media-src 'self' blob:; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' wss: https: ws:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "microphone=(self), camera=(), geolocation=()"
    )
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        return await call_next(request)
    if request.url.path in ("/api/health", "/api/health/otl"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    trusted_proxy_ips = [
        ip.strip()
        for ip in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
        if ip.strip()
    ]
    client_host = request.client.host if request.client else ""
    trust_proxy = "*" in trusted_proxy_ips or client_host in trusted_proxy_ips

    if trust_proxy:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            for ip in reversed(ips):
                if ip not in trusted_proxy_ips and ip != "*":
                    client_ip = ip
                    break
        elif real_ip := request.headers.get("X-Real-IP"):
            client_ip = real_ip.strip()
        elif forwarded := request.headers.get("Forwarded"):
            for part in forwarded.split(";"):
                part = part.strip()
                if part.startswith("for="):
                    client_ip = part[4:].strip('"')
                    break

    if request.url.path.startswith("/api/auth/"):
        if not await auth_rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
            )
    else:
        if not await rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
            )
    return await call_next(request)


@app.exception_handler(OtlError)
async def _otl_error_handler(_: Request, exc: OtlError) -> JSONResponse:
    code = exc.status_code if exc.status_code in (400, 404) else 502
    return JSONResponse(status_code=code, content={"detail": exc.message})


@app.exception_handler(OtlConfigError)
async def _otl_config_error_handler(_: Request, exc: OtlConfigError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# Mount all modular v1 routes
app.include_router(api_v1_router)


def _frontend_dist() -> Path | None:
    default = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    dist = Path(os.getenv("FRONTEND_DIST", str(default))).resolve()
    return dist if (dist / "index.html").is_file() else None


_DIST = _frontend_dist()
if _DIST is not None:
    _assets = _DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str) -> Response:
    if _DIST is None:
        raise HTTPException(status_code=404, detail="Not found")
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (_DIST / full_path).resolve()
    if (
        full_path
        and (_DIST == candidate or _DIST in candidate.parents)
        and candidate.is_file()
    ):
        revalidate = candidate.name in ("sw.js", "manifest.webmanifest")
        headers = {"Cache-Control": "no-cache"} if revalidate else None
        return FileResponse(candidate, headers=headers)
    return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})


__all__ = [
    "_DIST",
    "_cors_origins",
    "_extract_entries",
    "_options_hint",
    "_otl_config_error_handler",
    "_otl_error_handler",
    "_speech_client",
    "_strict_assignment",
    "app",
    "auth",
    "auth_rate_limiter",
    "chat",
    "fusion_catalogue",
    "otl_client",
    "rate_limiter",
    "ws_tracker",
]
