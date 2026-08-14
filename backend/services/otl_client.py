

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BASE_URL = (
    "https://fa-epxp-test-saasfaprod1.fa.ocs.oraclecloud.com"
    "/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests"
)

# Max length Oracle allows on the string attributes we write.
_STR_MAX = 80


def base_url() -> str:
    return (os.getenv("OTL_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> httpx.Timeout:
    secs = float(os.getenv("OTL_TIMEOUT_SECONDS", "30"))
    return httpx.Timeout(secs, connect=10.0)


# --------------------------------------------------------------------------- #
# Credential + errors
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
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
    except Exception:  # noqa: BLE001 - fall back to text below
        pass
    text = (resp.text or "").strip()
    return text or f"OTL request failed with HTTP {resp.status_code}"


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise OtlError(resp.status_code, _extract_error(resp), detail=_safe_body(resp))


def _safe_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return (resp.text or "")[:2000]


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _clip(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)[:_STR_MAX]


# --------------------------------------------------------------------------- #
# App entry -> OTL record body
# --------------------------------------------------------------------------- #
def map_entry_to_otl(entry: Dict[str, Any]) -> Dict[str, Any]:
    emp_num = str(entry.get("employeeNumber") or "UNKNOWN_EMP").strip()
    hours = _coerce_int(entry.get("hours")) or 0
    now = datetime.now(UTC)
    start_time_str = entry.get("startTime")
    stop_time_str = entry.get("stopTime")
    date_str = entry.get("date")
    
    # Parse the base date (fallback to today)
    try:
        if date_str:
            y, m, d = map(int, date_str.split("-"))
            base_dt = datetime(year=y, month=m, day=d, tzinfo=UTC)
        else:
            base_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        base_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Parse or synthesize start time
    try:
        if start_time_str:
            h1, m1 = map(int, start_time_str.split(":"))
            start_dt = base_dt.replace(hour=h1, minute=m1)
        else:
            start_dt = base_dt.replace(hour=9, minute=0) # fallback 9am
    except Exception:
        start_dt = base_dt.replace(hour=9, minute=0)
        
    # Parse or synthesize stop time
    try:
        if stop_time_str:
            h2, m2 = map(int, stop_time_str.split(":"))
            stop_dt = base_dt.replace(hour=h2, minute=m2)
        else:
            stop_dt = start_dt + timedelta(hours=hours)
    except Exception:
        stop_dt = start_dt + timedelta(hours=hours)

    start_time = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    stop_time = stop_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Build a human-readable comment from the project/task/work-order fields.
    parts: List[str] = []
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

    event: Dict[str, Any] = {
        "measure": hours,
        "reporterIdType": "PERSON",
        "reporterId": emp_num,
        "operationType": "ADD",
    }
    
    
    if start_time and stop_time:
        event["startTime"] = start_time
        event["stopTime"] = stop_time
        
    attrs: List[Dict[str, str]] = []
    if parts:
        attrs.append({
            "attributeName": "Comment",
            "attributeValue": _clip(" | ".join(parts)),
        })
        
    payroll_time_type = entry.get("payrollTimeType")
    if payroll_time_type:
        attrs.append({
            "attributeName": "PayrollTimeType",
            "attributeValue": payroll_time_type,
        })
        
    if attrs:
        event["timeRecordEventAttribute"] = attrs

    return {
        "processInline": "Y",
        "processMode": "TIME_ENTER",
        "timeRecordEvent": [event],
    }


def _default_record_name(entry: Dict[str, Any]) -> str:
    emp = str(entry.get("employeeNumber") or "EMP").strip()
    wo = str(entry.get("workOrder") or "WO").strip()
    return f"{emp}-{wo}-{int(time.time() * 1000) % 1_000_000}"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def validate(cred: OtlCredential) -> Dict[str, Any]:
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
    query: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if query:
        params["q"] = query
    with _client(cred) as client:
        resp = client.get(base_url(), params=params)
    _raise_for_status(resp)
    return resp.json()


def get_timecard_entry(cred: OtlCredential, record_id: Any) -> Dict[str, Any]:
    with _client(cred) as client:
        resp = client.get(f"{base_url()}/{record_id}")
    _raise_for_status(resp)
    return resp.json()


def create_timecard_entry(
    cred: OtlCredential, entry: Dict[str, Any]
) -> Dict[str, Any]:
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
    cred: OtlCredential, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for index, entry in enumerate(entries):
        try:
            created = create_timecard_entry(cred, entry)
            results.append(
                {
                    "index": index,
                    "ok": True,
                    "id": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordNumber": created.get("timeRecordEventRequestId") or "UNKNOWN",
                    "recordName": "timeRecordEventRequest",
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
