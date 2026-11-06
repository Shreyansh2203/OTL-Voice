from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TimecardEntryInput(BaseModel):
    employeeNumber: str | None = None
    employeeName: str | None = None
    projectNo: str | int | None = None
    projectName: str | None = None
    workOrder: str | None = None
    taskDetails: str | None = None
    taskId: str | int | None = None
    projectId: str | None = None
    hours: float | None = None
    date: str | None = None
    startTime: str | None = None
    stopTime: str | None = None
    payrollTimeType: str | None = None
    expenditureType: str | None = None
    comment: str | None = None
    requestId: str | None = Field(
        default=None,
        description="Stable client-generated key used to replay this entry safely",
    )
    idempotencyKey: str | None = Field(
        default=None,
        description="Alias for requestId",
    )


class TimecardBody(BaseModel):
    entries: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=100,
        description="Structured timecard entries to submit to Oracle Fusion OTL",
    )
    assistantMessage: str | None = Field(
        default=None,
        description="Optional raw assistant message containing JSON fenced entries",
    )
    requestId: str | None = Field(
        default=None,
        description="Stable request key for a single-entry submission",
    )
    idempotencyKey: str | None = Field(
        default=None,
        description="Alias for requestId",
    )
