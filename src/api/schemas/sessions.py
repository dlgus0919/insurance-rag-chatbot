"""Session and message schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    title: str = Field(default="새로운 보상 질의", max_length=255)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    message_count: int = 0


class MessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    sources: list[dict] | None = None
    created_at: datetime
