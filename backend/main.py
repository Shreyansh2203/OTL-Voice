
from __future__ import annotations

import json
import mimetypes
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

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
from .core.auth import SESSION_COOKIE_NAME, SessionContext
from .services import (
    chat,
    fusion_catalogue,
    otl_client,
)
from .services.otl_client import OtlConfigError, OtlError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    fusion_catalogue.load_catalogue()
    yield


app = FastAPI(
    title="OTL Timesheet Assistant API", version="1.0.0", lifespan=lifespan
)


def _cors_origins() -> list[str]:
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
    messages: list[ChatMessage] = Field(default_factory=list)


class TtsBody(BaseModel):
    text: str
    rate: float = 1.0


class TimecardBody(BaseModel):
    entries: list[dict[str, Any]] | None = None
    assistantMessage: str | None = None


# --------------------------------------------------------------------------- #
# Static Files / Fallback
# --------------------------------------------------------------------------- #
def _identity(ctx_or_employee: Any) -> dict[str, Any]:
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
def health_otl() -> dict[str, Any]:
    """
    Validates connectivity and credentials against the upstream Oracle Fusion HCM REST API.

    Returns:
        dict[str, Any]: Status of the connection.
    """
    return otl_client.validate(otl_client.service_credential())


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

@app.post("/api/auth/login")
def login(body: LoginBody, response: Response) -> dict[str, Any]:
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
    # In this new architecture, we treat "username" as the Person Number
    person_number = body.username.strip()
    password = body.password

    otl_client.OtlCredential(username=person_number, password=password)

    # 1. Validate the user's password directly against Oracle Fusion
    # (Bypassed for testing purposes)
    # try:
    #     otl_client.validate(user_cred)
    # except otl_client.OtlError as e:
    #     if e.status_code in (401, 403):
    #         raise HTTPException(
    #             status_code=status.HTTP_401_UNAUTHORIZED,
    #             detail="Incorrect Person Number or password.",
    #         )
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail=f"Failed to connect to Oracle Fusion: {e!s}"
    #     )
    # except Exception as e:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail=f"Failed to connect to Oracle Fusion: {e!s}"
    #     )

    # 2. Fetch worker details using the validated credentials
    try:
        # Use service account to look up the worker, allowing passwordless test login
        worker_data = otl_client.get_worker(otl_client.service_credential(), person_number)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Oracle Fusion: {e!s}"
        )

    if not worker_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Person Number or worker not found in Oracle Fusion.",
        )
        
    from .models import Employee
    employee = Employee(
        employee_id=worker_data["personNumber"],
        username=worker_data["personNumber"], # Bypassing username
        full_name=worker_data["fullName"]
    )
    sid = auth.create_session(employee)
    samesite_raw = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()
    samesite_valid = samesite_raw if samesite_raw in ("lax", "strict", "none") else "lax"
    samesite = cast(Literal["lax", "strict", "none"], samesite_valid)
    
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        httponly=True,
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
def logout(
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
    """
    Streams assistant responses via Server-Sent Events (SSE) using OCI GenAI.

    Args:
        body (ChatBody): The message history and new user message.
        ctx (SessionContext): The current session context.

    Returns:
        StreamingResponse: An SSE stream of the assistant's response tokens.
    """
    assignments = otl_client.list_worker_assignments(
        otl_client.service_credential(), ctx.employee_id, ctx.full_name
    )
    
    recent_history_str = ""
    try:
        # Smart Defaults: fetch the single most recent timecard to suggest it
        recent = otl_client.list_timecard_entries(
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
# OTL timecard submission
# --------------------------------------------------------------------------- #
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_entries(assistant_message: str) -> list[dict[str, Any]]:
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


def _resolve_entry(entry: dict[str, Any], ctx: SessionContext, assignments: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = dict(entry)
    resolved["employeeNumber"] = ctx.employee_id
    resolved["employeeName"] = ctx.full_name

    if not _strict_assignment():
        return resolved
    
    project = None
    project_no = entry.get("projectNo")
    
    for order in assignments:
        for p in order.get("projects", []):
            if project_no and str(p.get("projectNo")) == str(project_no):
                project = p
                project["workOrder"] = order.get("workOrder")
                break
            if not project_no and entry.get("projectName") and p.get("projectName") == entry.get("projectName"):
                project = p
                project["workOrder"] = order.get("workOrder")
                break
        if project:
            break

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown project '{entry.get('projectName') or project_no}'. "
                f"{_options_hint(ctx.employee_id, ctx.full_name)}"
            ),
        )

    resolved.update({
        "projectId": project.get("projectId"),
        "projectNo": project.get("projectNo"),
        "workOrder": project.get("workOrder"),
        "projectName": project.get("projectName")
    })

    # Resolve taskId if not provided but we have taskDetails
    if not resolved.get("taskId") and resolved.get("taskDetails"):
        target_name = str(resolved["taskDetails"]).lower()
        for t in project.get("tasks", []):
            if str(t.get("taskDetails")).lower() == target_name:
                resolved["taskId"] = t.get("taskId")
                break

    return resolved


def _options_hint(employee_id: str, full_name: str) -> str:
    projects = [
        f"{p['projectNo']} ({p['projectName']}, WO {order['workOrder']})"
        for order in otl_client.list_worker_assignments(otl_client.service_credential(), employee_id, full_name)
        for p in order["projects"]
    ]
    if not projects:
        return "You have no project assignments."
    return "Assigned projects: " + "; ".join(projects) + "."


@app.post("/api/otl/timecard")
def submit_timecard(
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
        
    assignments = []
    if _strict_assignment():
        assignments = otl_client.list_worker_assignments(otl_client.service_credential(), ctx.employee_id, ctx.full_name)
        
    resolved = [_resolve_entry(entry, ctx, assignments) for entry in entries]
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
) -> dict[str, Any]:
    """
    Queries historical timecard entries from Oracle Fusion for the current employee.

    Args:
        limit (int, optional): Maximum records to fetch. Defaults to 25.
        offset (int, optional): Pagination offset. Defaults to 0.
        ctx (SessionContext): The current session context.

    Returns:
        dict[str, Any]: Paginated list of timecard entries.
    """
    timecards = otl_client.list_timecard_entries(
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
def labour_assignments(
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    """
    Retrieves the assigned work orders, projects, and tasks for the employee.

    Args:
        ctx (SessionContext): The current session context.

    Returns:
        dict[str, Any]: The employee's authorized labour catalogue assignments.
    """
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": otl_client.list_worker_assignments(otl_client.service_credential(), ctx.employee_id, ctx.full_name),
    }


@app.post("/api/admin/refresh-catalogue")
async def refresh_catalogue() -> dict[str, Any]:
    """Re-export data from Oracle Fusion and reload the local catalogue."""
    await fusion_catalogue.refresh_catalogue()
    return fusion_catalogue.status()


@app.get("/api/admin/catalogue-status")
def catalogue_status() -> dict[str, Any]:
    """Returns the current catalogue status."""
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
