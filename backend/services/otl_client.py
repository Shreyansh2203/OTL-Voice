
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

_STR_MAX = 80
def base_url() -> str:
    url = os.getenv("OTL_BASE_URL")
    if not url:
        raise ValueError("OTL_BASE_URL environment variable is not set. Please configure it in .env")
    return url.rstrip("/")
def _timeout() -> httpx.Timeout:
    secs = float(os.getenv("OTL_TIMEOUT_SECONDS", "30"))
    return httpx.Timeout(secs, connect=10.0)
@dataclass(frozen=True)
class OtlCredential:
    username: str
    password: str
    @property
    def auth(self) -> tuple[str, str]:
        return (self.username, self.password)
class OtlError(Exception):
    def __init__(self, status_code: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail
class OtlConfigError(RuntimeError):
    pass
def service_credential() -> OtlCredential:
    username = os.getenv("OTL_SERVICE_USERNAME", "").strip()
    password = os.getenv("OTL_SERVICE_PASSWORD", "")
    if not username or not password:
        raise OtlConfigError(
            "OTL service account is not configured. Set OTL_SERVICE_USERNAME and "
            "OTL_SERVICE_PASSWORD in the environment."
        )
    return OtlCredential(username=username, password=password)
def _client(cred: OtlCredential) -> httpx.Client:
    return httpx.Client(
        auth=cred.auth,
        timeout=_timeout(),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )
def _extract_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("detail") or data.get("title") or data.get("message")
            if msg:
                return str(msg)
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text or f"OTL request failed with HTTP {resp.status_code}"
def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise OtlError(resp.status_code, _extract_error(resp), detail=_safe_body(resp))
def _safe_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return (resp.text or "")[:10000]
def _coerce_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
def _clip(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:_STR_MAX]
def map_entry_to_otl(entry: dict[str, Any]) -> dict[str, Any]:
    emp_num = entry.get("employeeNumber")
    if not emp_num:
        raise OtlError(400, "employeeNumber is required.")
    emp_num = str(emp_num).strip()
    hours = _coerce_number(entry.get("hours")) or 0
    if hours <= 0:
        raise OtlError(400, f"Timecard entry hours must be greater than zero, got {hours}.")
    now = datetime.now(UTC)
    start_time_str = entry.get("startTime")
    stop_time_str = entry.get("stopTime")
    date_str = entry.get("date")
    try:
        if date_str:
            y, m, d = map(int, date_str.split("-"))
            base_dt = datetime(year=y, month=m, day=d, tzinfo=UTC)
        else:
            base_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        raise OtlError(400, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD.")
    default_start_hour = int(os.getenv("DEFAULT_START_HOUR", "9"))
    if start_time_str:
        try:
            h1, m1 = map(int, start_time_str.split(":"))
            start_dt = base_dt.replace(hour=h1, minute=m1)
        except Exception:
            raise OtlError(400, f"Invalid startTime format '{start_time_str}'. Expected HH:MM.")
    else:
        start_dt = base_dt.replace(hour=default_start_hour, minute=0) 
    if stop_time_str:
        try:
            h2, m2 = map(int, stop_time_str.split(":"))
            stop_dt = base_dt.replace(hour=h2, minute=m2)
        except Exception:
            raise OtlError(400, f"Invalid stopTime format '{stop_time_str}'. Expected HH:MM.")
    else:
        stop_dt = start_dt + timedelta(hours=hours)

    if stop_dt < start_dt:
        stop_dt += timedelta(days=1)
    start_time = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    stop_time = stop_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    parts: list[str] = []
    project_name = entry.get("projectName")
    if project_name:
        project_no = entry.get("projectNo")
        parts.append(f"Project: {project_name}" + (f" ({project_no})" if project_no else ""))
    task_details = entry.get("taskDetails")
    if task_details:
        parts.append(f"Task: {task_details}")
    work_order = entry.get("workOrder")
    if work_order:
        parts.append(f"WO: {work_order}")
    parts.append(f"Total Hours: {hours}")
    event: dict[str, Any] = {
        "measure": hours,
        "reporterIdType": "PERSON",
        "reporterId": emp_num,
        "operationType": "ADD",
    }
    if start_time and stop_time:
        event["startTime"] = start_time
        event["stopTime"] = stop_time
    attrs: list[dict[str, str]] = []
    if parts:
        comment_str = " | ".join(parts)
        if len(comment_str) > _STR_MAX:
            total_hours_part = parts[-1]
            allowed_len = _STR_MAX - len(total_hours_part) - 3
            if allowed_len > 0:
                rest = " | ".join(parts[:-1])
                comment_str = rest[:allowed_len] + " | " + total_hours_part
            else:
                comment_str = total_hours_part[:_STR_MAX]
        attrs.append({
            "attributeName": "Comment",
            "attributeValue": comment_str,
        })
    payroll_time_type = entry.get("payrollTimeType")
    if payroll_time_type:
        attrs.append({
            "attributeName": "PayrollTimeType",
            "attributeValue": str(payroll_time_type),
        })
    project_id = entry.get("projectId")
    if project_id:
        attrs.append({
            "attributeName": "PJC_PROJECT_ID",
            "attributeValue": str(project_id),
        })
    task_id = entry.get("taskId")
    if task_id:
        attrs.append({
            "attributeName": "PJC_TASK_ID",
            "attributeValue": str(task_id),
        })
    default_expenditure_type = os.getenv("DEFAULT_EXPENDITURE_TYPE", "Professional Services")
    expenditure_type = entry.get("expenditureType", default_expenditure_type)
    if project_id and expenditure_type:
        attrs.append({
            "attributeName": "PJC_EXPENDITURE_TYPE_NAME",
            "attributeValue": expenditure_type,
        })
    if attrs:
        event["timeRecordEventAttribute"] = attrs
    return {
        "processInline": "Y",
        "processMode": "TIME_ENTER",
        "timeRecordEvent": [event],
    }
def _default_record_name(entry: dict[str, Any]) -> str:
    emp = str(entry.get("employeeNumber") or "EMP").strip()
    wo = str(entry.get("workOrder") or "WO").strip()
    return f"{emp}-{wo}-{int(time.time() * 1000) % 1_000_000}"
def validate(cred: OtlCredential) -> dict[str, Any]:
    with _client(cred) as client:
        resp = client.get(base_url(), params={"limit": 1})
    if resp.status_code in (401, 403):
        raise OtlError(
            resp.status_code,
            "OTL rejected the service account credential. Check "
            "OTL_SERVICE_USERNAME / OTL_SERVICE_PASSWORD.",
        )
    _raise_for_status(resp)
    return {"ok": True, "username": cred.username}
def escape_q_literal(value: str) -> str:
    return str(value).replace("'", "''")
def list_timecard_entries(
    cred: OtlCredential,
    limit: int = 25,
    offset: int = 0,
    person_number: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "expand": "timeAttributes",
    }
    q_parts = []
    if person_number:
        q_parts.append(f"personNumber='{escape_q_literal(person_number)}'")
    if q_parts:
        params["q"] = " AND ".join(q_parts)
    url = base_url().replace("/timeRecordEventRequests", "/timeRecords")
    with _client(cred) as client:
        resp = client.get(url, params=params)
    _raise_for_status(resp)
    return resp.json()
def hcm_base_url() -> str:
    url = base_url()
    if "/timeRecordEventRequests" in url:
        return url.replace("/timeRecordEventRequests", "")
    return url
def get_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    with _client(cred) as client:
        resp = client.get(
            f"{hcm_base_url()}/workers",
            params={
                "q": f"PersonNumber='{escape_q_literal(person_number)}'",
                "expand": "names",
                "limit": 1
            }
        )
    _raise_for_status(resp)
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return None
    worker = items[0]
    names = worker.get("names", [])
    if isinstance(names, dict):
        names = names.get("items", [])
    full_name = "Unknown Name"
    if names and len(names) > 0:
        full_name = str(names[0].get("DisplayName") or full_name).strip()
    return {
        "personId": worker.get("PersonId"),
        "personNumber": worker.get("PersonNumber"),
        "fullName": full_name,
        "isActive": worker.get("ActiveFlag", True)  # Documented: actual status might require expanding workRelationships
    }
def list_worker_assignments(cred: OtlCredential, person_number: str, full_name: str = "") -> list[dict[str, Any]]:
    from . import fusion_catalogue
    return fusion_catalogue.list_assignments_for_worker(person_number, full_name)
def get_timecard_entry(cred: OtlCredential, record_id: Any) -> dict[str, Any]:
    with _client(cred) as client:
        resp = client.get(f"{base_url()}/{record_id}")
    _raise_for_status(resp)
    return resp.json()
def create_timecard_entry(
    cred: OtlCredential, entry: dict[str, Any]
) -> dict[str, Any]:
    body = map_entry_to_otl(entry)
    with _client(cred) as client:
        resp = client.post(
            base_url(),
            json=body,
            headers={"Content-Type": "application/json"},
        )
    _raise_for_status(resp)
    return resp.json()
def delete_timecard_entry(cred: OtlCredential, record_id: Any) -> None:
    with _client(cred) as client:
        resp = client.delete(f"{base_url()}/{record_id}")
    _raise_for_status(resp)
def create_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        try:
            created = create_timecard_entry(cred, entry)
            results.append(
                {
                    "index": index,
                    "ok": True,
                    "id": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordNumber": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordName": _default_record_name(entry),
                }
            )
        except OtlError as exc:
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "status": exc.status_code,
                    "error": exc.message,
                }
            )
    return results
def _async_client(cred: OtlCredential) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=cred.auth,
        timeout=_timeout(),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )
async def avalidate(cred: OtlCredential) -> dict[str, Any]:
    async with _async_client(cred) as client:
        resp = await client.get(base_url(), params={"limit": 1})
    if resp.status_code in (401, 403):
        raise OtlError(
            resp.status_code,
            "OTL rejected the service account credential. Check "
            "OTL_SERVICE_USERNAME / OTL_SERVICE_PASSWORD.",
        )
    _raise_for_status(resp)
    return {"ok": True, "username": cred.username}
async def aget_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(get_worker, cred, person_number)
async def alist_timecard_entries(
    cred: OtlCredential, limit: int = 10, offset: int = 0, person_number: str | None = None
) -> dict[str, Any]:
    return await asyncio.to_thread(list_timecard_entries, cred, limit, offset, person_number)
async def acreate_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        try:
            created = await acreate_timecard_entry(cred, entry)
            results.append(
                {
                    "index": index,
                    "ok": True,
                    "id": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordNumber": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordName": _default_record_name(entry),
                }
            )
        except OtlError as exc:
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "status": exc.status_code,
                    "error": exc.message,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "status": 500,
                    "error": str(exc),
                }
            )
    return results
async def alist_worker_assignments(
    cred: OtlCredential, person_number: str, full_name: str = ""
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_worker_assignments, cred, person_number, full_name)
async def acreate_timecard_entry(cred: OtlCredential, entry: dict[str, Any]) -> dict[str, Any]:
    async with _async_client(cred) as client:
        resp = await client.post(base_url(), json=map_entry_to_otl(entry))
    _raise_for_status(resp)
    return resp.json()