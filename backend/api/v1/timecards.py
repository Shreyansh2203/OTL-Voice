from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from ...core import auth
from ...core.auth import SessionContext
from ...schemas.timecards import TimecardBody
from ...services import fusion_catalogue, otl_client, timecard_entries
from ...services.idempotency import (
    IdempotencyKeyError,
    idempotency_key_for_entry,
    sanitize_idempotency_result,
)
from ...services.otl_client import propagate_timecard_statuses

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timecards", "labour"])

_FENCED_JSON = timecard_entries._FENCED_JSON
_STRICT_ASSIGNMENT_CACHE = timecard_entries._STRICT_ASSIGNMENT_CACHE
MAX_TIMECARD_ENTRIES = timecard_entries.MAX_TIMECARD_ENTRIES
_extract_entries = timecard_entries._extract_entries
_normalize_entry = timecard_entries._normalize_entry
_options_hint = timecard_entries._options_hint
_resolve_entry = timecard_entries._resolve_entry
_strict_assignment = timecard_entries._strict_assignment
_validate_timecard_entry = timecard_entries._validate_timecard_entry
_validate_timecard_entries = timecard_entries._validate_timecard_entries


@router.post("/api/otl/timecard")
async def submit_timecard(
    body: TimecardBody,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    correlation_id = uuid.uuid4().hex
    response.headers["X-Correlation-ID"] = correlation_id
    try:
        entries = body.entries or _extract_entries(body.assistantMessage or "")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assistant message did not contain valid timecard JSON.",
        ) from None
    if len(entries) > MAX_TIMECARD_ENTRIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {MAX_TIMECARD_ENTRIES} timecard entries may be submitted.",
        )
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No timecard entries found to submit.",
        )
    body_request_id = body.requestId or body.idempotencyKey
    try:
        if idempotency_key is not None and body_request_id is not None:
            idempotency_key_for_entry({}, idempotency_key)
            idempotency_key_for_entry({}, body_request_id)
            if idempotency_key != body_request_id:
                raise IdempotencyKeyError("Conflicting requestId values were supplied.")
        request_id = body_request_id or idempotency_key
        if request_id is not None:
            idempotency_key_for_entry({}, request_id)
        if request_id is not None and len(entries) != 1:
            raise IdempotencyKeyError(
                "Each timecard entry must include its own requestId when submitting multiple entries."
            )
        seen_request_ids: set[str] = set()
        for entry in entries:
            entry_request_id = idempotency_key_for_entry(entry)
            if request_id is not None and entry_request_id not in (None, request_id):
                raise IdempotencyKeyError("Conflicting requestId values were supplied.")
            if entry_request_id is not None:
                if entry_request_id in seen_request_ids:
                    raise IdempotencyKeyError(
                        "Each requestId must be unique within a submission."
                    )
                seen_request_ids.add(entry_request_id)
    except IdempotencyKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    valid, validation_error = _validate_timecard_entries(entries, None)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation_error or "Invalid timecard entry.",
        )
    assignments_for_validation: list[dict[str, Any]] | None = []
    if _strict_assignment():
        try:
            assignments_for_validation = (
                await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id)
            )
        except Exception:
            logger.error("Assignment lookup failed (correlation_id=%s)", correlation_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Project assignments are temporarily unavailable. "
                    f"Reference: {correlation_id}."
                ),
            ) from None
        if assignments_for_validation is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Project assignments catalogue is not loaded yet. "
                    f"Reference: {correlation_id}."
                ),
            )
    valid, validation_error = _validate_timecard_entries(
        entries, assignments_for_validation
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation_error or "Invalid timecard entry.",
        )
    assignments = assignments_for_validation
    resolved = [_resolve_entry(entry, ctx, assignments) for entry in entries]
    submit_kwargs: dict[str, Any] = {"correlation_id": correlation_id}
    if request_id is not None:
        submit_kwargs["request_id"] = request_id
    try:
        results = await otl_client.acreate_many(
            otl_client.service_credential(), resolved, **submit_kwargs
        )
    except Exception:
        logger.error("Timecard submission failed (correlation_id=%s)", correlation_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Timecard submission could not be completed. "
                f"Reference: {correlation_id}."
            ),
        ) from None
    safe_results = []
    for index, result in enumerate(results):
        safe_result = sanitize_idempotency_result(result)
        safe_result.setdefault("index", index)
        safe_results.append(safe_result)
    succeeded = sum(1 for result in safe_results if result.get("ok"))
    return {
        "submitted": len(safe_results),
        "succeeded": succeeded,
        "failed": len(safe_results) - succeeded,
        "results": safe_results,
        "correlationId": correlation_id,
    }


@router.get("/api/otl/timecards")
async def list_timecards(
    response: Response,
    limit: int = Query(
        default=25, ge=1, le=100, description="Maximum records to fetch (1-100)"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset (>=0)"),
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    correlation_id = uuid.uuid4().hex
    response.headers["X-Correlation-ID"] = correlation_id
    try:
        timecards = await otl_client.alist_timecard_entries(
            otl_client.service_credential(),
            limit=limit,
            offset=offset,
            person_number=ctx.employee_id,
        )
    except Exception:
        logger.info(
            "Could not fetch live timecards from Oracle (correlation_id=%s)",
            correlation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not fetch timecards from Oracle Cloud. "
                f"Reference: {correlation_id}."
            ),
        ) from None
    timecards = propagate_timecard_statuses(timecards)
    for item in timecards.get("items", []):
        attrs = item.get("timeAttributes", [])
        if "timeRecordEvent" in item:
            for event in item.get("timeRecordEvent", []):
                evt_attrs = event.get("timeRecordEventAttribute", [])
                has_comment = any(
                    a.get("attributeName") == "Comment" for a in evt_attrs
                )
                if not has_comment:
                    proj_attr = next(
                        (
                            a
                            for a in evt_attrs
                            if a.get("attributeName") == "PJC_PROJECT_ID"
                        ),
                        None,
                    )
                    if proj_attr and proj_attr.get("attributeValue"):
                        proj = fusion_catalogue.get_project_by_id(
                            proj_attr.get("attributeValue")
                        )
                        if proj:
                            evt_attrs.append(
                                {
                                    "attributeName": "Comment",
                                    "attributeValue": f"Project: {proj.get('project_name')}",
                                }
                            )
        else:
            item["timeRecordEventAttribute"] = attrs
            has_comment = any(a.get("attributeName") == "Comment" for a in attrs)
            if not has_comment:
                proj_attr = next(
                    (a for a in attrs if a.get("attributeName") == "PJC_PROJECT_ID"),
                    None,
                )
                if proj_attr and proj_attr.get("attributeValue"):
                    proj = fusion_catalogue.get_project_by_id(
                        proj_attr.get("attributeValue")
                    )
                    if proj:
                        attrs.append(
                            {
                                "attributeName": "Comment",
                                "attributeValue": f"Project: {proj.get('project_name')}",
                            }
                        )
            if item.get("comment") and not has_comment:
                attrs.append(
                    {
                        "attributeName": "Comment",
                        "attributeValue": item.get("comment"),
                    }
                )
    return timecards


@router.get("/api/labour/assignments")
async def labour_assignments(
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    correlation_id = uuid.uuid4().hex
    response.headers["X-Correlation-ID"] = correlation_id
    try:
        work_orders = await fusion_catalogue.alist_assignments_for_worker(
            ctx.employee_id
        )
    except Exception:
        logger.error(
            "Assignment lookup failed (correlation_id=%s)",
            correlation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Project assignments are temporarily unavailable. "
                f"Reference: {correlation_id}."
            ),
        ) from None
    if work_orders is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Project assignments are still loading. Reference: {correlation_id}."
            ),
        )
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": work_orders,
    }
