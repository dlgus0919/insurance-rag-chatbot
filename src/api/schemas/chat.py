"""Chat request schemas reserved for the Week 2 SSE implementation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IndexMode = Literal["default", "v2_only", "v1_v2_combined"]


class ChatRequest(BaseModel):
    mode: Literal["general", "quickcode", "formal"] = "general"
    query: str = Field(..., min_length=1)
    session_id: str | None = None
    model: str | None = None
    provider: Literal["openai", "local"] | None = None
    reasoning_mode: Literal["off", "on"] = "off"
    top_k: int = Field(default=10, ge=1, le=20)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    filters: dict = Field(default_factory=dict)
    memo: str | None = None
    index_mode: IndexMode = "default"
    clarification: dict = Field(default_factory=dict)
