from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import audit_ontology_approval_integrity
from scripts import ontology_review
from src.ontology.approval_integrity import BaseManifestLock, manifest_content_hash
from src.ontology.manifest_merge import merge_approved_candidates
from src.ontology.review_store import APPROVED, OntologyCandidate, OntologyReviewStore


class _ReviewStore:
    def __init__(self, candidate: OntologyCandidate) -> None:
        self.candidate = candidate
        self.decision_kwargs: dict[str, object] | None = None

    def get_candidate(self, candidate_id: str) -> OntologyCandidate:
        assert candidate_id == self.candidate.candidate_id
        return self.candidate

    def load_candidates(self) -> list[OntologyCandidate]:
        return [self.candidate]

    def available_approval_operations(self, candidate_id: str) -> list[dict[str, str]]:
        assert candidate_id == self.candidate.candidate_id
        return [
            {
                "path": "/concepts/cond.alpha/evidence_tags/hash-alpha",
                "field_label": "근거 태그",
                "value_preview": "source:alpha",
                "value_hash": "hash-alpha",
            }
        ]

    def decide(self, candidate_id: str, decision: str, **kwargs: object) -> OntologyCandidate:
        assert candidate_id == self.candidate.candidate_id
        assert decision == "approve"
        self.decision_kwargs = kwargs
        return self.candidate


def _candidate() -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id="cand-cli",
        concept_id="cond.alpha",
        canonical_name="CLI 검토 후보",
        evidence_tags=["source:alpha"],
    )


def test_cli_show_includes_explicit_approval_operations(
    monkeypatch,
    capsys,
) -> None:
    store = _ReviewStore(_candidate())
    monkeypatch.setattr(ontology_review, "OntologyReviewStore", lambda: store)
    monkeypatch.setattr(sys, "argv", ["ontology_review.py", "--show", "cand-cli"])

    assert ontology_review.main() == 0

    output = capsys.readouterr().out
    assert "승인 가능 변경 항목" in output
    assert "근거 태그" in output
    assert "/concepts/cond.alpha/evidence_tags/hash-alpha" in output


def test_cli_passes_only_explicit_approval_paths_to_store(monkeypatch) -> None:
    store = _ReviewStore(_candidate())
    path = "/concepts/cond.alpha/evidence_tags/hash-alpha"
    monkeypatch.setattr(ontology_review, "OntologyReviewStore", lambda: store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ontology_review.py",
            "--decide",
            "cand-cli",
            "--decision",
            "approve",
            "--reason",
            "명시 항목 승인",
            "--approve-path",
            path,
        ],
    )

    assert ontology_review.main() == 0
    assert store.decision_kwargs is not None
    assert store.decision_kwargs["approved_paths"] == [path]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "version": "base-test",
        "description": "test manifest",
        "concepts": [
            {
                "concept_id": "cond.alpha",
                "canonical_name": "기존 조건",
                "node_type": "ClaimCondition",
            }
        ],
    }


def _approved_store(tmp_path: Path) -> tuple[OntologyReviewStore, Path, Path]:
    base_path = tmp_path / "concepts.json"
    base_payload = _base_payload()
    _write_json(base_path, base_payload)
    lock_path = tmp_path / "base_manifest.lock.json"
    BaseManifestLock.from_manifest(
        base_payload,
        source_commit="test-commit",
        review_record_id="test-review",
    ).write(lock_path)
    candidate = OntologyCandidate(
        candidate_id="cand-dry-run",
        concept_id="cond.alpha",
        canonical_name="기존 조건",
        evidence_tags=["source:alpha"],
        properties={"candidate_type": "evidence_tag", "target_concept_id": "cond.alpha"},
        source_evidence=[{"chunk_id": "chunk-alpha", "excerpt": "근거"}],
    )
    store = OntologyReviewStore(
        candidates_path=tmp_path / "candidates.jsonl",
        review_log_path=tmp_path / "review_log.jsonl",
        applied_reviews_path=tmp_path / "applied_reviews.jsonl",
    )
    store.add_candidate(candidate)
    available = store.available_approval_operations(
        candidate.candidate_id,
        base_manifest_path=base_path,
    )
    store.decide(
        candidate.candidate_id,
        "approve",
        reviewer="tester",
        approved_paths=[available[0]["path"]],
        base_manifest_path=base_path,
    )
    return store, base_path, lock_path


def test_apply_reviews_dry_run_uses_real_merge_and_preserves_runtime_files(tmp_path: Path) -> None:
    store, base_path, lock_path = _approved_store(tmp_path)
    active_path = tmp_path / "concepts.active.json"
    provenance_path = tmp_path / "concepts.active.provenance.json"

    preview = ontology_review.apply_reviews(
        store,
        dry_run=True,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        active_manifest_path=active_path,
        provenance_path=provenance_path,
    )

    assert preview.status == "dry_run"
    assert preview.merge_result is not None
    assert preview.audit is not None
    assert preview.audit.report.state == "valid"
    assert preview.merge_result.applied_operation_count == 1
    assert preview.concept_diffs
    assert not active_path.exists()
    assert not provenance_path.exists()


def test_apply_reviews_dry_run_previews_locked_base_when_no_candidates_exist(tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    base_payload = _base_payload()
    _write_json(base_path, base_payload)
    lock_path = tmp_path / "base_manifest.lock.json"
    BaseManifestLock.from_manifest(
        base_payload,
        source_commit="test-commit",
        review_record_id="test-review",
    ).write(lock_path)
    active_path = tmp_path / "concepts.active.json"
    provenance_path = tmp_path / "concepts.active.provenance.json"
    store = OntologyReviewStore(
        candidates_path=tmp_path / "candidates.jsonl",
        review_log_path=tmp_path / "review_log.jsonl",
        applied_reviews_path=tmp_path / "applied_reviews.jsonl",
    )

    preview = ontology_review.apply_reviews(
        store,
        dry_run=True,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        active_manifest_path=active_path,
        provenance_path=provenance_path,
    )

    assert preview.status == "dry_run"
    assert preview.valid is True
    assert preview.merge_result is not None
    assert preview.merge_result.base_concept_count == 1
    assert preview.merge_result.applied_operation_count == 0
    assert preview.concept_diffs == ()
    assert not active_path.exists()
    assert not provenance_path.exists()


def test_apply_reviews_dry_run_reports_legacy_candidate_without_patch(tmp_path: Path) -> None:
    store, base_path, lock_path = _approved_store(tmp_path)
    candidate = store.get_candidate("cand-dry-run")
    candidate.status = APPROVED
    store.add_candidate(candidate, replace=True)
    (tmp_path / "review_log.jsonl").unlink()

    preview = ontology_review.apply_reviews(
        store,
        dry_run=True,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        active_manifest_path=tmp_path / "concepts.active.json",
        provenance_path=tmp_path / "concepts.active.provenance.json",
    )

    assert preview.status == "legacy_unverifiable"
    assert preview.legacy_unverifiable_candidate_ids == ("cand-dry-run",)


def test_cli_build_base_lock_writes_only_requested_lock(monkeypatch, tmp_path: Path) -> None:
    base_path = tmp_path / "concepts.json"
    output_path = tmp_path / "base_manifest.lock.json"
    _write_json(base_path, _base_payload())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ontology_review.py",
            "--build-base-lock",
            "--base",
            str(base_path),
            "--source-commit",
            "test-commit",
            "--review-record-id",
            "test-review",
            "--output",
            str(output_path),
        ],
    )

    assert ontology_review.main() == 0
    lock = json.loads(output_path.read_text(encoding="utf-8"))
    assert lock["source_commit"] == "test-commit"
    assert lock["concept_hashes"].keys() == {"cond.alpha"}


def _active_audit_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    store, base_path, lock_path = _approved_store(tmp_path)
    candidates = store.approved_or_applied_candidates()
    patches = {
        candidate.candidate_id: store.latest_approval_patch(candidate.candidate_id)
        for candidate in candidates
    }
    assert all(patch is not None for patch in patches.values())
    active_path = tmp_path / "concepts.active.json"
    provenance_path = tmp_path / "concepts.active.provenance.json"
    merge_approved_candidates(
        candidates,
        approval_patches=patches,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        output_path=active_path,
        provenance_path=provenance_path,
    )
    return base_path, lock_path, active_path, provenance_path


def _audit_argv(
    base_path: Path,
    lock_path: Path,
    active_path: Path,
    provenance_path: Path,
) -> list[str]:
    return [
        "audit_ontology_approval_integrity.py",
        "--base",
        str(base_path),
        "--base-lock",
        str(lock_path),
        "--active",
        str(active_path),
        "--provenance",
        str(provenance_path),
        "--format",
        "json",
    ]


def test_integrity_audit_cli_returns_zero_for_valid_active_manifest(monkeypatch, capsys, tmp_path: Path) -> None:
    paths = _active_audit_paths(tmp_path)
    monkeypatch.setattr(sys, "argv", _audit_argv(*paths))

    assert audit_ontology_approval_integrity.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "valid"
    assert payload["exit_code"] == 0


def test_integrity_audit_cli_returns_two_for_unproven_active_delta(monkeypatch, capsys, tmp_path: Path) -> None:
    base_path, lock_path, active_path, provenance_path = _active_audit_paths(tmp_path)
    active = json.loads(active_path.read_text(encoding="utf-8"))
    active["concepts"].append({"concept_id": "cond.unproven", "canonical_name": "미증명 개념"})
    _write_json(active_path, active)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["active_content_hash"] = manifest_content_hash(active)
    _write_json(provenance_path, provenance)
    monkeypatch.setattr(sys, "argv", _audit_argv(base_path, lock_path, active_path, provenance_path))

    assert audit_ontology_approval_integrity.main() == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "legacy_unverifiable"
    assert payload["exit_code"] == 2
    assert payload["quarantined_concept_ids"] == ["cond.unproven"]


def test_integrity_audit_cli_returns_three_for_active_hash_mismatch(monkeypatch, capsys, tmp_path: Path) -> None:
    base_path, lock_path, active_path, provenance_path = _active_audit_paths(tmp_path)
    active = json.loads(active_path.read_text(encoding="utf-8"))
    active["description"] = "변경된 설명"
    _write_json(active_path, active)
    monkeypatch.setattr(sys, "argv", _audit_argv(base_path, lock_path, active_path, provenance_path))

    assert audit_ontology_approval_integrity.main() == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["exit_code"] == 3


def test_integrity_audit_cli_returns_four_for_malformed_input(monkeypatch, capsys, tmp_path: Path) -> None:
    base_path, lock_path, active_path, provenance_path = _active_audit_paths(tmp_path)
    active_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _audit_argv(base_path, lock_path, active_path, provenance_path))

    assert audit_ontology_approval_integrity.main() == 4

    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 4
    assert payload["state"] == "invalid_input"
