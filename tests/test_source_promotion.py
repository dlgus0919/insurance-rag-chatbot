from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.source_promotion import (
    collect_approved_intake_source_refs,
    load_active_source_chunks,
    load_active_source_manifest,
    promote_staging_chunks,
    validate_staging_source_refs,
    IntakeSourceRef,
)
from src.parser.chunker import Chunk, save_chunks


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_promote_staging_chunks_appends_provenance_and_manifest(tmp_path: Path) -> None:
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks(
        [
            Chunk(
                id="intake_001_doc_p001",
                text="4세대 급여 통원 80% 보상",
                metadata={
                    "doc_short": "intake_001_doc",
                    "doc_name": "새 약관",
                    "page_start": 1,
                    "page_end": 1,
                },
            )
        ],
        staging_path,
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    result = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )

    assert result.status == "promoted"
    assert result.job_id == "intake_001"
    assert result.chunk_count == 1
    assert result.chunks_path == active_chunks_path
    assert result.manifest_path == manifest_path
    assert result.source_filename == "new_policy.pdf"

    chunks = load_active_source_chunks(active_chunks_path)
    assert [chunk.id for chunk in chunks] == ["intake:intake_001:0001"]
    assert chunks[0].metadata["intake_job_id"] == "intake_001"
    assert chunks[0].metadata["source_status"] == "active_intake_source"
    assert chunks[0].metadata["source_method"] == "admin_digital_pdf_text_layer"
    assert chunks[0].metadata["source_filename"] == "new_policy.pdf"
    assert chunks[0].metadata["canonical_chunk_id"] == "intake_001_doc_p001"
    assert chunks[0].metadata["source_chunk_id"] == "intake_001_doc_p001"

    manifest = load_active_source_manifest(manifest_path)
    assert manifest == [
        {
            "job_id": "intake_001",
            "source_filename": "new_policy.pdf",
            "staging_chunks_path": str(staging_path),
            "active_chunks_path": str(active_chunks_path),
            "chunk_count": 1,
            "chunk_ids": ["intake:intake_001:0001"],
        }
    ]


def test_promote_staging_chunks_is_idempotent_by_job_id(tmp_path: Path) -> None:
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks(
        [Chunk(id="intake_001_doc_p001", text="본문", metadata={})],
        staging_path,
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    first = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )
    second = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )

    assert first.status == "promoted"
    assert second.status == "skipped"
    assert second.chunk_count == 0
    assert len(load_active_source_chunks(active_chunks_path)) == 1
    assert len(load_active_source_manifest(manifest_path)) == 1


def test_promote_staging_chunks_rejects_missing_empty_and_duplicate_outputs(tmp_path: Path) -> None:
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    with pytest.raises(FileNotFoundError):
        promote_staging_chunks(
            job_id="intake_001",
            staging_chunks_path=tmp_path / "missing.jsonl",
            source_filename="new_policy.pdf",
            active_chunks_path=active_chunks_path,
            manifest_path=manifest_path,
        )

    empty_path = tmp_path / "empty" / "chunks.jsonl"
    empty_path.parent.mkdir(parents=True)
    empty_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        promote_staging_chunks(
            job_id="intake_001",
            staging_chunks_path=empty_path,
            source_filename="new_policy.pdf",
            active_chunks_path=active_chunks_path,
            manifest_path=manifest_path,
        )

    save_chunks([Chunk(id="intake:intake_001:0001", text="기존", metadata={})], active_chunks_path)
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks([Chunk(id="source", text="본문", metadata={})], staging_path)
    with pytest.raises(ValueError, match="duplicate"):
        promote_staging_chunks(
            job_id="intake_001",
            staging_chunks_path=staging_path,
            source_filename="new_policy.pdf",
            active_chunks_path=active_chunks_path,
            manifest_path=manifest_path,
        )


def test_validate_staging_source_refs_checks_batch_before_any_write(tmp_path: Path) -> None:
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks([Chunk(id="source-1", text="본문", metadata={})], staging_path)
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    with pytest.raises(FileNotFoundError, match="intake_002"):
        validate_staging_source_refs(
            [
                IntakeSourceRef("intake_001", staging_path, "new_policy.pdf"),
                IntakeSourceRef("intake_002", tmp_path / "missing.jsonl", "missing.pdf"),
            ],
            active_chunks_path=active_chunks_path,
            manifest_path=manifest_path,
        )

    assert not active_chunks_path.exists()
    assert not manifest_path.exists()


def test_collect_approved_intake_source_refs_from_ontology_and_rule_candidates(tmp_path: Path) -> None:
    ontology_path = tmp_path / "ontology" / "candidates.jsonl"
    rule_path = tmp_path / "rules" / "candidates.jsonl"
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    _write_jsonl(
        ontology_path,
        [
            {
                "candidate_id": "dev.cov.demo.1",
                "concept_id": "cov.demo",
                "canonical_name": "테스트 보장",
                "status": "approved",
                "properties": {
                    "intake_job_id": "intake_001",
                    "source_filename": "new_policy.pdf",
                    "staging_chunks_path": str(staging_path),
                },
            },
            {
                "candidate_id": "dev.cov.demo.2",
                "concept_id": "cov.pending",
                "canonical_name": "미승인 보장",
                "status": "pending",
                "properties": {
                    "intake_job_id": "intake_002",
                    "source_filename": "pending.pdf",
                    "staging_chunks_path": str(tmp_path / "jobs" / "intake_002" / "staging" / "chunks.jsonl"),
                },
            },
            {
                "candidate_id": "dev.cov.demo.3",
                "concept_id": "cov.missing_path",
                "canonical_name": "경로 없는 보장",
                "status": "approved",
                "properties": {"intake_job_id": "intake_003"},
            },
        ],
    )
    _write_jsonl(
        rule_path,
        [
            {
                "candidate_id": "rulecand.demo.1",
                "status": "approved",
                "intake_job_id": "intake_001",
                "source_filename": "duplicate.pdf",
                "staging_chunks_path": str(staging_path),
                "proposed_rule": {"rule_id": "rule.demo"},
            },
            {
                "candidate_id": "rulecand.demo.2",
                "status": "approved",
                "intake_job_id": "intake_004",
                "source_filename": "rule_policy.pdf",
                "staging_chunks_path": str(tmp_path / "jobs" / "intake_004" / "staging" / "chunks.jsonl"),
                "proposed_rule": {"rule_id": "rule.demo.2"},
            },
        ],
    )

    refs = collect_approved_intake_source_refs(
        ontology_candidates_path=ontology_path,
        rule_candidates_path=rule_path,
    )

    assert [ref.job_id for ref in refs] == ["intake_001", "intake_004"]
    assert refs[0].source_filename == "new_policy.pdf"
    assert refs[0].staging_chunks_path == staging_path
    assert refs[1].source_filename == "rule_policy.pdf"
