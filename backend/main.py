from __future__ import annotations

import asyncio
import inspect
import logging
import mimetypes
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from dotenv import load_dotenv

load_dotenv()


_SENSITIVE_EVENT_PATHS = (
    "/api/auth/",
    "/api/chat",
    "/api/tts",
    "/api/stt/",
    "/api/otl/",
)
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "setcookie",
    "password",
    "passwd",
    "secret",
    "credential",
    "credentials",
    "apikey",
    "privatekey",
    "token",
    "jwt",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "personnumber",
    "employeenumber",
    "phonenumber",
    "employeeid",
    "userid",
    "username",
    "email",
    "ipaddress",
    "body",
    "data",
    "headers",
    "query",
    "querystring",
    "chat",
    "messages",
    "content",
    "transcript",
    "prompt",
    "text",
    "audio",
}
_REDACTIONS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)basic\s+[A-Za-z0-9+/=]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(
        r"(?i)(password|passwd|token|jwt|cookie|authorization)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?<!\d)\d{6,}(?!\d)"),
)


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTIONS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _scrub_sentry_value(value: Any, key: str | None = None) -> Any:
    if key is not None and _normalized_key(key) in _SENSITIVE_KEYS:
        return "[FILTERED]"
    if isinstance(value, dict):
        return {
            str(child_key): _scrub_sentry_value(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_scrub_sentry_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_sentry_value(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _event_path(event: dict[str, Any]) -> str:
    request = event.get("request")
    if isinstance(request, dict) and isinstance(request.get("url"), str):
        return urlsplit(request["url"]).path
    transaction = event.get("transaction")
    return transaction if isinstance(transaction, str) else ""


def _sentry_scrub_event(event: Any, hint: Any) -> Any | None:
    if not isinstance(event, dict):
        return None
    if any(path in _event_path(event) for path in _SENSITIVE_EVENT_PATHS):
        return None
    for field in (
        "attachments",
        "breadcrumbs",
        "contexts",
        "extra",
        "logs",
        "modules",
        "user",
    ):
        event.pop(field, None)
    event.pop("tags", None)
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("cookies", "data", "env", "headers", "query_string"):
            request.pop(field, None)
        raw_url = request.get("url")
        if isinstance(raw_url, str):
            parsed = urlsplit(raw_url)
            request["url"] = urlunsplit(
                (parsed.scheme, parsed.netloc, _redact_text(parsed.path), "", "")
            )
    stacktrace = event.get("stacktrace")
    frames = stacktrace.get("frames", []) if isinstance(stacktrace, dict) else []
    for frame in frames:
        if isinstance(frame, dict):
            frame.pop("vars", None)
    scrubbed = _scrub_sentry_value(event)
    return scrubbed if isinstance(scrubbed, dict) else None


def _sentry_scrub_transaction(event: Any, hint: Any) -> Any | None:
    del hint
    if not isinstance(event, dict):
        return None
    if any(path in _event_path(event) for path in _SENSITIVE_EVENT_PATHS):
        return None
    return _scrub_sentry_value(event)


def _sentry_scrub_breadcrumb(crumb: Any, hint: Any) -> None:
    del crumb, hint
    return None


def _sentry_sample_rate(name: str, default: float, maximum: float) -> float:
    try:
        return max(0.0, min(maximum, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


def _initialize_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=_sentry_sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.05, 0.1),
        profiles_sample_rate=0.0,
        before_send=_sentry_scrub_event,
        before_send_transaction=_sentry_scrub_transaction,
        before_breadcrumb=_sentry_scrub_breadcrumb,
    )


_initialize_sentry()

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
from .core.config import cors_origins, is_test_mode

_cors_origins = cors_origins
from .core.limiter import (
    RateLimiterUnavailable,
    auth_rate_limiter,
    rate_limiter,
    resolve_client_ip,
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
    allow_headers=["Content-Type", CSRF_HEADER_NAME],
    expose_headers=["X-CSRF-Token"],
)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if is_test_mode():
        return await call_next(request)
    if request.method in ("GET", "HEAD", "OPTIONS") or request.url.path in (
        "/api/health",
        "/api/health/otl",
    ):
        response = await call_next(request)
        csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_token:
            csrf_token = _generate_csrf_token()
            auth.set_csrf_cookie(response, csrf_token, CSRF_COOKIE_NAME)
        response.headers["X-CSRF-Token"] = csrf_token
        return response
    if request.headers.get("Authorization"):
        return JSONResponse(
            status_code=401,
            content={"detail": "Bearer authentication is not supported."},
        )
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if (
        not cookie_token
        or not header_token
        or len(cookie_token) > 256
        or len(header_token) > 256
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
    if is_test_mode():
        return await call_next(request)
    if request.url.path in ("/api/health", "/api/health/otl"):
        return await call_next(request)

    client_ip = resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get("X-Forwarded-For"),
        request.headers.get("X-Real-IP"),
    )
    limiter = (
        auth_rate_limiter if request.url.path.startswith("/api/auth/") else rate_limiter
    )
    try:
        allowed = await limiter.is_allowed(client_ip)
    except RateLimiterUnavailable:
        return JSONResponse(
            status_code=503,
            content={"detail": "Rate limiting is temporarily unavailable."},
            headers={"Retry-After": "1"},
        )
    if not allowed:
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
