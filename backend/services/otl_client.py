from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .idempotency import (
    IdempotencyKeyError,
    IdempotencyStore,
    IdempotencyUnavailable,
    get_idempotency_store,
    idempotency_key_for_entry,
    request_fingerprint,
    scoped_idempotency_key,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
)

_pool_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
_shared_async_client: httpx.AsyncClient | None = None
_shared_client_lock = asyncio.Lock()

_STR_MAX = 80


def base_url() -> str:
    url = os.getenv("OTL_BASE_URL")
    if not url:
        raise ValueError(
            "OTL_BASE_URL environment variable is not set. Please configure it in .env"
        )
    return url.rstrip("/")


def _timeout() -> httpx.Timeout:
    secs = float(os.getenv("OTL_TIMEOUT_SECONDS", "30"))
    return httpx.Timeout(secs, connect=10.0)


def _business_timezone():
    name = os.getenv("APP_TIMEZONE", "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown APP_TIMEZONE '%s'; using system timezone.", name)
    return datetime.now().astimezone().tzinfo or UTC


@dataclass(frozen=True)
class OtlCredential:
    username: str
    password: str

    @property
    def auth(self) -> tuple[str, str]:
        return (self.username, self.password)


class OtlError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        detail: Any = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail
        self.correlation_id = correlation_id or uuid.uuid4().hex


class OtlConfigError(RuntimeError):
    pass


def public_otl_error(status_code: int) -> str:
    if status_code in (400, 422):
        return "Oracle rejected this timecard entry."
    if status_code in (401, 403):
        return "Oracle authentication or authorization failed."
    if status_code == 404:
        return "The timecard request was not found."
    if status_code == 409:
        return "The timecard request conflicts with an existing request."
    if status_code == 429:
        return "Oracle is temporarily busy. Please retry later."
    if 500 <= status_code <= 599:
        return "Oracle Cloud is temporarily unavailable."
    return "Timecard submission failed."


def new_correlation_id() -> str:
    return uuid.uuid4().hex


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


def _response_correlation_id(resp: httpx.Response) -> str:
    try:
        value = resp.request.headers.get("X-Correlation-ID")
    except (AttributeError, RuntimeError):
        value = None
    return str(value)[:128] if value else new_correlation_id()


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise OtlError(
            resp.status_code,
            public_otl_error(resp.status_code),
            detail=_safe_body(resp),
            correlation_id=_response_correlation_id(resp),
        )


def _safe_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return (resp.text or "")[:10000]


def _coerce_number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _clip(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:_STR_MAX]


def map_entry_to_otl(entry: dict[str, Any]) -> dict[str, Any]:
    from .timecard_entries import (
        ALLOWED_EXPENDITURE_TYPES,
        _configured_allowlist,
        _validate_timecard_entry,
    )

    valid, validation_error = _validate_timecard_entry(
        entry, assignments=None, require_assignment=False
    )
    if not valid:
        raise OtlError(400, validation_error or "Invalid timecard entry.")
    emp_num = entry.get("employeeNumber")
    if not isinstance(emp_num, (str, int)) or not str(emp_num).strip():
        raise OtlError(400, "employeeNumber is required.")
    emp_num = str(emp_num).strip()
    hours = _coerce_number(entry.get("hours"))
    if hours is None or hours <= 0:
        raise OtlError(
            400, "Timecard entry hours must be a finite number greater than zero."
        )
    timezone = _business_timezone()
    now = datetime.now(timezone)
    date_str = entry.get("date")
    try:
        if date_str:
            parsed_date = date.fromisoformat(str(date_str))
            base_dt = datetime(
                year=parsed_date.year,
                month=parsed_date.month,
                day=parsed_date.day,
                tzinfo=timezone,
            )
        else:
            base_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, TypeError):
        raise OtlError(400, "Invalid date. Expected YYYY-MM-DD.") from None
    try:
        default_start_hour = int(os.getenv("DEFAULT_START_HOUR", "9"))
    except ValueError:
        raise OtlError(400, "Default start time is not configured safely.") from None
    if not 0 <= default_start_hour <= 23:
        raise OtlError(400, "Default start time is not configured safely.")
    start_time_str = entry.get("startTime")
    stop_time_str = entry.get("stopTime")
    try:
        if start_time_str:
            start_hour, start_minute = (
                int(part) for part in str(start_time_str).split(":", 1)
            )
        else:
            start_hour, start_minute = default_start_hour, 0
        start_dt = base_dt.replace(
            hour=start_hour, minute=start_minute, second=0, microsecond=0
        )
        if stop_time_str:
            stop_hour, stop_minute = (
                int(part) for part in str(stop_time_str).split(":", 1)
            )
            stop_dt = base_dt.replace(
                hour=stop_hour, minute=stop_minute, second=0, microsecond=0
            )
            if stop_dt <= start_dt:
                raise OtlError(
                    400, "startTime must be earlier than stopTime on the same day."
                )
            measured_seconds = (stop_dt - start_dt).total_seconds()
            if abs(measured_seconds - hours * 3600) > 0.001:
                raise OtlError(
                    400,
                    "stopTime must exactly match startTime plus the submitted hours.",
                )
        else:
            stop_dt = start_dt + timedelta(hours=hours)
            if stop_dt.date() != base_dt.date():
                raise OtlError(
                    400, "Submitted hours would extend beyond the selected date."
                )
    except OtlError:
        raise
    except (TypeError, ValueError):
        raise OtlError(400, "Invalid startTime or stopTime.") from None
    start_time = start_dt.isoformat(timespec="milliseconds")
    stop_time = stop_dt.isoformat(timespec="milliseconds")
    parts: list[str] = []
    project_name = entry.get("projectName")
    if project_name:
        project_no = entry.get("projectNo")
        parts.append(
            f"Project: {project_name}" + (f" ({project_no})" if project_no else "")
        )
    task_details = entry.get("taskDetails")
    if task_details:
        parts.append(f"Task: {task_details}")
    work_order = entry.get("workOrder")
    if work_order:
        parts.append(f"WO: {work_order}")
    parts.append(f"Total Hours: {hours:g}")
    event: dict[str, Any] = {
        "measure": hours,
        "reporterIdType": "PERSON",
        "reporterId": emp_num,
        "operationType": "ADD",
        "startTime": start_time,
        "stopTime": stop_time,
    }
    comment_str = " | ".join(parts)
    if len(comment_str) > _STR_MAX:
        total_hours_part = parts[-1]
        allowed_len = _STR_MAX - len(total_hours_part) - 3
        if allowed_len > 0:
            rest = " | ".join(parts[:-1])
            comment_str = rest[:allowed_len] + " | " + total_hours_part
        else:
            comment_str = total_hours_part[:_STR_MAX]
    attrs: list[dict[str, str]] = [
        {"attributeName": "Comment", "attributeValue": comment_str}
    ]
    payroll_time_type = entry.get("payrollTimeType")
    if payroll_time_type:
        attrs.append(
            {
                "attributeName": "PayrollTimeType",
                "attributeValue": str(payroll_time_type),
            }
        )
    project_id = entry.get("projectId")
    if project_id:
        attrs.append(
            {
                "attributeName": "PJC_PROJECT_ID",
                "attributeValue": str(project_id),
            }
        )
    task_id = entry.get("taskId")
    if task_id:
        attrs.append(
            {
                "attributeName": "PJC_TASK_ID",
                "attributeValue": str(task_id),
            }
        )
    default_expenditure_type = os.getenv(
        "DEFAULT_EXPENDITURE_TYPE", "Professional Services"
    )
    expenditure_type = entry.get("expenditureType", default_expenditure_type)
    if project_id and expenditure_type:
        allowed_expenditure_types = _configured_allowlist(
            (
                "OTL_ALLOWED_EXPENDITURE_TYPES",
                "ALLOWED_EXPENDITURE_TYPES",
                "EXPENDITURE_TYPE_ALLOWLIST",
            ),
            ALLOWED_EXPENDITURE_TYPES,
        )
        if str(expenditure_type).strip() not in allowed_expenditure_types:
            raise OtlError(400, "expenditureType is not in the configured allowlist.")
        attrs.append(
            {
                "attributeName": "PJC_EXPENDITURE_TYPE_NAME",
                "attributeValue": str(expenditure_type),
            }
        )
    event["timeRecordEventAttribute"] = attrs
    return {
        "processInline": "Y",
        "processMode": "TIME_ENTER",
        "timeRecordEvent": [event],
    }


def _default_record_name(entry: dict[str, Any]) -> str:
    from .idempotency import idempotency_key_for_entry

    emp = str(entry.get("employeeNumber") or "EMP").strip()
    wo = str(entry.get("workOrder") or "WO").strip()
    try:
        request_id = idempotency_key_for_entry(entry)
    except ValueError:
        request_id = None
    suffix = (
        request_id.replace(":", "-")[:48]
        if request_id
        else str(int(time.time() * 1000) % 1_000_000)
    )
    return f"{emp}-{wo}-{suffix}"


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    idempotent: bool = True,
    correlation_id: str | None = None,
    **kwargs,
) -> httpx.Response:
    request_correlation_id = correlation_id or new_correlation_id()
    request_headers = dict(kwargs.pop("headers", {}) or {})
    request_headers.setdefault("X-Correlation-ID", request_correlation_id)
    kwargs["headers"] = request_headers
    last_exc: Exception | None = None
    retries = max_retries if idempotent else 0
    for attempt in range(retries + 1):
        try:
            m = method.upper()
            if m == "GET":
                resp = client.get(url, **kwargs)
            elif m == "DELETE":
                resp = client.delete(url, **kwargs)
            elif m == "POST":
                resp = client.post(url, **kwargs)
            else:
                resp = client.request(method, url, **kwargs)

            if (
                idempotent
                and resp.status_code in RETRYABLE_STATUS_CODES
                and attempt < retries
            ):
                delay = min(base_delay * (2**attempt), max_delay) * (
                    0.8 + random.random() * 0.4
                )
                logger.warning(
                    "Oracle HCM HTTP %d; retrying in %.2fs "
                    "(correlation_id=%s attempt=%d/%d)",
                    resp.status_code,
                    delay,
                    request_correlation_id,
                    attempt + 1,
                    retries,
                )
                time.sleep(delay)
                continue
            return resp
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if idempotent and attempt < retries:
                delay = min(base_delay * (2**attempt), max_delay) * (
                    0.8 + random.random() * 0.4
                )
                logger.warning(
                    "Oracle HCM network error (%s); retrying in %.2fs "
                    "(correlation_id=%s attempt=%d/%d)",
                    type(exc).__name__,
                    delay,
                    request_correlation_id,
                    attempt + 1,
                    retries,
                )
                time.sleep(delay)
            else:
                raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry loop exited unexpectedly")


async def _arequest_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    cred: OtlCredential | None = None,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    idempotent: bool = True,
    correlation_id: str | None = None,
    **kwargs,
) -> httpx.Response:
    auth = cred.auth if cred is not None else httpx.USE_CLIENT_DEFAULT
    request_correlation_id = correlation_id or new_correlation_id()
    request_headers = dict(kwargs.pop("headers", {}) or {})
    request_headers.setdefault("X-Correlation-ID", request_correlation_id)
    kwargs["headers"] = request_headers
    last_exc: Exception | None = None
    retries = max_retries if idempotent else 0
    for attempt in range(retries + 1):
        try:
            m = method.upper()
            if m == "GET":
                resp = await client.get(url, auth=auth, **kwargs)
            elif m == "DELETE":
                resp = await client.delete(url, auth=auth, **kwargs)
            elif m == "POST":
                resp = await client.post(url, auth=auth, **kwargs)
            else:
                resp = await client.request(method, url, auth=auth, **kwargs)

            if (
                idempotent
                and resp.status_code in RETRYABLE_STATUS_CODES
                and attempt < retries
            ):
                delay = min(base_delay * (2**attempt), max_delay) * (
                    0.8 + random.random() * 0.4
                )
                logger.warning(
                    "Oracle HCM HTTP %d; retrying in %.2fs "
                    "(correlation_id=%s attempt=%d/%d)",
                    resp.status_code,
                    delay,
                    request_correlation_id,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
                continue
            return resp
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if idempotent and attempt < retries:
                delay = min(base_delay * (2**attempt), max_delay) * (
                    0.8 + random.random() * 0.4
                )
                logger.warning(
                    "Oracle HCM network error (%s); retrying in %.2fs "
                    "(correlation_id=%s attempt=%d/%d)",
                    type(exc).__name__,
                    delay,
                    request_correlation_id,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
            else:
                raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry loop exited unexpectedly")


def validate(cred: OtlCredential) -> dict[str, Any]:
    with _client(cred) as client:
        resp = _request_with_retry(
            client, "GET", base_url(), params={"limit": 1}, idempotent=True
        )
    if resp.status_code in (401, 403):
        raise OtlError(
            resp.status_code,
            public_otl_error(resp.status_code),
        )
    _raise_for_status(resp)
    return {"ok": True, "username": cred.username}


def escape_q_literal(value: str) -> str:
    return str(value).replace("'", "''")


def _time_status_value(statuses: Any) -> str | None:
    if isinstance(statuses, dict):
        statuses = statuses.get("items", [statuses])
    if isinstance(statuses, str):
        return statuses or None
    if not isinstance(statuses, list):
        return None
    for status in statuses:
        if isinstance(status, str) and status:
            return status
        if not isinstance(status, dict):
            continue
        for key in ("displayValue", "statusName", "statusCode", "name"):
            value = status.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def propagate_timecard_statuses(data: Any) -> Any:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return data
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        item_status = _time_status_value(item.get("timeStatuses"))
        if not item_status and item.get("eventStatus"):
            item_status = str(item["eventStatus"])
        events = item.get("timeRecordEvent", [])
        if isinstance(events, dict):
            events = events.get("items", [])
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_status = _time_status_value(event.get("timeStatuses"))
                if not event_status and event.get("eventStatus"):
                    event_status = str(event["eventStatus"])
                if not event_status and item_status:
                    event_status = item_status
                if event_status and not event.get("eventStatus"):
                    event["eventStatus"] = event_status
                if not item_status and event_status:
                    item_status = event_status
        if item_status and not item.get("eventStatus"):
            item["eventStatus"] = item_status
    return data


def list_timecard_entries(
    cred: OtlCredential,
    limit: int = 25,
    offset: int = 0,
    person_number: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "expand": "timeAttributes,timeStatuses",
        "orderBy": "startTime:desc",
    }
    q_parts = []
    if person_number:
        q_parts.append(f"personNumber='{escape_q_literal(person_number)}'")
    if q_parts:
        params["q"] = " AND ".join(q_parts)
    url = base_url().replace("/timeRecordEventRequests", "/timeRecords")
    with _client(cred) as client:
        resp = _request_with_retry(client, "GET", url, params=params, idempotent=True)
    _raise_for_status(resp)
    return propagate_timecard_statuses(resp.json())


def hcm_base_url() -> str:
    url = base_url()
    if "/timeRecordEventRequests" in url:
        return url.replace("/timeRecordEventRequests", "")
    return url


def get_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    with _client(cred) as client:
        resp = _request_with_retry(
            client,
            "GET",
            f"{hcm_base_url()}/workers",
            params={
                "q": f"PersonNumber='{escape_q_literal(person_number)}'",
                "expand": "names",
                "limit": 1,
            },
            idempotent=True,
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
        "isActive": worker.get("ActiveFlag", True),
    }


def list_worker_assignments(
    cred: OtlCredential, person_number: str, full_name: str = ""
) -> list[dict[str, Any]] | None:
    from . import fusion_catalogue

    return fusion_catalogue.list_assignments_for_worker(person_number)


def get_timecard_entry(cred: OtlCredential, record_id: Any) -> dict[str, Any]:
    with _client(cred) as client:
        resp = _request_with_retry(
            client, "GET", f"{base_url()}/{record_id}", idempotent=True
        )
    _raise_for_status(resp)
    return resp.json()


def _write_headers(entry: dict[str, Any], correlation_id: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id,
    }
    try:
        request_id = idempotency_key_for_entry(entry)
    except IdempotencyKeyError:
        request_id = None
    if request_id:
        headers["Idempotency-Key"] = request_id
    return headers


def _success_result(
    index: int,
    created: Any,
    entry: dict[str, Any],
    correlation_id: str,
    request_id: str | None = None,
    *,
    replayed: bool = False,
) -> dict[str, Any]:
    data = created if isinstance(created, dict) else {}
    record_id = str(data.get("timeRecordEventRequestId") or "UNKNOWN")[:256]
    result: dict[str, Any] = {
        "index": index,
        "ok": True,
        "id": record_id,
        "recordNumber": record_id,
        "recordName": _default_record_name(entry),
        "correlationId": correlation_id,
    }
    if request_id:
        result["requestId"] = request_id
    if replayed:
        result["replayed"] = True
    return result


def _failure_result(
    index: int,
    status_code: int,
    correlation_id: str,
    request_id: str | None = None,
    *,
    replayed: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "index": index,
        "ok": False,
        "status": status_code,
        "error": public_otl_error(status_code),
        "correlationId": correlation_id,
    }
    if request_id:
        result["requestId"] = request_id
    if replayed:
        result["replayed"] = True
    return result


def _preflight_entries(
    entries: list[dict[str, Any]], request_id: str | None
) -> list[str | None]:
    from .timecard_entries import _validate_timecard_entry

    if len(entries) > 100:
        raise OtlError(400, "At most 100 timecard entries may be submitted at once.")
    if request_id is not None and len(entries) != 1:
        raise OtlError(
            400,
            "Each timecard entry must include its own requestId when submitting multiple entries.",
        )
    fallback = request_id if len(entries) == 1 else None
    keys: list[str | None] = []
    for index, entry in enumerate(entries):
        try:
            key = idempotency_key_for_entry(entry, fallback)
        except IdempotencyKeyError as exc:
            raise OtlError(400, f"Entry {index + 1}: {exc}") from None
        valid, error = _validate_timecard_entry(
            entry, assignments=None, require_assignment=False
        )
        if not valid:
            raise OtlError(400, f"Entry {index + 1}: {error}")
        keys.append(key)
    seen_keys: set[str] = set()
    for key in keys:
        if key is None:
            continue
        if key in seen_keys:
            raise OtlError(400, "Each requestId must be unique within a submission.")
        seen_keys.add(key)
    return keys


def create_timecard_entry(
    cred: OtlCredential,
    entry: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    body = map_entry_to_otl(entry)
    request_correlation_id = correlation_id or new_correlation_id()
    with _client(cred) as client:
        resp = client.post(
            base_url(),
            json=body,
            headers=_write_headers(entry, request_correlation_id),
        )
    _raise_for_status(resp)
    return resp.json()


def delete_timecard_entry(cred: OtlCredential, record_id: Any) -> None:
    with _client(cred) as client:
        resp = _request_with_retry(
            client, "DELETE", f"{base_url()}/{record_id}", idempotent=True
        )
    _raise_for_status(resp)


def create_many(
    cred: OtlCredential,
    entries: list[dict[str, Any]],
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    idempotency_store: IdempotencyStore | None = None,
) -> list[dict[str, Any]]:
    keys = _preflight_entries(entries, request_id)
    if request_id is not None and len(entries) == 1 and keys[0] is not None:
        entries = [{**entries[0], "requestId": keys[0]}]
    store = idempotency_store or (
        get_idempotency_store() if any(key is not None for key in keys) else None
    )
    results: list[dict[str, Any]] = []
    for index, (entry, key) in enumerate(zip(entries, keys, strict=True)):
        row_correlation_id = f"{correlation_id or new_correlation_id()}-{index}"
        scoped_key: str | None = None
        claim_token: str | None = None
        if key:
            if store is None:
                results.append(_failure_result(index, 503, row_correlation_id, key))
                continue
            employee_number = str(entry.get("employeeNumber") or "").strip()
            if not employee_number:
                results.append(_failure_result(index, 400, row_correlation_id, key))
                continue
            scoped_key = scoped_idempotency_key(employee_number, key)
            try:
                claim = store.claim(scoped_key, request_fingerprint(entry))
            except IdempotencyUnavailable:
                logger.error(
                    "Idempotency claim failed (correlation_id=%s)", row_correlation_id
                )
                results.append(_failure_result(index, 503, row_correlation_id, key))
                continue
            if claim.state == "replay" and claim.result is not None:
                results.append({**claim.result, "index": index})
                continue
            if claim.state == "conflict" and claim.result is not None:
                results.append(
                    {
                        **claim.result,
                        "index": index,
                        "requestId": key,
                        "correlationId": row_correlation_id,
                    }
                )
                continue
            if claim.state == "pending":
                try:
                    replayed = store.wait_for_result(scoped_key)
                except IdempotencyUnavailable:
                    results.append(_failure_result(index, 503, row_correlation_id, key))
                    continue
                results.append(
                    {
                        **replayed,
                        "index": index,
                        "requestId": key,
                        "correlationId": row_correlation_id,
                    }
                )
                continue
            claim_token = claim.token
        try:
            created = create_timecard_entry(
                cred, entry, correlation_id=row_correlation_id
            )
            result = _success_result(index, created, entry, row_correlation_id, key)
        except OtlError as exc:
            logger.warning(
                "Oracle rejected a timecard entry (correlation_id=%s status=%d)",
                exc.correlation_id,
                exc.status_code,
            )
            result = _failure_result(index, exc.status_code, exc.correlation_id, key)
        except Exception as exc:
            logger.error(
                "Unexpected timecard write failure (%s, correlation_id=%s)",
                type(exc).__name__,
                row_correlation_id,
            )
            result = _failure_result(index, 500, row_correlation_id, key)
        if scoped_key and claim_token:
            assert store is not None
            try:
                stored = store.complete(scoped_key, claim_token, result)
            except IdempotencyUnavailable:
                logger.error(
                    "Idempotency result persistence failed (correlation_id=%s)",
                    row_correlation_id,
                )
                result = _failure_result(index, 503, row_correlation_id, key)
            else:
                if not stored:
                    result = _failure_result(index, 409, row_correlation_id, key)
        results.append(result)
    return results


def _async_client(cred: OtlCredential) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=cred.auth,
        limits=_pool_limits,
        timeout=_timeout(),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )


async def get_shared_async_client() -> httpx.AsyncClient:
    """Return the shared pooled httpx.AsyncClient instance."""
    global _shared_async_client
    if _shared_async_client is None or _shared_async_client.is_closed:
        async with _shared_client_lock:
            if _shared_async_client is None or _shared_async_client.is_closed:
                _shared_async_client = httpx.AsyncClient(
                    limits=_pool_limits,
                    timeout=_timeout(),
                    headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
                )
    return _shared_async_client


async def close_shared_client() -> None:
    """Cleanly close the shared persistent HTTP client on shutdown."""
    global _shared_async_client
    if _shared_async_client is not None and not _shared_async_client.is_closed:
        async with _shared_client_lock:
            if _shared_async_client is not None and not _shared_async_client.is_closed:
                await _shared_async_client.aclose()
                _shared_async_client = None


async def avalidate(cred: OtlCredential) -> dict[str, Any]:
    client = await get_shared_async_client()
    resp = await _arequest_with_retry(
        client, "GET", base_url(), cred=cred, params={"limit": 1}, idempotent=True
    )
    if resp.status_code in (401, 403):
        raise OtlError(
            resp.status_code,
            public_otl_error(resp.status_code),
        )
    _raise_for_status(resp)
    return {"ok": True, "username": cred.username}


async def aget_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    client = await get_shared_async_client()
    url = f"{hcm_base_url()}/workers"
    params = {
        "q": f"PersonNumber='{escape_q_literal(person_number)}'",
        "expand": "names",
        "limit": 1,
    }
    resp = await _arequest_with_retry(
        client, "GET", url, cred=cred, params=params, idempotent=True
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
        "isActive": worker.get("ActiveFlag", True),
    }


async def alist_timecard_entries(
    cred: OtlCredential,
    limit: int = 10,
    offset: int = 0,
    person_number: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "expand": "timeAttributes,timeStatuses",
        "orderBy": "startTime:desc",
    }
    q_parts = []
    if person_number:
        q_parts.append(f"personNumber='{escape_q_literal(person_number)}'")
    if q_parts:
        params["q"] = " AND ".join(q_parts)
    url = base_url().replace("/timeRecordEventRequests", "/timeRecords")
    client = await get_shared_async_client()
    resp = await _arequest_with_retry(
        client, "GET", url, cred=cred, params=params, idempotent=True
    )
    _raise_for_status(resp)
    return propagate_timecard_statuses(resp.json())


async def acreate_many(
    cred: OtlCredential,
    entries: list[dict[str, Any]],
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    idempotency_store: IdempotencyStore | None = None,
) -> list[dict[str, Any]]:
    keys = _preflight_entries(entries, request_id)
    if request_id is not None and len(entries) == 1 and keys[0] is not None:
        entries = [{**entries[0], "requestId": keys[0]}]
    store = idempotency_store or (
        get_idempotency_store() if any(key is not None for key in keys) else None
    )
    client = await get_shared_async_client()

    async def _submit_single(
        index: int, entry: dict[str, Any], key: str | None
    ) -> dict[str, Any]:
        row_correlation_id = f"{correlation_id or new_correlation_id()}-{index}"
        scoped_key: str | None = None
        claim_token: str | None = None
        if key and store is not None:
            employee_number = str(entry.get("employeeNumber") or "").strip()
            if not employee_number:
                return _failure_result(index, 400, row_correlation_id, key)
            scoped_key = scoped_idempotency_key(employee_number, key)
            try:
                claim = await asyncio.to_thread(
                    store.claim, scoped_key, request_fingerprint(entry)
                )
            except IdempotencyUnavailable:
                logger.error(
                    "Idempotency claim failed (correlation_id=%s)", row_correlation_id
                )
                return _failure_result(index, 503, row_correlation_id, key)
            if claim.state == "replay" and claim.result is not None:
                return {**claim.result, "index": index}
            if claim.state == "conflict" and claim.result is not None:
                return {
                    **claim.result,
                    "index": index,
                    "requestId": key,
                    "correlationId": row_correlation_id,
                }
            if claim.state == "pending":
                try:
                    replayed = await asyncio.to_thread(
                        store.wait_for_result, scoped_key
                    )
                except IdempotencyUnavailable:
                    return _failure_result(index, 503, row_correlation_id, key)
                return {
                    **replayed,
                    "index": index,
                    "requestId": key,
                    "correlationId": row_correlation_id,
                }
            claim_token = claim.token
        try:
            created = await acreate_timecard_entry(
                cred, entry, client=client, correlation_id=row_correlation_id
            )
            result = _success_result(index, created, entry, row_correlation_id, key)
        except OtlError as exc:
            logger.warning(
                "Oracle rejected a timecard entry (correlation_id=%s status=%d)",
                exc.correlation_id,
                exc.status_code,
            )
            result = _failure_result(index, exc.status_code, exc.correlation_id, key)
        except Exception as exc:
            logger.error(
                "Unexpected timecard write failure (%s, correlation_id=%s)",
                type(exc).__name__,
                row_correlation_id,
            )
            result = _failure_result(index, 500, row_correlation_id, key)
        if scoped_key and claim_token and store is not None:
            try:
                stored = await asyncio.to_thread(
                    store.complete, scoped_key, claim_token, result
                )
            except IdempotencyUnavailable:
                logger.error(
                    "Idempotency result persistence failed (correlation_id=%s)",
                    row_correlation_id,
                )
                return _failure_result(index, 503, row_correlation_id, key)
            if not stored:
                return _failure_result(index, 409, row_correlation_id, key)
        return result

    tasks = [
        _submit_single(index, entry, key)
        for index, (entry, key) in enumerate(zip(entries, keys, strict=True))
    ]
    return list(await asyncio.gather(*tasks))


async def alist_worker_assignments(
    cred: OtlCredential, person_number: str, full_name: str = ""
) -> list[dict[str, Any]] | None:
    return await asyncio.to_thread(list_worker_assignments, cred, person_number)


async def acreate_timecard_entry(
    cred: OtlCredential,
    entry: dict[str, Any],
    client: httpx.AsyncClient | None = None,
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    if client is None:
        client = await get_shared_async_client()
    body = map_entry_to_otl(entry)
    request_correlation_id = correlation_id or new_correlation_id()
    resp = await client.post(
        base_url(),
        json=body,
        auth=cred.auth,
        headers=_write_headers(entry, request_correlation_id),
    )
    _raise_for_status(resp)
    return resp.json()
