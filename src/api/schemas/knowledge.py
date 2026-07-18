"""Schemas for administrator knowledge extension APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IntakeJobResponse(BaseModel):
    job_id: str
    original_filename: str
    uploaded_by: str
    document_kind: str
    status: str
    message: str
    created_at: str
    updated_at: str
    source_path: str | None = None
    staging_chunks_path: str | None = None
    details: dict = Field(default_factory=dict)


class IntakeJobListResponse(BaseModel):
    total: int
    items: list[IntakeJobResponse]


class IntakeAuditEventResponse(BaseModel):
    event_id: str
    job_id: str
    timestamp: str
    actor: str
    from_status: str | None = None
    to_status: str
    event_type: str
    message: str
    block_reason: str | None = None
    next_action: str | None = None
    details: dict = Field(default_factory=dict)


class IntakeAuditListResponse(BaseModel):
    total: int
    items: list[IntakeAuditEventResponse]


class CandidateDecisionRequest(BaseModel):
    decision: Literal["approve", "hold", "reject"]
    reason: str = Field(..., min_length=1, max_length=1000)
    hold_reason_codes: list[str] = Field(default_factory=list)
    approved_paths: list[str] = Field(default_factory=list)


class CandidateListResponse(BaseModel):
    total: int
    items: list[dict]
