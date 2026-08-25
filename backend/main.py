
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import redis.asyncio as redis
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure correct Content-Type for the PWA manifest and service worker.
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

load_dotenv()  # backend runs from the project root; loads ./.env

from .core import auth
from .core.auth import SessionContext
from .services import (
    chat,
    fusion_catalogue,
    otl_client,
)
from .services.otl_client import OtlConfigError, OtlError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis-backed rate limiter for multi-worker deployments with in-memory fallback."""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 60, redis_url: str | None = None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self._redis: redis.Redis | None = None
        self._use_redis = self.redis_url is not None
        # In-memory fallback - bounded to prevent memory leaks
        self._local_requests: dict[str, list[float]] = defaultdict(list)
        self._local_lock = asyncio.Lock()
        self._max_local_keys = 10000  # Max unique IPs to track in memory
    
    async def _get_redis(self) -> redis.Redis | None:
        if not self._use_redis:
            return None
        if self._redis is None:
            if not self.redis_url:
                self._use_redis = False
                return None
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                # Test connection
                await self._redis.ping()
            except Exception:
                self._use_redis = False
                self._redis = None
                logger.warning("Redis unavailable for rate limiter, falling back to in-memory mode")
        return self._redis

    async def is_allowed(self, key: str) -> bool:
        r = await self._get_redis()
        now = time.time()
        window_start = now - self.window_seconds
        
        if r is not None:
            try:
                # Use Redis sorted set. Count *after* adding the current request
                # so the limit check is exact (no off-by-one), and remove the
                # member we just added if the request should be rejected.
                member = f"{now}-{time.perf_counter()}"
                pipe = r.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zadd(key, {member: now})
                pipe.expire(key, self.window_seconds + 1)
                results = await pipe.execute()

                current_count = results[1]
                if current_count > self.max_requests:
                    await r.zrem(key, member)
                    return False
                return True
            except Exception:
                # Fall back to in-memory on Redis error
                pass
        
        # In-memory fallback with size limit and cleanup
        async with self._local_lock:
            # Clean up expired entries
            self._local_requests[key] = [t for t in self._local_requests[key] if now - t < self.window_seconds]
            
            # Enforce max keys limit - remove oldest if over limit
            if len(self._local_requests) > self._max_local_keys:
                # Remove keys with oldest access time
                sorted_keys = sorted(
                    self._local_requests.items(),
                    key=lambda kv: kv[1][0] if kv[1] else now
                )
                for k, _ in sorted_keys[:len(self._local_requests) - self._max_local_keys]:
                    del self._local_requests[k]
            
            if len(self._local_requests[key]) >= self.max_requests:
                return False
            self._local_requests[key].append(now)
            return True
    
    async def close(self):
        if self._redis:
            await self._redis.close()


# WebSocket connection tracker for STT rate limiting
class WSConnectionTracker:
    """Track WebSocket connections per client IP for rate limiting."""
    
    def __init__(self, max_connections_per_ip: int = 5):
        self.max_connections_per_ip = max_connections_per_ip
        self._connections: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
    
    async def acquire(self, client_ip: str) -> bool:
        async with self._lock:
            if self._connections[client_ip] >= self.max_connections_per_ip:
                return False
            self._connections[client_ip] += 1
            return True
    
    async def release(self, client_ip: str) -> None:
        async with self._lock:
            if self._connections[client_ip] > 0:
                self._connections[client_ip] -= 1
                if self._connections[client_ip] == 0:
                    del self._connections[client_ip]


# Global WebSocket connection tracker
ws_tracker = WSConnectionTracker(max_connections_per_ip=5)


# Global rate limiter - can be configured per endpoint
rate_limiter = RateLimiter(max_requests=60, window_seconds=60)

# Stricter rate limiter for auth endpoints
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


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
        # Close rate limiter connections
        await rate_limiter.close()
        await auth_rate_limiter.close()
        # Close token blocklist
        from .core.auth import _blocklist
        await _blocklist().close()


app = FastAPI(
    title="OTL Timesheet Assistant API", version="1.0.0", lifespan=lifespan
)


# Request body size limit (10MB max)
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Request body size limit (10MB max)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 10 * 1024 * 1024:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large. Maximum size is 10MB."}
                )
        except ValueError:
            # Malformed Content-Length; let the framework reject it downstream.
            pass
    return await call_next(request)


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:4173"
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,  # required so the browser sends the session cookie
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _generate_csrf_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Add CSRF protection for state-changing requests."""
    # Skip all protection in test mode
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        return await call_next(request)
    
    # Skip CSRF for safe methods and health checks
    if request.method in ("GET", "HEAD", "OPTIONS") or request.url.path in ("/api/health", "/api/health/otl"):
        response = await call_next(request)
        # Set CSRF cookie on all responses for future requests if not present
        if CSRF_COOKIE_NAME not in request.cookies:
            token = _generate_csrf_token()
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                httponly=False,
                secure=auth.cookie_secure(),
                samesite="lax",
                max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
                path="/",
            )
        return response
    
    # Skip CSRF for WebSocket upgrade
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
    
    # Validate CSRF token for all state-changing requests including auth endpoints
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    
    if not cookie_token or not header_token or cookie_token != header_token:
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF token missing or invalid"}
        )
    
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    
    # Content Security Policy - configurable for dev vs prod
    csp_dev = os.getenv("CSP_DEV_MODE", "false").strip().lower() == "true"
    if csp_dev:
        logger.warning(
            "CSP_DEV_MODE is enabled - this weakens Content-Security-Policy. "
            "Must be 'false' in production!"
        )
        # Development mode: allow unsafe-inline for React HMR, dev tools
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' wss: https: ws:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    else:
        # Production mode: strict CSP
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' wss: https: ws:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    
    # Other security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Allow microphone for STT, deny camera and geolocation
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Apply rate limiting to API endpoints."""
    # Skip all protection in test mode
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        return await call_next(request)
    
    # Skip rate limiting for health checks
    if request.url.path in ("/api/health", "/api/health/otl"):
        return await call_next(request)
    
    # Get client IP - trust proxy headers only from trusted proxies
    client_ip = request.client.host if request.client else "unknown"
    
    # Check if request comes from a trusted proxy. A configured value of "*"
    # (e.g. TRUSTED_PROXY_IPS=*) means "trust any forwarder", which is
    # acceptable when nginx is the sole ingress (see deploy/docker-compose.yml).
    trusted_proxy_ips = [
        ip.strip()
        for ip in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
        if ip.strip()
    ]
    client_host = request.client.host if request.client else ""
    trust_proxy = "*" in trusted_proxy_ips or client_host in trusted_proxy_ips
    
    if trust_proxy:
        # Trust X-Forwarded-For from trusted proxy (nginx)
        # Take the first (original client) IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        # Also trust X-Real-IP if set by nginx
        elif real_ip := request.headers.get("X-Real-IP"):
            client_ip = real_ip.strip()
        # Also support Forwarded header (RFC 7239)
        elif forwarded := request.headers.get("Forwarded"):
            # Parse Forwarded: for=192.0.2.60;proto=https;by=203.0.113.43
            for part in forwarded.split(";"):
                part = part.strip()
                if part.startswith("for="):
                    client_ip = part[4:].strip('"')
                    break
    
    # Apply stricter limits to auth endpoints
    if request.url.path.startswith("/api/auth/"):
        if not await auth_rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )
    else:
        if not await rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )
    
    return await call_next(request)


@app.exception_handler(OtlError)
async def _otl_error_handler(_: Request, exc: OtlError) -> JSONResponse:
    # Upstream 4xx passes through, but never as 401: the caller's own session is
    # fine — a rejected service credential must not look like a expired login.
    code = exc.status_code if exc.status_code in (400, 404) else 502
    return JSONResponse(status_code=code, content={"detail": exc.message})


@app.exception_handler(OtlConfigError)
async def _otl_config_error_handler(_: Request, exc: OtlConfigError) -> JSONResponse:
    # A deployment problem, not a client one.
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Lazy singletons
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _speech_client():
    from .services.oci_speech import SpeechClient

    return SpeechClient()


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    username: str
    password: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list, min_length=0, max_length=50)


class TtsBody(BaseModel):
    text: str
    rate: float = 1.0


class TimecardBody(BaseModel):
    entries: list[dict[str, Any]] | None = None
    assistantMessage: str | None = None


# --------------------------------------------------------------------------- #
# Static Files / Fallback
# --------------------------------------------------------------------------- #


class HasIdentity(Protocol):
    @property
    def username(self) -> str: ...
    @property
    def employee_id(self) -> str: ...
    @property
    def full_name(self) -> str: ...


def _identity(ctx_or_employee: HasIdentity) -> dict[str, Any]:
    return {
        "username": ctx_or_employee.username,
        "employeeId": ctx_or_employee.employee_id,
        "fullName": ctx_or_employee.full_name,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    """
    Basic service liveness check.

    Returns:
        dict[str, str]: Status indicating the service is healthy.
    """
    return {"status": "ok"}


@app.get("/api/health/otl")
async def health_otl(ctx: SessionContext = Depends(auth.current_session)) -> dict[str, Any]:
    """
    Validates connectivity and credentials against the upstream Oracle Fusion HCM REST API.

    Returns:
        dict[str, Any]: Status of the connection.
    """
    return await otl_client.avalidate(otl_client.service_credential())


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

@app.post("/api/auth/login")
async def login(body: LoginBody, response: Response) -> dict[str, Any]:
    """
    Authenticates an employee by their Oracle Fusion Person Number.

    Args:
        body (LoginBody): The login credentials containing username and password.
        response (Response): The FastAPI response object to set the session cookie.

    Raises:
        HTTPException: If authentication fails or Oracle Fusion is unreachable.

    Returns:
        dict[str, Any]: The authenticated employee's identity.
    """
    person_number = body.username.strip()
    password = body.password

    user_cred = otl_client.OtlCredential(username=person_number, password=password)

    try:
        await otl_client.avalidate(user_cred)
    except otl_client.OtlError as e:
        if e.status_code in (401, 403):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect Person Number or password.",
            )
        # Don't expose internal error details which may contain credentials
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to Oracle Fusion. Please try again later."
        )
    except Exception:
        # Don't expose internal error details which may contain credentials
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to Oracle Fusion. Please try again later."
        )

    try:
        worker_data = await otl_client.aget_worker(user_cred, person_number)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to Oracle Fusion. Please try again later."
        )

    if not worker_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Person Number or worker not found in Oracle Fusion.",
        )
        
    from .models import Employee
    employee = Employee(
        employee_id=worker_data["personNumber"],
        username=worker_data["personNumber"],
        full_name=worker_data["fullName"]
    )
    sid = auth.create_session(employee)
    csrf_token = _generate_csrf_token()
    samesite_raw = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()
    samesite_valid = samesite_raw if samesite_raw in ("lax", "strict", "none") else "lax"
    samesite = cast(Literal["lax", "strict", "none"], samesite_valid)
    
    # Validate: SameSite=none requires Secure=true
    if samesite == "none" and not auth.cookie_secure():
        raise RuntimeError(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true. "
            "Either set SESSION_COOKIE_SECURE=true or use SESSION_COOKIE_SAMESITE=lax/strict."
        )
    
    response.set_cookie(
        key=auth._session_cookie_name(),
        value=sid,
        httponly=True,
        secure=auth.cookie_secure(),
        samesite=samesite,
        max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
        path="/",
    )
    # Set CSRF token cookie on login
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=auth.cookie_secure(),
        samesite=samesite,
        max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
        path="/",
    )
    return _identity(employee)


@app.get("/api/auth/session")
def session(ctx: SessionContext = Depends(auth.current_session)) -> dict[str, Any]:
    """
    Retrieves the currently authenticated employee's identity from the session.

    Args:
        ctx (SessionContext): The current session context injected by dependency.

    Returns:
        dict[str, Any]: The authenticated employee's identity.
    """
    return _identity(ctx)


@app.post("/api/auth/logout")
async def logout(
    request: Request, response: Response
) -> dict[str, str]:
    """
    Terminates the active session and clears the session cookie.

    Args:
        request (Request): The incoming request to read the session cookie.
        response (Response): The response object to delete the session cookie.

    Returns:
        dict[str, str]: Status indicating the session was signed out.
    """
    await auth.destroy(request.cookies.get(auth._session_cookie_name()))
    response.delete_cookie(auth._session_cookie_name(), path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "signed out"}


@app.post("/api/auth/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    """
    Refreshes the current session by issuing a new JWT and resetting the cookie TTL.
    """
    old_token = request.cookies.get(auth._session_cookie_name())
    if old_token:
        await auth.destroy(old_token)
    from .models import Employee
    employee = Employee(
        username=ctx.username,
        full_name=ctx.full_name,
        employee_id=ctx.employee_id,
    )
    new_token = auth.create_session(employee)
    samesite_raw = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()
    samesite_valid = samesite_raw if samesite_raw in ("lax", "strict", "none") else "lax"
    samesite = cast(Literal["lax", "strict", "none"], samesite_valid)
    
    # Validate: SameSite=none requires Secure=true
    if samesite == "none" and not auth.cookie_secure():
        raise RuntimeError(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true. "
            "Either set SESSION_COOKIE_SECURE=true or use SESSION_COOKIE_SAMESITE=lax/strict."
        )

    response.set_cookie(
        key=auth._session_cookie_name(),
        value=new_token,
        httponly=True,
        secure=auth.cookie_secure(),
        samesite=samesite,
        max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
        path="/",
    )
    # Set new CSRF token on session refresh
    csrf_token = _generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=auth.cookie_secure(),
        samesite=samesite,
        max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
        path="/",
    )
    return {"status": "refreshed"}

# --------------------------------------------------------------------------- #
# Chat / LLM
# --------------------------------------------------------------------------- #
@app.post("/api/chat")
async def chat_stream(
    body: ChatBody, ctx: SessionContext = Depends(auth.current_session)
) -> StreamingResponse:
    """
    Streams assistant responses via Server-Sent Events (SSE) using OCI GenAI.

    Args:
        body (ChatBody): The message history and new user message.
        ctx (SessionContext): The current session context.

    Returns:
        StreamingResponse: An SSE stream of the assistant's response tokens.
    """
    assignments = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    
    recent_history_str = ""
    try:
        # Smart Defaults: fetch the single most recent timecard to suggest it
        recent = await otl_client.alist_timecard_entries(
            otl_client.service_credential(), limit=1, offset=0, person_number=ctx.employee_id
        )
        items = recent.get("items", [])
        if items:
            latest = items[0]
            attrs = latest.get("timeRecordEventAttribute") or latest.get("timeAttributes", [])
            proj = next((a.get("attributeValue") for a in attrs if a.get("attributeName") == "PJC_PROJECT_ID"), None)
            hours = latest.get("measure", "")
            if proj:
                p_info = fusion_catalogue.get_project_by_id(proj)
                if p_info:
                    recent_history_str = f"User recently logged {hours} hours on {p_info.get('project_name')} (Project {p_info.get('project_number')})."
    except Exception:
        pass

    system_prompt = chat.build_system_prompt(
        username=ctx.username,
        employee_id=ctx.employee_id,
        employee_name=ctx.full_name,
        assignments=assignments,
        recent_history=recent_history_str,
    )
    history = [{"role": m.role, "content": m.content} for m in body.messages]
    return StreamingResponse(
        chat.stream_sse(system_prompt, history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# Text-to-speech
# --------------------------------------------------------------------------- #
@app.post("/api/tts")
def tts(
    body: TtsBody, _: SessionContext = Depends(auth.current_session)
) -> Response:
    """
    Synthesizes speech audio from provided text using OCI AI Speech Service.

    Args:
        body (TtsBody): The text to synthesize and optional rate.
        _ (SessionContext): The current session context (authentication required).

    Raises:
        HTTPException: If the speech synthesis service is unavailable.

    Returns:
        Response: Binary audio stream (e.g., MP3).
    """
    try:
        client = _speech_client()
        audio = client.synthesize(body.text, rate=body.rate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech synthesis unavailable: {exc}",
        )
    return Response(content=audio, media_type=client.mime)


# --------------------------------------------------------------------------- #
# Speech-to-Text (Streaming)
# --------------------------------------------------------------------------- #

from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/api/stt/stream")
async def stt_stream(websocket: WebSocket):
    """
    Bidirectional WebSocket for streaming raw PCM audio to OCI Realtime Speech.
    """
    # Get client IP for rate limiting
    client_ip = websocket.client.host if websocket.client else "unknown"
    
    # Validate Origin header against allowed CORS origins. In single-origin
    # deployments CORS_ORIGINS is empty, meaning there is no allow-list to
    # enforce against — the browser already enforces same-origin for the
    # WebSocket handshake, so we skip the check rather than reject everything.
    origin = websocket.headers.get("origin") or websocket.headers.get("sec-websocket-origin")
    allowed_origins = _cors_origins()
    if origin and allowed_origins and origin not in allowed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    
    # Authenticate FIRST before acquiring rate limiter slot
    otl_session = websocket.cookies.get(auth._session_cookie_name())
    ctx = await auth.resolve(otl_session)
    if not ctx:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return
    
    # Check WebSocket connection limit per IP
    if not await ws_tracker.acquire(client_ip):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Too many connections")
        return
    
    # Now accept the authenticated connection
    # WebSocket message size limits should be configured at the server level.
    await websocket.accept()

    oci_client = None
    try:
        from .services.oci_speech import STTClient
        client = STTClient()
        oci_client, result_queue, done_event, loop_task = await client.stream_session()
        
        # Backpressure: limit concurrent sends to prevent queue buildup
        send_semaphore = asyncio.Semaphore(10)
        # Track if we're applying backpressure
        backpressure_active = False
        
        async def receive_from_frontend():
            nonlocal backpressure_active
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if not data:  # EOF signal from frontend (empty bytes)
                        await oci_client.request_final_result()
                        break
                    # Validate message size
                    if len(data) > 64 * 1024:
                        logging.getLogger(__name__).warning("STT message too large: %d bytes", len(data))
                        continue
                    
                    # Apply backpressure if queue is building up
                    if result_queue.qsize() > 50:
                        backpressure_active = True
                        # Small delay to let consumer catch up
                        await asyncio.sleep(0.01)
                    else:
                        backpressure_active = False
                    
                    await oci_client.send_data(data)
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.exception("STT RX Error")

        async def send_to_frontend():
            try:
                while not done_event.is_set() or not result_queue.empty():
                    # Wait for results or the connection to close
                    fetch_task = asyncio.create_task(result_queue.get())
                    done_task = asyncio.create_task(done_event.wait())
                    
                    done, pending = await asyncio.wait(
                        [fetch_task, done_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    if fetch_task in done:
                        result = fetch_task.result()
                        # Apply backpressure on send
                        async with send_semaphore:
                            await websocket.send_json(result)
                        if result.get("isFinal"):
                            pass
                    
                    for t in pending:
                        t.cancel()
            except WebSocketDisconnect:
                pass
            except Exception:
                import logging
                logging.getLogger(__name__).exception("STT TX Error")
        
        rx_task = asyncio.create_task(receive_from_frontend())
        tx_task = asyncio.create_task(send_to_frontend())
        
        # Use gather with return_exceptions to handle errors gracefully
        results = await asyncio.gather(rx_task, tx_task, loop_task, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                import logging
                logging.getLogger(__name__).exception("STT task error", exc_info=result)
        
    except Exception:
        import logging
        logging.getLogger(__name__).exception("STT Session Error")
    finally:
        await ws_tracker.release(client_ip)
        try:
            if oci_client:
                oci_client.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

# --------------------------------------------------------------------------- #
# OTL timecard submission
# --------------------------------------------------------------------------- #
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.MULTILINE)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first complete JSON object from text, handling nested braces."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_entries(assistant_message: str) -> list[dict[str, Any]]:
    if not assistant_message:
        return []
    
    # First try to find fenced JSON block
    match = _FENCED_JSON.search(assistant_message)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            # Try to extract valid JSON from the matched group
            data = _extract_json_object(match.group(1))
        if data and isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, list):
                return entries
    
    # Fallback: try to extract JSON object from anywhere in the message
    data = _extract_json_object(assistant_message)
    if data and isinstance(data, dict):
        entries = data.get("entries")
        if isinstance(entries, list):
            return entries
    
    return []


_STRICT_ASSIGNMENT_CACHE: bool | None = None


def _strict_assignment() -> bool:
    global _STRICT_ASSIGNMENT_CACHE
    if _STRICT_ASSIGNMENT_CACHE is None:
        _STRICT_ASSIGNMENT_CACHE = os.getenv("STRICT_ASSIGNMENT", "true").strip().lower() != "false"
    return _STRICT_ASSIGNMENT_CACHE


def _validate_timecard_entry(entry: dict[str, Any], assignments: list[dict[str, Any]] | None = None) -> tuple[bool, str | None]:
    """
    Validates a single timecard entry.
    Returns (is_valid, error_message).
    """
    hours = entry.get("hours")
    if hours is None or not isinstance(hours, (int, float)):
        return False, "Hours is required and must be a number"
    
    if hours <= 0:
        return False, "Hours must be greater than zero"
    
    if not entry.get("projectNo") and not entry.get("projectName"):
        return False, "Project number or project name is required"
    
    if not entry.get("taskDetails"):
        return False, "Task details are required"
    
    # Validate date format if provided
    date_str = entry.get("date")
    if date_str and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."
    
    # Validate time format if provided
    for time_field in ["startTime", "stopTime"]:
        time_str = entry.get(time_field)
        if time_str and not re.match(r"^\d{2}:\d{2}$", time_str):
            return False, f"Invalid {time_field} format '{time_str}'. Expected HH:MM."
    
    # If strict assignment mode and assignments provided, validate project
    if assignments is not None and _strict_assignment():
        project_no = entry.get("projectNo")
        project_name = entry.get("projectName")
        project_found = False
        
        for order in assignments:
            for p in order.get("projects", []):
                if project_no and str(p.get("projectNo")) == str(project_no):
                    project_found = True
                    break
                if not project_no and project_name and p.get("projectName") == project_name:
                    project_found = True
                    break
            if project_found:
                break
        
        if not project_found:
            return False, f"Project {project_no or project_name} is not in your assigned projects"
    
    return True, None


def _resolve_entry(entry: dict[str, Any], ctx: SessionContext, assignments: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = dict(entry)
    resolved["employeeNumber"] = ctx.employee_id
    resolved["employeeName"] = ctx.full_name

    project = None
    project_no = entry.get("projectNo")
    
    for order in assignments:
        for p in order.get("projects", []):
            if project_no and str(p.get("projectNo")) == str(project_no):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
            if not project_no and entry.get("projectName") and p.get("projectName") == entry.get("projectName"):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
        if project:
            break

    resolved.update({
        "projectId": project.get("projectId") if project else None,
        "projectNo": project.get("projectNo") if project else project_no,
        "workOrder": project.get("workOrder") if project else None,
        "projectName": project.get("projectName") if project else entry.get("projectName"),
    })

    # Resolve taskId if not provided but we have taskDetails
    if not resolved.get("taskId") and resolved.get("taskDetails"):
        target_name = str(resolved["taskDetails"]).lower()
        if project:
            for t in project.get("tasks", []):
                if str(t.get("taskDetails")).lower() == target_name:
                    resolved["taskId"] = t.get("taskId")
                    break

    return resolved


def _options_hint(assignments: list[dict[str, Any]]) -> str:
    projects = [
        f"{p.get('projectNo')} ({p.get('projectName')}, WO {order.get('workOrder')})"
        for order in assignments
        for p in order.get("projects", [])
    ]
    if not projects:
        return "You have no project assignments."
    
    # Limit to first 10 projects and truncate if too long
    max_projects = 10
    max_length = 500
    display_projects = projects[:max_projects]
    hint = "Assigned projects: " + "; ".join(display_projects) + "."
    
    if len(projects) > max_projects:
        hint += f" ... and {len(projects) - max_projects} more."
    
    if len(hint) > max_length:
        hint = hint[:max_length - 3] + "..."
    
    return hint


@app.post("/api/otl/timecard")
async def submit_timecard(
    body: TimecardBody, ctx: SessionContext = Depends(auth.current_session)
) -> dict[str, Any]:
    """
    Submits validated timecard entries to Oracle Fusion Cloud HCM.

    Args:
        body (TimecardBody): The timecard entries to submit, or raw assistant JSON output.
        ctx (SessionContext): The current session context.

    Raises:
        HTTPException: If no valid entries are provided or assignment authorization fails.

    Returns:
        dict[str, Any]: Submission results including succeeded and failed counts.
    """
    entries = body.entries or _extract_entries(body.assistantMessage or "")
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No timecard entries found to submit.",
        )
    
    # Validate entries before processing
    assignments_for_validation = []
    if _strict_assignment():
        assignments_for_validation = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    
    for i, entry in enumerate(entries):
        valid, error = _validate_timecard_entry(entry, assignments_for_validation)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Entry {i + 1}: {error}",
            )
    
    assignments = assignments_for_validation
    resolved = [_resolve_entry(entry, ctx, assignments) for entry in entries]
    results = await otl_client.acreate_many(otl_client.service_credential(), resolved)
    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "submitted": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@app.get("/api/otl/timecards")
async def list_timecards(
    limit: int = Query(default=25, ge=1, le=100, description="Maximum records to fetch (1-100)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset (>=0)"),
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    """
    Queries historical timecard entries from Oracle Fusion for the current employee.

    Args:
        limit (int, optional): Maximum records to fetch. Defaults to 25, max 100.
        offset (int, optional): Pagination offset. Defaults to 0.
        ctx (SessionContext): The current session context.

    Returns:
        dict[str, Any]: Paginated list of timecard entries.
    """
    timecards = await otl_client.alist_timecard_entries(
        otl_client.service_credential(),
        limit=limit,
        offset=offset,
        person_number=ctx.employee_id,
    )

    # Enrich timecards with human-readable project names if they lack a Comment attribute.
    for item in timecards.get("items", []):
        # timeRecords endpoint has attributes directly under timeAttributes
        attrs = item.get("timeAttributes", [])
        
        # Maintain compatibility with old timeRecordEventRequests format if it's ever used
        if "timeRecordEvent" in item:
            for event in item.get("timeRecordEvent", []):
                evt_attrs = event.get("timeRecordEventAttribute", [])
                has_comment = any(a.get("attributeName") == "Comment" for a in evt_attrs)
                if not has_comment:
                    proj_attr = next((a for a in evt_attrs if a.get("attributeName") == "PJC_PROJECT_ID"), None)
                    if proj_attr and proj_attr.get("attributeValue"):
                        proj = fusion_catalogue.get_project_by_id(proj_attr.get("attributeValue"))
                        if proj:
                            evt_attrs.append({
                                "attributeName": "Comment",
                                "attributeValue": f"Project: {proj.get('project_name')}"
                            })
        else:
            # Handle new timeRecords format
            # ensure timeRecordEventAttribute is populated for frontend compatibility
            item["timeRecordEventAttribute"] = attrs
            has_comment = any(a.get("attributeName") == "Comment" for a in attrs)
            if not has_comment:
                proj_attr = next((a for a in attrs if a.get("attributeName") == "PJC_PROJECT_ID"), None)
                if proj_attr and proj_attr.get("attributeValue"):
                    proj = fusion_catalogue.get_project_by_id(proj_attr.get("attributeValue"))
                    if proj:
                        attrs.append({
                            "attributeName": "Comment",
                            "attributeValue": f"Project: {proj.get('project_name')}"
                        })
            
            # Use top level comment if present
            if item.get("comment") and not has_comment:
                attrs.append({
                    "attributeName": "Comment",
                    "attributeValue": item.get("comment")
                })
                
    return timecards


# --------------------------------------------------------------------------- #
# Labour catalogue
# --------------------------------------------------------------------------- #
@app.get("/api/labour/assignments")
async def labour_assignments(
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    """
    Retrieves the assigned work orders, projects, and tasks for the employee.

    Args:
        ctx (SessionContext): The current session context.

    Returns:
        dict[str, Any]: The employee's authorized labour catalogue assignments.
    """
    work_orders = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": work_orders,
    }


def _assert_admin(request: Request) -> None:
    """Restrict admin endpoints.

    If ADMIN_API_KEY is configured, the caller must present a matching
    `X-Admin-Key` header. If it is not configured the endpoint stays open
    (backward compatible), but operators SHOULD set ADMIN_API_KEY in
    production so that catalogue reloads cannot be triggered by any
    logged-in employee.
    """
    key = os.getenv("ADMIN_API_KEY")
    if not key:
        return
    if request.headers.get("X-Admin-Key") != key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key required.",
        )


@app.post("/api/admin/refresh-catalogue")
async def refresh_catalogue(
    request: Request,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    """Re-export data from Oracle Fusion and reload the local catalogue."""
    _assert_admin(request)
    await fusion_catalogue.refresh_catalogue()
    return fusion_catalogue.status()


@app.get("/api/admin/catalogue-status")
async def catalogue_status(
    request: Request,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    """Returns the current catalogue status."""
    _assert_admin(request)
    return fusion_catalogue.status()


# --------------------------------------------------------------------------- #
# Static SPA (single-origin production)
# --------------------------------------------------------------------------- #
# In production the built PWA (frontend/dist) is served from this same app, so
# the browser talks to one origin — no CORS, and the session cookie is same-site.
# This block is registered LAST so the catch-all never shadows the /api routes.
# It is skipped when the build is absent (e.g. local dev, where Vite serves the
# frontend and proxies /api here).
def _frontend_dist() -> Path | None:
    default = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    dist = Path(os.getenv("FRONTEND_DIST", str(default))).resolve()
    return dist if (dist / "index.html").is_file() else None


_DIST = _frontend_dist()

if _DIST is not None:
    _assets = _DIST / "assets"
    if _assets.is_dir():
        # Hashed, immutable bundles — safe to mount as-is (long cache by hash).
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> Response:
        if _DIST is None:
            raise HTTPException(status_code=404, detail="Not found")
            
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (_DIST / full_path).resolve()
        # Path-traversal guard: only serve real files inside dist.
        if full_path and (_DIST == candidate or _DIST in candidate.parents) and candidate.is_file():
            # sw.js and the manifest must revalidate so updates roll out promptly.
            revalidate = candidate.name in ("sw.js", "manifest.webmanifest")
            headers = {"Cache-Control": "no-cache"} if revalidate else None
            return FileResponse(candidate, headers=headers)

        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})
