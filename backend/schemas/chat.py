from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(default="", max_length=10000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list, max_length=50)


class TtsBody(BaseModel):
    text: str
    rate: float = 1.0
