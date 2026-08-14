
from __future__ import annotations

import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure correct Content-Type for the PWA manifest and service worker.
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

load_dotenv()  # backend runs from the project root; loads ./.env

from .core import auth
from .services import chat, otl_client  # noqa: E402  (after load_dotenv)
from .core.auth import SESSION_COOKIE_NAME, SessionContext
from .db import repository, seed
from .services.otl_client import OtlConfigError, OtlError

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    seed.ensure_seeded()
    yield


app = FastAPI(
    title="OTL Timesheet Assistant API", version="1.0.0", lifespan=lifespan
)


def _cors_origins() -> List[str]:
    raw = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:4173"
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,  # required so the browser sends the session cookie
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    role: str  # "user" | "assistant"
    content: str


class ChatBody(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)


class TtsBody(BaseModel):
    text: str
    rate: float = 1.0


class TimecardBody(BaseModel):
    entries: Optional[List[Dict[str, Any]]] = None
    assistantMessage: Optional[str] = None


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/otl")
def health_otl() -> Dict[str, Any]:
    return otl_client.validate(otl_client.service_credential())


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _identity(ctx_or_employee: Any) -> Dict[str, Any]:
    return {
        "username": ctx_or_employee.username,
        "employeeId": ctx_or_employee.employee_id,
        "fullName": ctx_or_employee.full_name,
    }


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response) -> Dict[str, Any]:
    employee = repository.verify_login(body.username, body.password)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    sid = auth.create_session(employee)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        httponly=True,
        secure=auth.cookie_secure(),
        samesite=os.getenv("SESSION_COOKIE_SAMESITE", "lax"),
        max_age=int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60))),
        path="/",
    )
    return _identity(employee)


@app.get("/api/auth/session")
def session(ctx: SessionContext = Depends(auth.current_session)) -> Dict[str, Any]:
    return _identity(ctx)


@app.post("/api/auth/logout")
def logout(
    request: Request, response: Response
) -> Dict[str, str]:
    auth.destroy(request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "signed out"}


# --------------------------------------------------------------------------- #
# Chat (SSE)
# --------------------------------------------------------------------------- #
@app.post("/api/chat")
def chat_stream(
    body: ChatBody, ctx: SessionContext = Depends(auth.current_session)
) -> StreamingResponse:
    system_prompt = chat.build_system_prompt(
        username=ctx.username,
        employee_id=ctx.employee_id,
        employee_name=ctx.full_name,
        assignments=repository.list_assignments(ctx.employee_id),
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
    try:
        client = _speech_client()
        audio = client.synthesize(body.text, rate=body.rate)
    except Exception as exc:  # noqa: BLE001 - TTS is best-effort
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech synthesis unavailable: {exc}",
        )
    return Response(content=audio, media_type=client.mime)


# --------------------------------------------------------------------------- #
# OTL timecard submission
# --------------------------------------------------------------------------- #
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_entries(assistant_message: str) -> List[Dict[str, Any]]:
    match = _FENCED_JSON.search(assistant_message or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, list) else []


def _strict_assignment() -> bool:
    return os.getenv("STRICT_ASSIGNMENT", "true").strip().lower() != "false"


def _resolve_entry(entry: Dict[str, Any], ctx: SessionContext) -> Dict[str, Any]:
    resolved = dict(entry)
    resolved["employeeNumber"] = ctx.employee_id
    resolved["employeeName"] = ctx.full_name

    if not _strict_assignment():
        return resolved

    project = None
    project_no = entry.get("projectNo")
    if project_no not in (None, ""):
        try:
            project = repository.resolve_project(int(project_no))
        except (TypeError, ValueError):
            project = None
    if project is None and entry.get("projectName"):
        project = repository.find_project_by_name(str(entry["projectName"]))

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown project '{entry.get('projectName') or project_no}'. "
                f"{_options_hint(ctx.employee_id)}"
            ),
        )
    if not repository.is_assigned(ctx.employee_id, project["projectNo"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{ctx.full_name} is not assigned to project {project['projectNo']} "
                f"({project['projectName']}). {_options_hint(ctx.employee_id)}"
            ),
        )

    resolved.update(project)  # projectNo, workOrder, projectName
    return resolved


def _options_hint(employee_id: str) -> str:
    projects = [
        f"{p['projectNo']} ({p['projectName']}, WO {order['workOrder']})"
        for order in repository.list_assignments(employee_id)
        for p in order["projects"]
    ]
    if not projects:
        return "You have no project assignments."
    return "Assigned projects: " + "; ".join(projects) + "."


@app.post("/api/otl/timecard")
def submit_timecard(
    body: TimecardBody, ctx: SessionContext = Depends(auth.current_session)
) -> Dict[str, Any]:
    entries = body.entries or _extract_entries(body.assistantMessage or "")
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No timecard entries found to submit.",
        )
    resolved = [_resolve_entry(entry, ctx) for entry in entries]
    results = otl_client.create_many(otl_client.service_credential(), resolved)
    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "submitted": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@app.get("/api/otl/timecards")
def list_timecards(
    limit: int = 25,
    offset: int = 0,
    ctx: SessionContext = Depends(auth.current_session),
) -> Dict[str, Any]:
    employee = otl_client.escape_q_literal(ctx.employee_id)
    return otl_client.list_timecard_entries(
        otl_client.service_credential(),
        limit=limit,
        offset=offset,
        query=f"Employee_Number_c='{employee}'",
    )


# --------------------------------------------------------------------------- #
# Labour catalogue
# --------------------------------------------------------------------------- #
@app.get("/api/labour/assignments")
def labour_assignments(
    ctx: SessionContext = Depends(auth.current_session),
) -> Dict[str, Any]:
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": repository.list_assignments(ctx.employee_id),
    }


# --------------------------------------------------------------------------- #
# Static SPA (single-origin production)
# --------------------------------------------------------------------------- #
# In production the built PWA (frontend/dist) is served from this same app, so
# the browser talks to one origin — no CORS, and the session cookie is same-site.
# This block is registered LAST so the catch-all never shadows the /api routes.
# It is skipped when the build is absent (e.g. local dev, where Vite serves the
# frontend and proxies /api here).
def _frontend_dist() -> Optional[Path]:
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
