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
        details: dict[str, Any] | None = None,
        source_path: str | None = None,
        staging_chunks_path: str | None = None,
    ) -> IntakeJob:
        job = self.load_job(job_id)
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
        return job

    def job_dir(self, job_id: str) -> Path:
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ValueError("invalid intake job id")
        return self.root / job_id

    def _job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def _write(self, job: IntakeJob) -> None:
        path = self._job_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
