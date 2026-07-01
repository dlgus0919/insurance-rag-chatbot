"""Runtime job store for administrator document intake."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class IntakeJobStatus(StrEnum):
    UPLOADED = "uploaded"
    DETECTING_DOCUMENT_TYPE = "detecting_document_type"
    BLOCKED_SCANNED_PDF = "blocked_scanned_pdf"
    BLOCKED_UNSUPPORTED = "blocked_unsupported"
    STAGING_SOURCE = "staging_source"
    BUILDING_STAGING_CHUNKS = "building_staging_chunks"
    EXTRACTING_CANDIDATES = "extracting_candidates"
    WAITING_REVIEW = "waiting_review"
    APPLYING_APPROVED = "applying_approved"
    REBUILDING_ACTIVE = "rebuilding_active"
    COMPLETED = "completed"
    FAILED = "failed"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _event_type(status: IntakeJobStatus) -> str:
    if status in {IntakeJobStatus.BLOCKED_SCANNED_PDF, IntakeJobStatus.BLOCKED_UNSUPPORTED}:
        return "blocked"
    if status == IntakeJobStatus.FAILED:
        return "failed"
    if status in {
        IntakeJobStatus.APPLYING_APPROVED,
        IntakeJobStatus.REBUILDING_ACTIVE,
        IntakeJobStatus.COMPLETED,
    }:
        return "applied"
    return "status_changed"


@dataclass
class IntakeJob:
    job_id: str
    original_filename: str
    uploaded_by: str
    document_kind: str
    status: IntakeJobStatus
    message: str
    created_at: str
    updated_at: str
    source_path: str | None = None
    staging_chunks_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeJob":
        payload = dict(data)
        payload["status"] = IntakeJobStatus(payload["status"])
        return cls(**payload)


class IntakeJobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def create_job(self, *, original_filename: str, uploaded_by: str, document_kind: str) -> IntakeJob:
        self.root.mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        safe_ts = now.replace(":", "").replace("+", "Z")
        job = IntakeJob(
            job_id=f"intake_{safe_ts}_{uuid.uuid4().hex[:8]}",
            original_filename=Path(original_filename).name,
            uploaded_by=uploaded_by,
            document_kind=document_kind,
            status=IntakeJobStatus.UPLOADED,
            message="문서가 업로드되었습니다.",
            created_at=now,
            updated_at=now,
        )
        self._write(job)
        self.append_audit_event(
            job.job_id,
            actor=uploaded_by,
            from_status=None,
            to_status=job.status,
            message=job.message,
        )
        return job

    def load_job(self, job_id: str) -> IntakeJob:
        path = self._job_path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"intake job not found: {job_id}")
        return IntakeJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_jobs(self) -> list[IntakeJob]:
        if not self.root.exists():
            return []
        jobs = []
        for path in self.root.glob("intake_*/job.json"):
            jobs.append(IntakeJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return sorted(jobs, key=lambda item: (item.created_at, item.job_id), reverse=True)

    def update_job(
        self,
        job_id: str,
        *,
        status: IntakeJobStatus,
        message: str,
        actor: str = "system",
        block_reason: str | None = None,
        next_action: str | None = None,
        details: dict[str, Any] | None = None,
        source_path: str | None = None,
        staging_chunks_path: str | None = None,
    ) -> IntakeJob:
        job = self.load_job(job_id)
        previous_status = job.status
        job.status = status
        job.message = message
        job.updated_at = utc_now_iso()
        if details:
            job.details.update(details)
        if source_path is not None:
            job.source_path = source_path
        if staging_chunks_path is not None:
            job.staging_chunks_path = staging_chunks_path
        self._write(job)
        self.append_audit_event(
            job.job_id,
            actor=actor,
            from_status=previous_status,
            to_status=status,
            message=message,
            block_reason=block_reason,
            next_action=next_action,
            details=details,
        )
        return job

    def job_dir(self, job_id: str) -> Path:
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ValueError("invalid intake job id")
        return self.root / job_id

    def append_audit_event(
        self,
        job_id: str,
        *,
        actor: str,
        from_status: IntakeJobStatus | None,
        to_status: IntakeJobStatus,
        message: str,
        block_reason: str | None = None,
        next_action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": uuid.uuid4().hex,
            "job_id": job_id,
            "timestamp": utc_now_iso(),
            "actor": actor,
            "from_status": from_status.value if from_status is not None else None,
            "to_status": to_status.value,
            "event_type": _event_type(to_status),
            "message": message,
            "block_reason": block_reason,
            "next_action": next_action,
            "details": details or {},
        }
        path = self._audit_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def load_audit_events(self, job_id: str) -> list[dict[str, Any]]:
        path = self._audit_path(job_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _audit_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "audit_log.jsonl"

    def _job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def _write(self, job: IntakeJob) -> None:
        path = self._job_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
