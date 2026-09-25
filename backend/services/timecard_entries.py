from __future__ import annotations

import json
import os
import re
from datetime import date
from datetime import time as dt_time
from decimal import Decimal, InvalidOperation
from typing import Any

from ..core.auth import SessionContext

_FENCED_JSON = re.compile(
    r"```(?:json)?\s*([{\[][\s\S]*?[}\]])\s*```",
    re.MULTILINE | re.IGNORECASE,
)

MAX_TIMECARD_ENTRIES = 100
MAX_HOURS_PER_ENTRY = 24.0
MAX_HOURS_PER_DAY = 24.0
ALLOWED_PAYROLL_TIME_TYPES = (
    "Regular",
    "Overtime",
    "Extended Day Overtime",
    "Shift Differential",
    "Holiday",
    "Sick",
    "Vacation",
    "Unpaid Leave",
)
ALLOWED_EXPENDITURE_TYPES = (
    "Professional Services",
    "Regular Time",
    "Dev",
)


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    norm = dict(entry)
    aliases = {
        "project_number": "projectNo",
        "project_name": "projectName",
        "task_name": "taskDetails",
        "work_order_number": "workOrder",
        "person_number": "employeeNumber",
        "employee_name": "employeeName",
        "request_id": "requestId",
        "idempotency_key": "idempotencyKey",
    }
    for source, target in aliases.items():
        if source in norm and target not in norm:
            norm[target] = norm[source]
    return norm


def _extract_entries(assistant_message: str) -> list[dict[str, Any]]:
    if not assistant_message:
        return []
    match = _FENCED_JSON.search(assistant_message)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("Assistant generated malformed timecard JSON.") from exc
        if isinstance(data, list):
            return [_normalize_entry(e) for e in data if isinstance(e, dict)]
        if isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, list):
                return [_normalize_entry(e) for e in entries if isinstance(e, dict)]
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
        _STRICT_ASSIGNMENT_CACHE = (
            os.getenv("STRICT_ASSIGNMENT", "true").strip().lower() != "false"
        )
    return _STRICT_ASSIGNMENT_CACHE


def _positive_number(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _entry_hours(entry: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    number = _positive_number(entry.get("hours"))
    if number is None:
        return None, "Hours is required and must be a finite number"
    if number <= 0:
        return None, "Hours must be greater than zero"
    quarter_units = number * 4
    if quarter_units != quarter_units.to_integral_value():
        return None, "Hours must be a whole number, half hour, or quarter hour"
    configured_entry_max = _positive_number(
        os.getenv("MAX_TIMECARD_HOURS_PER_ENTRY", str(MAX_HOURS_PER_ENTRY))
    )
    entry_max = configured_entry_max or Decimal(str(MAX_HOURS_PER_ENTRY))
    if number > entry_max:
        return None, f"Hours for one entry cannot exceed {_format_limit(entry_max)}"
    return number, None


def _format_limit(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.25"))).rstrip("0").rstrip(".")


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Date must be a string in YYYY-MM-DD format.")
    if value == "":
        raise ValueError("Date cannot be empty.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Invalid date format. Expected YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid date value. Expected a real calendar date.") from exc


def _parse_time(field: str, value: Any) -> dt_time | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string in HH:MM format.")
    if value == "":
        raise ValueError(f"{field} cannot be empty.")
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"Invalid {field} format. Expected HH:MM.")
    try:
        return dt_time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field} value. Expected a real 24-hour time."
        ) from exc


def _minutes(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def _validate_times(entry: dict[str, Any], hours: Decimal) -> str | None:
    try:
        start = _parse_time("startTime", entry.get("startTime"))
        stop = _parse_time("stopTime", entry.get("stopTime"))
    except (TypeError, ValueError) as exc:
        return str(exc)
    if stop is not None and start is None:
        return "stopTime requires an explicit startTime."
    if start is None or stop is None:
        return None
    start_minutes = _minutes(start)
    stop_minutes = _minutes(stop)
    if stop_minutes <= start_minutes:
        return "startTime must be earlier than stopTime on the same day."
    measured_minutes = int(hours * 60)
    if stop_minutes - start_minutes != measured_minutes:
        return "stopTime must exactly match startTime plus the submitted hours."
    return None


def _configured_allowlist(
    names: tuple[str, ...], defaults: tuple[str, ...]
) -> frozenset[str]:
    configured: str | None = None
    for name in names:
        value = os.getenv(name)
        if value is not None:
            configured = value
            break
    values = defaults if configured is None else configured.split(",")
    return frozenset(value.strip() for value in values if value.strip())


def _validate_allowlisted_value(
    entry: dict[str, Any],
    field: str,
    env_names: tuple[str, ...],
    defaults: tuple[str, ...],
) -> str | None:
    if field not in entry:
        return None
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        return f"{field} must be a non-empty string when supplied."
    allowed = _configured_allowlist(env_names, defaults)
    if value.strip() not in allowed:
        return f"{field} is not in the configured allowlist."
    return None


def _validate_payroll_values(entry: dict[str, Any]) -> str | None:
    payroll_error = _validate_allowlisted_value(
        entry,
        "payrollTimeType",
        (
            "OTL_ALLOWED_PAYROLL_TIME_TYPES",
            "ALLOWED_PAYROLL_TIME_TYPES",
            "PAYROLL_TIME_TYPE_ALLOWLIST",
        ),
        ALLOWED_PAYROLL_TIME_TYPES,
    )
    if payroll_error:
        return payroll_error
    return _validate_allowlisted_value(
        entry,
        "expenditureType",
        (
            "OTL_ALLOWED_EXPENDITURE_TYPES",
            "ALLOWED_EXPENDITURE_TYPES",
            "EXPENDITURE_TYPE_ALLOWLIST",
        ),
        ALLOWED_EXPENDITURE_TYPES,
    )


def _entry_idempotency_error(entry: dict[str, Any]) -> str | None:
    from .idempotency import IdempotencyKeyError, idempotency_key_for_entry

    try:
        idempotency_key_for_entry(entry)
    except IdempotencyKeyError as exc:
        return str(exc)
    return None


def _text_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _assigned_project(
    entry: dict[str, Any], assignments: list[dict[str, Any]] | None
) -> tuple[dict[str, Any] | None, str | None]:
    if assignments is None:
        return None, None
    project_no = _text_value(entry.get("projectNo"))
    project_name = _text_value(entry.get("projectName"))
    matches: list[dict[str, Any]] = []
    for order in assignments:
        projects = order.get("projects", []) if isinstance(order, dict) else []
        if not isinstance(projects, list):
            continue
        for project in projects:
            if not isinstance(project, dict):
                continue
            if project_no:
                if _text_value(project.get("projectNo")) != project_no:
                    continue
            elif (
                project_name and _text_value(project.get("projectName")) == project_name
            ):
                pass
            else:
                continue
            matches.append({**project, "workOrder": order.get("workOrder")})
    if not matches:
        return None, "Project is not in your assigned projects."
    identity = {
        (
            _text_value(match.get("projectId")),
            _text_value(match.get("projectNo")),
            _text_value(match.get("projectName")),
            _text_value(match.get("workOrder")),
        )
        for match in matches
    }
    if len(identity) > 1:
        return None, "Project reference is ambiguous. Select one assigned project."
    selected = matches[0]
    if project_name and _text_value(selected.get("projectName")) != project_name:
        return None, "Project name does not match the assigned project number."
    supplied_work_order = _text_value(entry.get("workOrder"))
    assigned_work_order = _text_value(selected.get("workOrder"))
    if supplied_work_order and assigned_work_order != supplied_work_order:
        return None, "Work order does not match the assigned project."
    return selected, None


def _validate_timecard_entry(
    entry: dict[str, Any],
    assignments: list[dict[str, Any]] | None = None,
    *,
    require_assignment: bool = True,
) -> tuple[bool, str | None]:
    entry = _normalize_entry(entry)
    hours, hours_error = _entry_hours(entry)
    if hours_error:
        return False, hours_error
    assert hours is not None
    idempotency_error = _entry_idempotency_error(entry)
    if idempotency_error:
        return False, idempotency_error
    try:
        _parse_date(entry.get("date"))
    except (TypeError, ValueError) as exc:
        return False, str(exc)
    time_error = _validate_times(entry, hours)
    if time_error:
        return False, time_error
    payroll_error = _validate_payroll_values(entry)
    if payroll_error:
        return False, payroll_error
    if require_assignment:
        has_project = bool(
            _text_value(entry.get("projectNo"))
            or _text_value(entry.get("projectName"))
            or _text_value(entry.get("projectId"))
        )
        if not has_project:
            return False, "Project number or project name is required"
        if not _text_value(entry.get("taskDetails")):
            return False, "Task details are required"
    if assignments is not None and _strict_assignment():
        selected, assignment_error = _assigned_project(entry, assignments)
        if assignment_error:
            return False, assignment_error
        if selected is None:
            return False, "Project is not in your assigned projects."
        task_id = _text_value(entry.get("taskId"))
        if task_id:
            allowed_task_ids = {
                _text_value(task.get("taskId"))
                for task in selected.get("tasks", []) or []
                if isinstance(task, dict) and _text_value(task.get("taskId"))
            }
            if task_id not in allowed_task_ids:
                project_no = _text_value(entry.get("projectNo"))
                suffix = f" project {project_no}." if project_no else "."
                return False, f"Task is not assigned to{suffix}"
    return True, None


def _validate_timecard_entries(
    entries: list[dict[str, Any]], assignments: list[dict[str, Any]] | None = None
) -> tuple[bool, str | None]:
    daily_totals: dict[str, Decimal] = {}
    configured_day_max = _positive_number(
        os.getenv("MAX_TIMECARD_HOURS_PER_DAY", str(MAX_HOURS_PER_DAY))
    )
    day_max = configured_day_max or Decimal(str(MAX_HOURS_PER_DAY))
    for index, entry in enumerate(entries):
        valid, error = _validate_timecard_entry(entry, assignments)
        if not valid:
            return False, f"Entry {index + 1}: {error}"
        normalized = _normalize_entry(entry)
        hours, _ = _entry_hours(normalized)
        assert hours is not None
        day = _text_value(normalized.get("date")) or "__undated__"
        daily_totals[day] = daily_totals.get(day, Decimal(0)) + hours
        if daily_totals[day] > day_max:
            if day == "__undated__":
                return (
                    False,
                    "Entry total hours cannot exceed the configured daily limit.",
                )
            return (
                False,
                f"Entry {index + 1}: Total hours for {day} exceed the {_format_limit(day_max)}-hour daily limit.",
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
    project, _ = _assigned_project(norm, assignments)
    resolved.update(
        {
            "projectId": project.get("projectId") if project else norm.get("projectId"),
            "projectNo": project.get("projectNo") if project else norm.get("projectNo"),
            "workOrder": project.get("workOrder") if project else norm.get("workOrder"),
            "projectName": project.get("projectName")
            if project
            else norm.get("projectName"),
        }
    )
    if not resolved.get("taskId") and resolved.get("taskDetails"):
        target_name = str(resolved["taskDetails"]).casefold()
        if project:
            for task in project.get("tasks", []):
                if (
                    isinstance(task, dict)
                    and str(task.get("taskDetails", "")).casefold() == target_name
                ):
                    resolved["taskId"] = task.get("taskId")
                    break
    return resolved


def _options_hint(assignments: list[dict[str, Any]]) -> str:
    projects = [
        f"{p.get('projectNo')} ({p.get('projectName')}, WO {order.get('workOrder')})"
        for order in assignments
        for p in order.get("projects", [])
        if isinstance(p, dict)
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
