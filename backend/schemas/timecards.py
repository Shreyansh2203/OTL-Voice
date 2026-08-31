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
    comment: str | None = None


class TimecardBody(BaseModel):
    entries: list[dict[str, Any]] | None = Field(
        default=None,
        description="Structured timecard entries to submit to Oracle Fusion OTL",
    )
    assistantMessage: str | None = Field(
        default=None,
        description="Optional raw assistant message containing JSON fenced entries",
    )
