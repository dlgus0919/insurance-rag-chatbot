"""System and model response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ModelInfo(BaseModel):
    provider: str
    id: str
    label: str


class ModelListResponse(BaseModel):
    providers: dict[str, list[ModelInfo]]
    defaults: dict[str, str | None]


class SystemStatusResponse(BaseModel):
    status: str
    paths: dict[str, bool]
