"""Run administrator document intake jobs without mutating active indexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.extract_claim_rule_candidates import extract_candidates_from_text, iter_policy_chunks
from src import config
from src.claim_calculation.rule_candidates import load_jsonl, write_jsonl
from src.ingest.document_intake import IntakeBlockReason, evaluate_pdf_text_layer
from src.ingest.intake_store import IntakeJob, IntakeJobStatus, IntakeJobStore
from src.ontology.candidate_extractor import (
    extract_reinforcement_candidates,
    load_manifest_concepts,
    load_processed_chunks,
)
from src.ontology.policy import load_candidate_extraction_policy, load_review_policy
from src.ontology.registry import ACTIVE_ONTOLOGY_MANIFEST, BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import OntologyCandidate, OntologyReviewStore, utc_now_iso
from src.parser.pdf_parser import parse_pdf

GLOBAL_ONTOLOGY_CANDIDATES_PATH = config.ROOT_DIR / "data" / "ontology" / "review" / "candidates.jsonl"
GLOBAL_RULE_CANDIDATES_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "candidates.jsonl"


def run_intake_job_once(store: IntakeJobStore, job_id: str) -> IntakeJob:
    job = store.load_job(job_id)
    if job.document_kind == "ocr_unsupported":
        return store.update_job(
            job_id,
            status=IntakeJobStatus.BLOCKED_UNSUPPORTED,
            message="이미지 또는 스캔 문서는 OCR 자동화 대상이 아니므로 후보 추출을 진행하지 않습니다.",
            block_reason=IntakeBlockReason.OCR_FILE_UNSUPPORTED.value,
            next_action="텍스트 레이어가 포함된 디지털 PDF 또는 구조화 가능한 Excel 파일을 업로드하세요.",
        )
    if job.document_kind == "pdf":
        return _run_pdf_job(store, job)
    if job.document_kind == "excel":
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="Excel 문서 intake는 아직 구조화 staging 연결 전입니다. PDF 디지털 문서부터 처리해 주세요.",
            block_reason=IntakeBlockReason.EXCEL_STAGING_NOT_READY.value,
            next_action="현재 단계에서는 텍스트 레이어가 포함된 디지털 PDF를 업로드하거나 Excel staging 연결 작업을 먼저 완료하세요.",
        )
    return store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_UNSUPPORTED,
        message="지원하지 않는 문서 형식입니다.",
        block_reason=IntakeBlockReason.UNSUPPORTED_FILE_TYPE.value,
        next_action="디지털 PDF 또는 구조화 가능한 Excel 파일을 업로드하세요.",
    )


def _run_pdf_job(store: IntakeJobStore, job: IntakeJob) -> IntakeJob:
    if not job.source_path:
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="업로드 원본 파일 경로가 기록되어 있지 않습니다.",
            block_reason=IntakeBlockReason.SOURCE_FILE_MISSING.value,
            next_action="문서를 다시 업로드한 뒤 intake job을 새로 실행하세요.",
        )
    source_path = Path(job.source_path)
    if not source_path.exists():
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="업로드 원본 파일을 찾을 수 없습니다.",
            block_reason=IntakeBlockReason.SOURCE_FILE_MISSING.value,
            next_action="문서를 다시 업로드한 뒤 intake job을 새로 실행하세요.",
            details={"source_path": str(source_path)},
        )

    store.update_job(job.job_id, status=IntakeJobStatus.DETECTING_DOCUMENT_TYPE, message="PDF 텍스트 레이어를 검사합니다.")
    report = evaluate_pdf_text_layer(source_path)
    if not report.has_text_layer:
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
            message=report.user_message,
            block_reason=report.block_reason.value if report.block_reason else None,
            next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
            details={"pdf_text_layer": report.as_dict()},
        )

    store.update_job(job.job_id, status=IntakeJobStatus.BUILDING_STAGING_CHUNKS, message="디지털 PDF staging chunk를 생성합니다.")
    chunks_path = _write_pdf_staging_chunks(store.job_dir(job.job_id), source_path, job.job_id)
    store.update_job(job.job_id, status=IntakeJobStatus.EXTRACTING_CANDIDATES, message="검토 후보를 생성합니다.")
    try:
        candidate_details = _write_candidate_outputs(store.job_dir(job.job_id), chunks_path, job.job_id)
        candidate_details.update(_publish_candidate_outputs(job, chunks_path, candidate_details))
    except Exception as exc:
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="검토 후보 생성 중 오류가 발생했습니다.",
            block_reason=IntakeBlockReason.CANDIDATE_EXTRACTION_FAILED.value,
            next_action="문서 staging 결과와 후보 추출 로그를 확인한 뒤 다시 실행하세요.",
            details={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
    return store.update_job(
        job.job_id,
        status=IntakeJobStatus.WAITING_REVIEW,
        message="문서 staging과 후보 생성이 완료되었습니다. 후보 검토를 진행할 수 있습니다.",
        staging_chunks_path=str(chunks_path),
        details={"pdf_text_layer": report.as_dict(), **candidate_details},
    )


def _write_pdf_staging_chunks(job_dir: Path, source_path: Path, job_id: str) -> Path:
    staging_dir = job_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = staging_dir / "chunks.jsonl"
    doc_short = f"{job_id}_{source_path.stem}"
    rows = []
    for page_no, text in parse_pdf(source_path):
        cleaned = str(text or "").strip()
        if not cleaned:
            continue
        chunk_id = f"{doc_short}_p{page_no:03d}"
        rows.append(
            {
                "id": chunk_id,
                "chunk_id": chunk_id,
                "text": cleaned,
                "metadata": {
                    "doc_short": doc_short,
                    "doc_name": source_path.stem,
                    "source": doc_short,
                    "pdf_filename": source_path.name,
                    "page_start": page_no,
                    "page_end": page_no,
                    "intake_job_id": job_id,
                },
            }
        )
    chunks_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return chunks_path


def _write_candidate_outputs(job_dir: Path, chunks_path: Path, job_id: str) -> dict[str, Any]:
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    ontology_path = review_dir / "ontology_candidates.jsonl"
    rule_path = review_dir / "rule_candidates.jsonl"

    concept_policy = load_candidate_extraction_policy(None)
    review_policy = load_review_policy(None)
    concepts = load_manifest_concepts(str(_candidate_extraction_manifest()))
    chunks = load_processed_chunks([chunks_path], limit=2000)
    ontology_result = extract_reinforcement_candidates(
        concepts=concepts,
        chunks=chunks,
        extraction_run_id=f"intake-ontology-{job_id}-{utc_now_iso()}",
        candidate_limit=100,
        candidate_type=concept_policy.default_reinforcement_type,
        extraction_policy=concept_policy,
        review_policy=review_policy,
        previous_review_candidates=[],
    )
    ontology_path.write_text(
        "".join(json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for candidate in ontology_result.candidates),
        encoding="utf-8",
    )

    rule_candidates = []
    for chunk in iter_policy_chunks(chunks_path):
        rule_candidates.extend(extract_candidates_from_text(**chunk))
    write_jsonl(rule_path, rule_candidates)
    return {
        "ontology_candidates_path": str(ontology_path),
        "rule_candidates_path": str(rule_path),
        "ontology_candidate_count": len(ontology_result.candidates),
        "rule_candidate_count": len(rule_candidates),
        "ontology_warnings": ontology_result.warnings,
    }


def _candidate_extraction_manifest() -> Path:
    if ACTIVE_ONTOLOGY_MANIFEST.exists():
        return ACTIVE_ONTOLOGY_MANIFEST
    return BASE_ONTOLOGY_MANIFEST


def _publish_candidate_outputs(job: IntakeJob, staging_chunks_path: Path, candidate_details: dict[str, Any]) -> dict[str, Any]:
    ontology_result = _publish_ontology_candidates(
        job,
        staging_chunks_path,
        Path(str(candidate_details["ontology_candidates_path"])),
    )
    rule_result = _publish_rule_candidates(
        job,
        staging_chunks_path,
        Path(str(candidate_details["rule_candidates_path"])),
    )
    return {
        "published_ontology_candidate_count": ontology_result["published"],
        "skipped_ontology_candidate_count": ontology_result["skipped"],
        "published_rule_candidate_count": rule_result["published"],
        "skipped_rule_candidate_count": rule_result["skipped"],
        "global_ontology_candidates_path": str(GLOBAL_ONTOLOGY_CANDIDATES_PATH),
        "global_rule_candidates_path": str(GLOBAL_RULE_CANDIDATES_PATH),
    }


def _publish_ontology_candidates(job: IntakeJob, staging_chunks_path: Path, path: Path) -> dict[str, int]:
    store = OntologyReviewStore(candidates_path=GLOBAL_ONTOLOGY_CANDIDATES_PATH)
    existing_ids = {candidate.candidate_id for candidate in store.load_candidates()}
    published = 0
    skipped = 0
    for row in _read_jsonl_dicts(path):
        candidate = OntologyCandidate.from_dict(row)
        if candidate.candidate_id in existing_ids:
            skipped += 1
            continue
        candidate.properties = dict(candidate.properties)
        candidate.properties.setdefault("intake_job_id", job.job_id)
        candidate.properties.setdefault("source_filename", job.original_filename)
        candidate.properties.setdefault("staging_chunks_path", str(staging_chunks_path))
        store.add_candidate(candidate)
        existing_ids.add(candidate.candidate_id)
        published += 1
    return {"published": published, "skipped": skipped}


def _publish_rule_candidates(job: IntakeJob, staging_chunks_path: Path, path: Path) -> dict[str, int]:
    existing = load_jsonl(GLOBAL_RULE_CANDIDATES_PATH)
    existing_ids = {str(row.get("candidate_id")) for row in existing if row.get("candidate_id")}
    new_rows = []
    skipped = 0
    for row in _read_jsonl_dicts(path):
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id in existing_ids:
            skipped += 1
            continue
        payload = dict(row)
        payload.setdefault("intake_job_id", job.job_id)
        payload.setdefault("source_filename", job.original_filename)
        payload.setdefault("staging_chunks_path", str(staging_chunks_path))
        new_rows.append(payload)
        existing_ids.add(candidate_id)
    if new_rows:
        write_jsonl(GLOBAL_RULE_CANDIDATES_PATH, [*existing, *new_rows])
    return {"published": len(new_rows), "skipped": skipped}


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows
