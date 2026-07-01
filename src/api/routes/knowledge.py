"""Administrator document intake and knowledge-review routes."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status

from scripts.claim_rule_candidate_review import append_log, decide_candidate
from src import config
from src.api.deps import require_permission
from src.api.exceptions import ValidationException
from src.api.schemas.knowledge import (
    CandidateDecisionRequest,
    CandidateListResponse,
    IntakeJobListResponse,
    IntakeJobResponse,
)
from src.auth.users import User
from src.claim_calculation.rule_candidates import load_jsonl, write_jsonl
from src.ingest.document_intake import DocumentKind, classify_source_file
from src.ingest.intake_runner import run_intake_job_once
from src.ingest.knowledge_apply import apply_approved_knowledge
from src.ingest.intake_store import IntakeJobStore
from src.ontology.review_store import OntologyReviewStore

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])

DEFAULT_INTAKE_ROOT = config.ROOT_DIR / "data" / "intake" / "jobs"
RULE_CANDIDATES_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "candidates.jsonl"
RULE_REVIEW_LOG_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "review_log.jsonl"
ONTOLOGY_CANDIDATES_PATH = config.ROOT_DIR / "data" / "ontology" / "review" / "candidates.jsonl"


def get_intake_store() -> IntakeJobStore:
    return IntakeJobStore(DEFAULT_INTAKE_ROOT)


def _job_response(job) -> dict:
    return job.as_dict()


@router.get("/intake/jobs", response_model=IntakeJobListResponse)
async def list_intake_jobs(
    _: User = Depends(require_permission("admin.knowledge.read")),
) -> dict:
    jobs = get_intake_store().list_jobs()
    return {"total": len(jobs), "items": [_job_response(job) for job in jobs]}


@router.post("/intake/jobs", response_model=IntakeJobResponse, status_code=status.HTTP_201_CREATED)
async def create_intake_job(
    file: UploadFile = File(...),
    current: User = Depends(require_permission("admin.knowledge.manage")),
) -> dict:
    original_name = Path(file.filename or "").name
    if not original_name:
        raise ValidationException(detail="파일명이 비어 있습니다.")
    document_kind = classify_source_file(original_name)
    if document_kind == DocumentKind.UNSUPPORTED:
        raise ValidationException(detail="지원하지 않는 파일 형식입니다.")

    store = get_intake_store()
    job = store.create_job(
        original_filename=original_name,
        uploaded_by=current.username,
        document_kind=document_kind.value,
    )
    source_dir = store.job_dir(job.job_id) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / original_name
    with source_path.open("wb") as fp:
        shutil.copyfileobj(file.file, fp)
    job = store.update_job(job.job_id, status=job.status, message=job.message, source_path=str(source_path))
    return _job_response(job)


@router.post("/intake/jobs/{job_id}/run", response_model=IntakeJobResponse)
async def run_intake_job(
    job_id: str,
    _: User = Depends(require_permission("admin.knowledge.manage")),
) -> dict:
    job = run_intake_job_once(get_intake_store(), job_id)
    return _job_response(job)


@router.get("/ontology-candidates", response_model=CandidateListResponse)
async def list_ontology_candidates(
    _: User = Depends(require_permission("admin.knowledge.read")),
) -> dict:
    store = OntologyReviewStore(candidates_path=ONTOLOGY_CANDIDATES_PATH)
    records = [candidate.to_dict() for candidate in store.load_candidates()]
    return {"total": len(records), "items": records}


@router.post("/ontology-candidates/{candidate_id}/decision")
async def decide_ontology_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    current: User = Depends(require_permission("admin.knowledge.manage")),
) -> dict:
    store = OntologyReviewStore(candidates_path=ONTOLOGY_CANDIDATES_PATH)
    candidate = store.decide(
        candidate_id,
        payload.decision,
        reviewer=current.username,
        reviewer_type="practitioner",
        reason=payload.reason,
        hold_reason_codes=payload.hold_reason_codes,
    )
    return candidate.to_dict()


@router.get("/rule-candidates", response_model=CandidateListResponse)
async def list_rule_candidates(
    _: User = Depends(require_permission("admin.knowledge.read")),
) -> dict:
    records = load_jsonl(RULE_CANDIDATES_PATH)
    return {"total": len(records), "items": records}


@router.post("/rule-candidates/{candidate_id}/decision")
async def decide_rule_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    current: User = Depends(require_permission("admin.knowledge.manage")),
) -> dict:
    if payload.decision == "hold":
        raise ValidationException(detail="액티브 룰 후보는 현재 승인 또는 거절만 지원합니다. 보류가 필요하면 거절 후 후보를 재생성하세요.")
    records = load_jsonl(RULE_CANDIDATES_PATH)
    event = decide_candidate(records, candidate_id, payload.decision, current.username, payload.reason)
    write_jsonl(RULE_CANDIDATES_PATH, records)
    append_log(RULE_REVIEW_LOG_PATH, event)
    return next(record for record in records if record.get("candidate_id") == candidate_id)


@router.post("/apply-approved")
async def apply_approved(
    _: User = Depends(require_permission("admin.knowledge.manage")),
) -> dict:
    return apply_approved_knowledge().as_dict()
