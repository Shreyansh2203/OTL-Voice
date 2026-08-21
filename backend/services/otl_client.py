

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

# Max length Oracle allows on the string attributes we write.
_STR_MAX = 80

def base_url() -> str:
    """
    Retrieves the base URL for the OTL REST API from the environment.

    Raises:
        ValueError: If OTL_BASE_URL is not set.

    Returns:
        str: The normalized base URL.
    """
    url = os.getenv("OTL_BASE_URL")
    if not url:
        raise ValueError("OTL_BASE_URL environment variable is not set. Please configure it in .env")
    return url.rstrip("/")
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
    """
    Constructs the OTL service account credentials from environment variables.

    Raises:
        OtlConfigError: If service account credentials are not configured.

    Returns:
        OtlCredential: The credentials for the Oracle Fusion service account.
    """
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
        return (resp.text or "")[:2000]


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _clip(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:_STR_MAX]


# --------------------------------------------------------------------------- #
# App entry -> OTL record body
# --------------------------------------------------------------------------- #
def map_entry_to_otl(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Maps a standardized timecard entry dictionary to the Oracle Fusion HCM payload format.

    Args:
        entry (dict[str, Any]): The raw timecard entry.

    Raises:
        OtlError: If the hours are <= 0 or the date format is invalid.

    Returns:
        dict[str, Any]: The payload formatted for the timeRecordEventRequests endpoint.
    """
    emp_num = str(entry.get("employeeNumber") or "UNKNOWN_EMP").strip()
    hours = _coerce_int(entry.get("hours")) or 0
    if hours <= 0:
        raise OtlError(400, f"Timecard entry hours must be greater than zero, got {hours}.")
        
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
        raise OtlError(400, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD.")

    # Parse or synthesize start time
    default_start_hour = int(os.getenv("DEFAULT_START_HOUR", "9"))
    try:
        if start_time_str:
            h1, m1 = map(int, start_time_str.split(":"))
            start_dt = base_dt.replace(hour=h1, minute=m1)
        else:
            start_dt = base_dt.replace(hour=default_start_hour, minute=0) # fallback
    except Exception:
        start_dt = base_dt.replace(hour=default_start_hour, minute=0)
        
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
        attrs.append({
            "attributeName": "Comment",
            "attributeValue": _clip(" | ".join(parts)),
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
        
    # In a full implementation, expenditure types would be fetched dynamically per project.
    # We default to a typical value if one is provided, or from env/Professional Services as a fallback.
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


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def validate(cred: OtlCredential) -> dict[str, Any]:
    """
    Validates the provided OTL credentials by making a minimal API request.

    Args:
        cred (OtlCredential): The credentials to validate.

    Raises:
        OtlError: If the credentials are rejected or the API request fails.

    Returns:
        dict[str, Any]: A success status dictionary.
    """
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
    query: str | None = None,
    person_number: str | None = None,
) -> dict[str, Any]:
    """
    Retrieves a paginated list of timecard entries from Oracle Fusion.

    Args:
        cred (OtlCredential): The credentials used for authentication.
        limit (int, optional): The maximum number of entries to return. Defaults to 25.
        offset (int, optional): The offset for pagination. Defaults to 0.
        query (str | None, optional): An optional query string to filter entries. Defaults to None.
        person_number (str | None, optional): Filter records by the worker's person number.

    Returns:
        dict[str, Any]: The paginated timecard response payload from Oracle Fusion.
    """
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "expand": "timeAttributes",
    }
    
    q_parts = []
    if query:
        q_parts.append(query)
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
    # Extracts the resources base path from the timeRecordEventRequests URL
    url = base_url()
    if "/timeRecordEventRequests" in url:
        return url.replace("/timeRecordEventRequests", "")
    return url


def get_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    """
    Fetches the worker details from Fusion HCM by PersonNumber.
    """
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
    # Extract names (Fusion returns a dict with 'items' when expanded)
    names = worker.get("names", [])
    if isinstance(names, dict):
        names = names.get("items", [])
        
    full_name = "Unknown Name"
    if names and len(names) > 0:
        full_name = names[0].get("DisplayName", full_name)
        
    return {
        "personId": worker.get("PersonId"),
        "personNumber": worker.get("PersonNumber"),
        "fullName": full_name,
        "isActive": True # Simplification for the demo
    }


def list_worker_assignments(cred: OtlCredential, person_number: str, full_name: str = "") -> list[dict[str, Any]]:
    """
    Fetches the projects and work orders this worker is allowed to charge time to.
    Reads from the live Fusion catalogue (fetched on startup from PPM APIs).
    """
    from . import fusion_catalogue
    return fusion_catalogue.list_assignments_for_worker(person_number, full_name)


def get_timecard_entry(cred: OtlCredential, record_id: Any) -> dict[str, Any]:
    """
    Fetches a specific timecard entry by its ID.

    Args:
        cred (OtlCredential): The credentials used for authentication.
        record_id (Any): The unique identifier of the timecard record.

    Returns:
        dict[str, Any]: The timecard entry details.
    """
    with _client(cred) as client:
        resp = client.get(f"{base_url()}/{record_id}")
    _raise_for_status(resp)
    return resp.json()


def create_timecard_entry(
    cred: OtlCredential, entry: dict[str, Any]
) -> dict[str, Any]:
    """
    Creates a single timecard entry in Oracle Fusion.

    Args:
        cred (OtlCredential): The credentials used for authentication.
        entry (dict[str, Any]): The timecard entry payload.

    Returns:
        dict[str, Any]: The created timecard entry response.
    """
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
    """
    Deletes a specific timecard entry by its ID.

    Args:
        cred (OtlCredential): The credentials used for authentication.
        record_id (Any): The unique identifier of the timecard record to delete.
    """
    with _client(cred) as client:
        resp = client.delete(f"{base_url()}/{record_id}")
    _raise_for_status(resp)


def create_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Submits multiple timecard entries to Oracle Fusion, handling individual successes and failures.

    Args:
        cred (OtlCredential): The credentials used for authentication.
        entries (list[dict[str, Any]]): A list of timecard entry payloads to submit.

    Returns:
        list[dict[str, Any]]: A list of dictionaries detailing the success or failure of each entry.
    """
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
