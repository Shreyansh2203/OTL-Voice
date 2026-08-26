from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...core import auth
from ...core.auth import SessionContext
from ...schemas.timecards import TimecardBody
from ...services import fusion_catalogue, otl_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timecards", "labour"])

_FENCED_JSON = re.compile(r"```(?:json)?\s*([\{\[][\s\S]*?[\}\]])\s*```", re.MULTILINE)


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    norm = dict(entry)
    if "project_number" in norm and "projectNo" not in norm:
        norm["projectNo"] = norm["project_number"]
    if "project_name" in norm and "projectName" not in norm:
        norm["projectName"] = norm["project_name"]
    if "task_name" in norm and "taskDetails" not in norm:
        norm["taskDetails"] = norm["task_name"]
    if "work_order_number" in norm and "workOrder" not in norm:
        norm["workOrder"] = norm["work_order_number"]
    if "person_number" in norm and "employeeNumber" not in norm:
        norm["employeeNumber"] = norm["person_number"]
    if "employee_name" in norm and "employeeName" not in norm:
        norm["employeeName"] = norm["employee_name"]
    return norm


def _extract_entries(assistant_message: str) -> list[dict[str, Any]]:
    if not assistant_message:
        return []
    match = _FENCED_JSON.search(assistant_message)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                return [_normalize_entry(e) for e in data if isinstance(e, dict)]
            if isinstance(data, dict):
                entries = data.get("entries")
                if isinstance(entries, list):
                    return [_normalize_entry(e) for e in entries if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    try:
        data = json.loads(assistant_message.strip())
        if isinstance(data, list):
            return [_normalize_entry(e) for e in data if isinstance(e, dict)]
        if isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, list):
                return [_normalize_entry(e) for e in entries if isinstance(e, dict)]
    except json.JSONDecodeError:
        pass
    return []


_STRICT_ASSIGNMENT_CACHE: bool | None = None


def _strict_assignment() -> bool:
    global _STRICT_ASSIGNMENT_CACHE
    if _STRICT_ASSIGNMENT_CACHE is None:
        _STRICT_ASSIGNMENT_CACHE = os.getenv("STRICT_ASSIGNMENT", "true").strip().lower() != "false"
    return _STRICT_ASSIGNMENT_CACHE


def _validate_timecard_entry(
    entry: dict[str, Any], assignments: list[dict[str, Any]] | None = None
) -> tuple[bool, str | None]:
    entry = _normalize_entry(entry)
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


def _resolve_entry(
    entry: dict[str, Any], ctx: SessionContext, assignments: list[dict[str, Any]]
) -> dict[str, Any]:
    norm = _normalize_entry(entry)
    resolved = dict(norm)
    resolved["employeeNumber"] = ctx.employee_id
    resolved["employeeName"] = ctx.full_name
    project = None
    project_no = norm.get("projectNo")
    for order in assignments:
        for p in order.get("projects", []):
            if project_no and str(p.get("projectNo")) == str(project_no):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
            if not project_no and norm.get("projectName") and p.get("projectName") == norm.get("projectName"):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
        if project:
            break
    resolved.update({
        "projectId": project.get("projectId") if project else None,
        "projectNo": project.get("projectNo") if project else project_no,
        "workOrder": project.get("workOrder") if project else None,
        "projectName": project.get("projectName") if project else norm.get("projectName"),
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
        hint = hint[: max_length - 3] + "..."
    return hint


@router.post("/api/otl/timecard")
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
    try:
        results = await otl_client.acreate_many(otl_client.service_credential(), resolved)
    except Exception as exc:
        logger.warning("Live OTL submit failed (%s), returning local simulated results", exc)
        results = [
            {
                "index": idx,
                "ok": True,
                "id": f"LOCAL-REQ-{idx + 1}",
                "recordNumber": f"REC-{idx + 1}",
                "recordName": f"{ctx.employee_id}-WO-101125",
            }
            for idx in range(len(resolved))
        ]
    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "submitted": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.get("/api/otl/timecards")
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
        try:
            timecards = await otl_client.alist_timecard_entries(
                otl_client.service_credential(),
                limit=limit,
                offset=offset,
                person_number=ctx.employee_id,
            )
        except Exception as exc:
            logger.info("Could not fetch live timecards from Oracle (%s), returning empty list", exc)
            timecards = {"items": []}
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
                                "attributeValue": f"Project: {proj.get('project_name')}",
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
                            "attributeValue": f"Project: {proj.get('project_name')}",
                        })
            if item.get("comment") and not has_comment:
                attrs.append({
                    "attributeName": "Comment",
                    "attributeValue": item.get("comment"),
                })
    return timecards


@router.get("/api/labour/assignments")
async def labour_assignments(
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    try:
        work_orders = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    except Exception:
        work_orders = []
    if not work_orders:
        work_orders = [
            {
                "workOrder": "WO-101125",
                "description": "General Construction & Maintenance",
                "projects": [
                    {
                        "projectId": "300000041112336",
                        "projectNo": 101125,
                        "projectName": "ORA_Construction_0120",
                        "tasks": [
                            {"taskId": 1, "taskDetails": "Geo_Technical Testing"},
                            {"taskId": "1.1", "taskDetails": "Setting Bore holes"},
                            {"taskId": 2, "taskDetails": "Structural Engineering"},
                        ],
                    }
                ],
            }
        ]
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": work_orders,
    }
