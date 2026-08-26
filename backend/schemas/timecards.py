from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TimecardBody(BaseModel):
    entries: list[dict[str, Any]] | None = None
    assistantMessage: str | None = None
