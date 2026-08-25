
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

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
load_dotenv()  
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
    def __init__(self, max_requests: int = 60, window_seconds: int = 60, redis_url: str | None = None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self._redis: redis.Redis | None = None
        self._use_redis = self.redis_url is not None
        self._local_requests: dict[str, list[float]] = defaultdict(list)
        self._local_lock = asyncio.Lock()
        self._max_local_keys = 10000  
    async def _get_redis(self) -> redis.Redis | None:
        if not self._use_redis:
            return None
        if self._redis is None:
            if not self.redis_url:
                self._use_redis = False
                return None
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
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
                pass
        async with self._local_lock:
            self._local_requests[key] = [t for t in self._local_requests[key] if now - t < self.window_seconds]
            if len(self._local_requests) > self._max_local_keys:
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
class WSConnectionTracker:
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
ws_tracker = WSConnectionTracker(max_connections_per_ip=5)
rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
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
        await rate_limiter.close()
        await auth_rate_limiter.close()
        from .core.auth import _blocklist
        await _blocklist().close()
app = FastAPI(
    title="OTL Timesheet Assistant API", version="1.0.0", lifespan=lifespan
)
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 10 * 1024 * 1024:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large. Maximum size is 10MB."}
                )
        except ValueError:
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
    allow_credentials=True,  
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
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        return await call_next(request)
    if request.method in ("GET", "HEAD", "OPTIONS") or request.url.path in ("/api/health", "/api/health/otl"):
        response = await call_next(request)
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
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
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
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
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
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' wss: https: ws:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
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
            client_ip = forwarded_for.split(",")[0].strip()
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
    code = exc.status_code if exc.status_code in (400, 404) else 502
    return JSONResponse(status_code=code, content={"detail": exc.message})
@app.exception_handler(OtlConfigError)
async def _otl_config_error_handler(_: Request, exc: OtlConfigError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})
@lru_cache(maxsize=1)
def _speech_client():
    from .services.oci_speech import SpeechClient
    return SpeechClient()
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
    return {"status": "ok"}
@app.get("/api/health/otl")
async def health_otl(ctx: SessionContext = Depends(auth.current_session)) -> dict[str, Any]:
    return await otl_client.avalidate(otl_client.service_credential())
@app.post("/api/auth/login")
async def login(body: LoginBody, response: Response) -> dict[str, Any]:
    person_number = body.username.strip()
    password = body.password
    user_cred = otl_client.OtlCredential(username=person_number, password=password)
    test_mode = os.getenv("TEST_MODE", "false").strip().lower() == "true"
    worker_data: dict[str, Any] | None = None
    if test_mode and password == "":
        worker_data = {
            "personNumber": person_number,
            "fullName": f"Test User {person_number}"
        }
    else:
        try:
            await otl_client.avalidate(user_cred)
        except otl_client.OtlError as e:
            if e.status_code in (401, 403):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect Person Number or password.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to connect to Oracle Fusion. Please try again later."
            )
        except Exception:
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
    return _identity(ctx)
@app.post("/api/auth/logout")
async def logout(
    request: Request, response: Response
) -> dict[str, str]:
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
@app.post("/api/chat")
async def chat_stream(
    body: ChatBody, ctx: SessionContext = Depends(auth.current_session)
) -> StreamingResponse:
    assignments = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    recent_history_str = ""
    try:
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
@app.post("/api/tts")
def tts(
    body: TtsBody, _: SessionContext = Depends(auth.current_session)
) -> Response:
    try:
        client = _speech_client()
        audio = client.synthesize(body.text, rate=body.rate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech synthesis unavailable: {exc}",
        )
    return Response(content=audio, media_type=client.mime)
from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/api/stt/stream")
async def stt_stream(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"
    origin = websocket.headers.get("origin") or websocket.headers.get("sec-websocket-origin")
    allowed_origins = _cors_origins()
    if origin and allowed_origins and origin not in allowed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    otl_session = websocket.cookies.get(auth._session_cookie_name())
    ctx = await auth.resolve(otl_session)
    if not ctx:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return
    if not await ws_tracker.acquire(client_ip):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Too many connections")
        return
    await websocket.accept()
    oci_client = None
    try:
        from .services.oci_speech import STTClient
        client = STTClient()
        oci_client, result_queue, done_event, loop_task = await client.stream_session()
        send_semaphore = asyncio.Semaphore(10)
        backpressure_active = False
        async def receive_from_frontend():
            nonlocal backpressure_active
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if not data:  
                        await oci_client.request_final_result()
                        break
                    if len(data) > 64 * 1024:
                        logging.getLogger(__name__).warning("STT message too large: %d bytes", len(data))
                        continue
                    if result_queue.qsize() > 50:
                        backpressure_active = True
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
                    fetch_task = asyncio.create_task(result_queue.get())
                    done_task = asyncio.create_task(done_event.wait())
                    done, pending = await asyncio.wait(
                        [fetch_task, done_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    if fetch_task in done:
                        result = fetch_task.result()
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
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.MULTILINE)
def _extract_json_object(text: str) -> dict[str, Any] | None:
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
    match = _FENCED_JSON.search(assistant_message)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            data = _extract_json_object(match.group(1))
        if data and isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, list):
                return entries
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
    hours = entry.get("hours")
    if hours is None or not isinstance(hours, (int, float)):
        return False, "Hours is required and must be a number"
    if hours <= 0:
        return False, "Hours must be greater than zero"
    if not entry.get("projectNo") and not entry.get("projectName"):
        return False, "Project number or project name is required"
    if not entry.get("taskDetails"):
        return False, "Task details are required"
    date_str = entry.get("date")
    if date_str and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."
    for time_field in ["startTime", "stopTime"]:
        time_str = entry.get(time_field)
        if time_str and not re.match(r"^\d{2}:\d{2}$", time_str):
            return False, f"Invalid {time_field} format '{time_str}'. Expected HH:MM."
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
    entries = body.entries or _extract_entries(body.assistantMessage or "")
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No timecard entries found to submit.",
        )
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
    test_mode = os.getenv("TEST_MODE", "false").strip().lower() == "true"
    timecards: dict[str, Any]
    if test_mode and ctx.full_name.startswith("Test User"):
        timecards = {"items": []}
    else:
        timecards = await otl_client.alist_timecard_entries(
            otl_client.service_credential(),
            limit=limit,
            offset=offset,
            person_number=ctx.employee_id,
        )
    for item in timecards.get("items", []):
        attrs = item.get("timeAttributes", [])
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
            if item.get("comment") and not has_comment:
                attrs.append({
                    "attributeName": "Comment",
                    "attributeValue": item.get("comment")
                })
    return timecards
@app.get("/api/labour/assignments")
async def labour_assignments(
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    work_orders = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": work_orders,
    }
def _assert_admin(request: Request) -> None:
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
    _assert_admin(request)
    await fusion_catalogue.refresh_catalogue()
    return fusion_catalogue.status()
@app.get("/api/admin/catalogue-status")
async def catalogue_status(
    request: Request,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    _assert_admin(request)
    return fusion_catalogue.status()
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
        if full_path and (_DIST == candidate or _DIST in candidate.parents) and candidate.is_file():
            revalidate = candidate.name in ("sw.js", "manifest.webmanifest")
            headers = {"Cache-Control": "no-cache"} if revalidate else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})