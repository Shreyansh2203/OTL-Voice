from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...core import auth
from ...core.auth import SessionContext
from ...schemas.timecards import TimecardBody
from ...services import fusion_catalogue, otl_client, timecard_entries
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


@router.post("/api/otl/timecard")
async def submit_timecard(
    body: TimecardBody, ctx: SessionContext = Depends(auth.current_session)
) -> dict[str, Any]:
    try:
        entries = body.entries or _extract_entries(body.assistantMessage or "")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
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
    assignments_for_validation: list[dict[str, Any]] | None = []
    if _strict_assignment():
        assignments_for_validation = (
            await fusion_catalogue.alist_assignments_for_worker(
                ctx.employee_id, ctx.full_name
            )
        )
        if assignments_for_validation is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Project assignments catalogue is not loaded yet.",
            )
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
        results = await otl_client.acreate_many(
            otl_client.service_credential(), resolved
        )
    except Exception as exc:
        logger.error("Live OTL submit failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to submit timecards to Oracle Cloud: {exc}",
        )
    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "submitted": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.get("/api/otl/timecards")
async def list_timecards(
    limit: int = Query(
        default=25, ge=1, le=100, description="Maximum records to fetch (1-100)"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset (>=0)"),
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    try:
        timecards = await otl_client.alist_timecard_entries(
            otl_client.service_credential(),
            limit=limit,
            offset=offset,
            person_number=ctx.employee_id,
        )
    except Exception as exc:
        logger.info("Could not fetch live timecards from Oracle", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch timecards from Oracle Cloud.",
        ) from exc
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
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, Any]:
    try:
        work_orders = await fusion_catalogue.alist_assignments_for_worker(
            ctx.employee_id, ctx.full_name
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project assignments are temporarily unavailable.",
        ) from exc
    if work_orders is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project assignments are still loading.",
        )
    return {
        "employeeId": ctx.employee_id,
        "fullName": ctx.full_name,
        "workOrders": work_orders,
    }
