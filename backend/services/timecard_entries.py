from __future__ import annotations

import json
import math
import os
import re
from datetime import date
from datetime import time as dt_time
from typing import Any

from ..core.auth import SessionContext

_FENCED_JSON = re.compile(
    r"```(?:json)?\s*([{\[][\s\S]*?[}\]])\s*```",
    re.MULTILINE | re.IGNORECASE,
)


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
        except json.JSONDecodeError as e:
            raise ValueError(f"Assistant generated malformed JSON: {e}")
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
MAX_TIMECARD_ENTRIES = 100


def _strict_assignment() -> bool:
    global _STRICT_ASSIGNMENT_CACHE
    if _STRICT_ASSIGNMENT_CACHE is None:
        _STRICT_ASSIGNMENT_CACHE = (
            os.getenv("STRICT_ASSIGNMENT", "true").strip().lower() != "false"
        )
    return _STRICT_ASSIGNMENT_CACHE


def _validate_timecard_entry(
    entry: dict[str, Any], assignments: list[dict[str, Any]] | None = None
) -> tuple[bool, str | None]:
    entry = _normalize_entry(entry)
    hours = entry.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        return False, "Hours is required and must be a finite number"
    try:
        finite_hours = math.isfinite(hours)
    except (OverflowError, TypeError):
        finite_hours = False
    if not finite_hours:
        return False, "Hours must be a finite number"
    if hours <= 0:
        return False, "Hours must be greater than zero"
    if (
        not entry.get("projectNo")
        and not entry.get("projectName")
        and not (not _strict_assignment() and entry.get("projectId"))
    ):
        return False, "Project number or project name is required"
    if not entry.get("taskDetails"):
        return False, "Task details are required"
    date_raw = entry.get("date")
    if date_raw is not None and not isinstance(date_raw, str):
        return False, "Date must be a string in YYYY-MM-DD format."
    date_str = date_raw
    if date_str == "":
        return False, "Date cannot be empty."
    if date_str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."
        try:
            date.fromisoformat(date_str)
        except ValueError:
            return False, f"Invalid date '{date_str}'."
    for time_field in ["startTime", "stopTime"]:
        time_raw = entry.get(time_field)
        if time_raw is not None and not isinstance(time_raw, str):
            return False, f"{time_field} must be a string in HH:MM format."
        time_str = time_raw
        if time_str == "":
            return False, f"{time_field} cannot be empty."
        if time_str:
            if not re.match(r"^\d{2}:\d{2}$", time_str):
                return (
                    False,
                    f"Invalid {time_field} format '{time_str}'. Expected HH:MM.",
                )
            try:
                dt_time.fromisoformat(time_str)
            except ValueError:
                return False, f"Invalid {time_field} value '{time_str}'."
    if assignments is not None and _strict_assignment():
        project_no = entry.get("projectNo")
        project_name = entry.get("projectName")
        selected_project = None
        for order in assignments:
            for p in order.get("projects", []):
                if project_no and str(p.get("projectNo")) == str(project_no):
                    selected_project = p
                    break
                if (
                    not project_no
                    and project_name
                    and p.get("projectName") == project_name
                ):
                    selected_project = p
                    break
            if selected_project is not None:
                break
        if selected_project is None:
            return (
                False,
                f"Project {project_no or project_name} is not in your assigned projects",
            )
        task_id = entry.get("taskId")
        if task_id is not None and task_id != "":
            allowed_task_ids = {
                str(task.get("taskId")).strip()
                for task in selected_project.get("tasks", []) or []
                if isinstance(task, dict)
                and task.get("taskId") is not None
                and str(task.get("taskId")).strip()
            }
            if str(task_id).strip() not in allowed_task_ids:
                return (
                    False,
                    f"Task {task_id} is not assigned to project {project_no or project_name}",
                )
    return True, None


def _resolve_entry(
    entry: dict[str, Any],
    ctx: SessionContext,
    assignments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    norm = _normalize_entry(entry)
    resolved = dict(norm)
    resolved["employeeNumber"] = ctx.employee_id
    resolved["employeeName"] = ctx.full_name
    project = None
    project_no = norm.get("projectNo")
    for order in assignments or []:
        for p in order.get("projects", []):
            if project_no and str(p.get("projectNo")) == str(project_no):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
            if (
                not project_no
                and norm.get("projectName")
                and p.get("projectName") == norm.get("projectName")
            ):
                project = dict(p)
                project["workOrder"] = order.get("workOrder")
                break
        if project:
            break
    resolved.update(
        {
            "projectId": project.get("projectId") if project else norm.get("projectId"),
            "projectNo": project.get("projectNo") if project else project_no,
            "workOrder": project.get("workOrder") if project else norm.get("workOrder"),
            "projectName": project.get("projectName")
            if project
            else norm.get("projectName"),
        }
    )
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
