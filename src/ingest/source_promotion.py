"""Promote reviewed intake staging chunks into active source overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.claim_rule_candidate_review import load_jsonl
from src import config
from src.ontology.review_store import OntologyReviewStore
from src.parser.chunker import Chunk, chunk_to_dict, load_chunks

ACTIVE_SOURCE_ROOT = config.ROOT_DIR / "data" / "intake" / "active_sources"
ACTIVE_SOURCE_CHUNKS_PATH = ACTIVE_SOURCE_ROOT / "chunks.jsonl"
ACTIVE_SOURCE_MANIFEST_PATH = ACTIVE_SOURCE_ROOT / "manifest.jsonl"


@dataclass(frozen=True)
class IntakeSourceRef:
    job_id: str
    staging_chunks_path: Path
    source_filename: str


@dataclass(frozen=True)
class SourcePromotionResult:
    status: str
    job_id: str
    chunk_count: int
    chunks_path: Path
    manifest_path: Path
    source_filename: str


def load_active_source_chunks(path: Path = ACTIVE_SOURCE_CHUNKS_PATH) -> list[Chunk]:
    if not path.exists():
        return []
    return load_chunks(path)


def load_active_source_manifest(path: Path = ACTIVE_SOURCE_MANIFEST_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def collect_approved_intake_source_refs(
    ontology_candidates_path: Path,
    rule_candidates_path: Path,
) -> list[IntakeSourceRef]:
    refs_by_job_id: dict[str, IntakeSourceRef] = {}

    ontology_store = OntologyReviewStore(candidates_path=ontology_candidates_path)
    for candidate in ontology_store.load_candidates():
        if candidate.status != "approved":
            continue
        ref = _ref_from_payload(candidate.properties)
        if ref is not None:
            refs_by_job_id.setdefault(ref.job_id, ref)

    for candidate in load_jsonl(rule_candidates_path):
        if candidate.get("status") != "approved":
            continue
        ref = _ref_from_payload(candidate)
        if ref is not None:
            refs_by_job_id.setdefault(ref.job_id, ref)

    return sorted(refs_by_job_id.values(), key=lambda ref: ref.job_id)


def promote_staging_chunks(
    job_id: str,
    staging_chunks_path: Path,
    source_filename: str,
    active_chunks_path: Path = ACTIVE_SOURCE_CHUNKS_PATH,
    manifest_path: Path = ACTIVE_SOURCE_MANIFEST_PATH,
) -> SourcePromotionResult:
    manifest_rows = load_active_source_manifest(manifest_path)
    if any(row.get("job_id") == job_id for row in manifest_rows):
        return SourcePromotionResult(
            status="skipped",
            job_id=job_id,
            chunk_count=0,
            chunks_path=active_chunks_path,
            manifest_path=manifest_path,
            source_filename=source_filename,
        )

    if not staging_chunks_path.exists():
        raise FileNotFoundError(f"staging chunks not found for {job_id}: {staging_chunks_path}")

    staged_chunks = load_chunks(staging_chunks_path)
    if not staged_chunks:
        raise ValueError(f"staging chunks are empty for {job_id}: {staging_chunks_path}")

    promoted_chunks = [
        _promote_chunk(
            chunk,
            job_id=job_id,
            index=index,
            source_filename=source_filename,
        )
        for index, chunk in enumerate(staged_chunks, start=1)
    ]
    _raise_for_duplicate_chunk_ids([*load_active_source_chunks(active_chunks_path), *promoted_chunks])

    active_chunks_path.parent.mkdir(parents=True, exist_ok=True)
    with active_chunks_path.open("a", encoding="utf-8") as file:
        for chunk in promoted_chunks:
            file.write(json.dumps(chunk_to_dict(chunk), ensure_ascii=False) + "\n")

    manifest_row = {
        "job_id": job_id,
        "source_filename": source_filename,
        "staging_chunks_path": str(staging_chunks_path),
        "active_chunks_path": str(active_chunks_path),
        "chunk_count": len(promoted_chunks),
        "chunk_ids": [chunk.id for chunk in promoted_chunks],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(manifest_row, ensure_ascii=False, sort_keys=True) + "\n")

    return SourcePromotionResult(
        status="promoted",
        job_id=job_id,
        chunk_count=len(promoted_chunks),
        chunks_path=active_chunks_path,
        manifest_path=manifest_path,
        source_filename=source_filename,
    )


def validate_staging_source_refs(
    refs: list[IntakeSourceRef],
    active_chunks_path: Path = ACTIVE_SOURCE_CHUNKS_PATH,
    manifest_path: Path = ACTIVE_SOURCE_MANIFEST_PATH,
) -> None:
    """Validate all pending source refs before appending any active source data."""

    promoted_job_ids = {str(row.get("job_id")) for row in load_active_source_manifest(manifest_path)}
    existing_chunks = load_active_source_chunks(active_chunks_path)
    planned_chunks: list[Chunk] = []

    for ref in refs:
        if ref.job_id in promoted_job_ids:
            continue
        if not ref.staging_chunks_path.exists():
            raise FileNotFoundError(f"staging chunks not found for {ref.job_id}: {ref.staging_chunks_path}")
        staged_chunks = load_chunks(ref.staging_chunks_path)
        if not staged_chunks:
            raise ValueError(f"staging chunks are empty for {ref.job_id}: {ref.staging_chunks_path}")
        planned_chunks.extend(
            _promote_chunk(
                chunk,
                job_id=ref.job_id,
                index=index,
                source_filename=ref.source_filename,
            )
            for index, chunk in enumerate(staged_chunks, start=1)
        )

    _raise_for_duplicate_chunk_ids([*existing_chunks, *planned_chunks])


def _ref_from_payload(payload: dict[str, Any]) -> IntakeSourceRef | None:
    job_id = str(payload.get("intake_job_id") or "").strip()
    staging_chunks_path = str(payload.get("staging_chunks_path") or "").strip()
    if not job_id or not staging_chunks_path:
        return None
    return IntakeSourceRef(
        job_id=job_id,
        staging_chunks_path=Path(staging_chunks_path),
        source_filename=str(payload.get("source_filename") or "").strip(),
    )


def _promote_chunk(chunk: Chunk, *, job_id: str, index: int, source_filename: str) -> Chunk:
    original_id = chunk.id
    metadata = dict(chunk.metadata)
    metadata["intake_job_id"] = job_id
    metadata["source_filename"] = source_filename
    metadata["source_status"] = "active_intake_source"
    metadata["source_method"] = "admin_digital_pdf_text_layer"
    metadata["canonical_chunk_id"] = original_id
    metadata["source_chunk_id"] = original_id
    return Chunk(
        id=f"intake:{job_id}:{index:04d}",
        text=chunk.text,
        metadata=metadata,
    )


def _raise_for_duplicate_chunk_ids(chunks: list[Chunk]) -> None:
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.id in seen:
            raise ValueError(f"duplicate active source chunk id: {chunk.id}")
        seen.add(chunk.id)
