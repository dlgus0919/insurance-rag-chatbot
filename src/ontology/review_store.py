from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.ontology.registry import ONTOLOGY_DIR


REVIEW_DIR = ONTOLOGY_DIR / "review"
DEFAULT_CANDIDATES_PATH = REVIEW_DIR / "candidates.jsonl"
DEFAULT_REVIEW_LOG_PATH = REVIEW_DIR / "review_log.jsonl"
DEFAULT_APPLIED_REVIEWS_PATH = REVIEW_DIR / "applied_reviews.jsonl"

PENDING = "pending"
APPROVED = "approved"
HELD = "held"
REJECTED = "rejected"
APPLIED = "applied"
VALID_STATUSES = {PENDING, APPROVED, HELD, REJECTED, APPLIED}
VALID_DECISIONS = {"approve", "hold", "reject"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    tmp_path.replace(path)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass
class OntologyCandidate:
    candidate_id: str
    concept_id: str
    canonical_name: str
    node_type: str = ""
    aliases: list[str] = field(default_factory=list)
    candidate_aliases: list[str] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)
    planner: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    source_evidence: list[dict[str, Any]] = field(default_factory=list)
    status: str = PENDING
    risk_flags: list[str] = field(default_factory=list)
    test_candidate: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    extraction_run_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OntologyCandidate":
        status = str(payload.get("status") or PENDING).strip()
        if status not in VALID_STATUSES:
            status = PENDING
        return cls(
            candidate_id=str(payload.get("candidate_id") or "").strip(),
            concept_id=str(payload.get("concept_id") or "").strip(),
            canonical_name=str(payload.get("canonical_name") or "").strip(),
            node_type=str(payload.get("node_type") or "").strip(),
            aliases=_string_list(payload.get("aliases")),
            candidate_aliases=_string_list(payload.get("candidate_aliases")),
            evidence_tags=_string_list(payload.get("evidence_tags")),
            planner=dict(payload.get("planner") or {}),
            retrieval=dict(payload.get("retrieval") or {}),
            properties=dict(payload.get("properties") or {}),
            source_evidence=[
                dict(item)
                for item in payload.get("source_evidence", [])
                if isinstance(item, dict)
            ],
            status=status,
            risk_flags=_string_list(payload.get("risk_flags")),
            test_candidate=bool(payload.get("test_candidate") is True),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            extraction_run_id=str(payload.get("extraction_run_id") or "").strip(),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.candidate_id:
            errors.append("candidate_id is required")
        if not self.concept_id:
            errors.append(f"{self.candidate_id}: concept_id is required")
        if not self.canonical_name:
            errors.append(f"{self.candidate_id}: canonical_name is required")
        if self.status not in VALID_STATUSES:
            errors.append(f"{self.candidate_id}: invalid status {self.status}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "concept_id": self.concept_id,
            "canonical_name": self.canonical_name,
            "node_type": self.node_type,
            "aliases": self.aliases,
            "candidate_aliases": self.candidate_aliases,
            "evidence_tags": self.evidence_tags,
            "planner": self.planner,
            "retrieval": self.retrieval,
            "properties": self.properties,
            "source_evidence": self.source_evidence,
            "status": self.status,
            "risk_flags": self.risk_flags,
            "test_candidate": self.test_candidate,
            "created_at": self.created_at,
            "extraction_run_id": self.extraction_run_id,
        }

    def runtime_concept(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "concept_id": self.concept_id,
            "canonical_name": self.canonical_name,
        }
        if self.node_type:
            payload["node_type"] = self.node_type
        if self.aliases:
            payload["aliases"] = self.aliases
        if self.candidate_aliases:
            payload["candidate_aliases"] = self.candidate_aliases
        if self.evidence_tags:
            payload["evidence_tags"] = self.evidence_tags
        if self.planner:
            payload["planner"] = self.planner
        if self.retrieval:
            payload["retrieval"] = self.retrieval
        properties = dict(self.properties)
        properties.setdefault("approval_candidate_id", self.candidate_id)
        properties.setdefault("approval_status", self.status)
        if self.source_evidence:
            properties.setdefault("source_evidence_count", len(self.source_evidence))
        if properties:
            payload["properties"] = properties
        return payload


class OntologyReviewStore:
    def __init__(
        self,
        candidates_path: str | Path = DEFAULT_CANDIDATES_PATH,
        review_log_path: str | Path = DEFAULT_REVIEW_LOG_PATH,
        applied_reviews_path: str | Path = DEFAULT_APPLIED_REVIEWS_PATH,
    ) -> None:
        self.candidates_path = Path(candidates_path)
        self.review_log_path = Path(review_log_path)
        self.applied_reviews_path = Path(applied_reviews_path)

    def load_candidates(self) -> list[OntologyCandidate]:
        return [OntologyCandidate.from_dict(row) for row in _read_jsonl(self.candidates_path)]

    def save_candidates(self, candidates: Iterable[OntologyCandidate]) -> None:
        rows = [candidate.to_dict() for candidate in candidates]
        _write_jsonl(self.candidates_path, rows)

    def add_candidate(self, candidate: OntologyCandidate, *, replace: bool = False) -> None:
        errors = candidate.validate()
        if errors:
            raise ValueError("; ".join(errors))
        candidates = self.load_candidates()
        existing_ids = {item.candidate_id for item in candidates}
        if candidate.candidate_id in existing_ids:
            if not replace:
                raise ValueError(f"candidate already exists: {candidate.candidate_id}")
            candidates = [item for item in candidates if item.candidate_id != candidate.candidate_id]
        candidates.append(candidate)
        self.save_candidates(candidates)

    def get_candidate(self, candidate_id: str) -> OntologyCandidate:
        for candidate in self.load_candidates():
            if candidate.candidate_id == candidate_id:
                return candidate
        raise KeyError(f"candidate not found: {candidate_id}")

    def candidates_by_status(self, status: str) -> list[OntologyCandidate]:
        return [candidate for candidate in self.load_candidates() if candidate.status == status]

    def pending_candidates(self) -> list[OntologyCandidate]:
        return self.candidates_by_status(PENDING)

    def approved_or_applied_candidates(self) -> list[OntologyCandidate]:
        return [
            candidate
            for candidate in self.load_candidates()
            if candidate.status in {APPROVED, APPLIED}
        ]

    def summary(self) -> dict[str, int]:
        result = {status: 0 for status in sorted(VALID_STATUSES)}
        for candidate in self.load_candidates():
            result[candidate.status] = result.get(candidate.status, 0) + 1
        result["total"] = sum(result.values())
        return result

    def decide(
        self,
        candidate_id: str,
        decision: str,
        *,
        reviewer: str = "unknown",
        reviewer_type: str = "practitioner",
        reason: str = "",
    ) -> OntologyCandidate:
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision: {decision}")
        candidates = self.load_candidates()
        updated: OntologyCandidate | None = None
        after_status = {
            "approve": APPROVED,
            "hold": HELD,
            "reject": REJECTED,
        }[decision]
        for candidate in candidates:
            if candidate.candidate_id != candidate_id:
                continue
            before_status = candidate.status
            candidate.status = after_status
            updated = candidate
            self._append_review_log(
                {
                    "review_id": str(uuid.uuid4()),
                    "candidate_id": candidate_id,
                    "decision": decision,
                    "reviewer": reviewer,
                    "reviewer_type": reviewer_type,
                    "reason": reason,
                    "created_at": utc_now_iso(),
                    "before_status": before_status,
                    "after_status": after_status,
                }
            )
            break
        if updated is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        self.save_candidates(candidates)
        return updated

    def auto_approve_test_candidates(self, *, reviewer: str = "codex-test-auto", dry_run: bool = False) -> list[OntologyCandidate]:
        candidates = self.load_candidates()
        selected = [
            candidate
            for candidate in candidates
            if candidate.status == PENDING and candidate.test_candidate is True
        ]
        if dry_run:
            return selected
        for candidate in selected:
            self.decide(
                candidate.candidate_id,
                "approve",
                reviewer=reviewer,
                reviewer_type="codex_test_auto",
                reason="test_candidate auto approval",
            )
        return selected

    def mark_approved_as_applied(self, *, manifest_path: str | Path) -> list[OntologyCandidate]:
        candidates = self.load_candidates()
        applied: list[OntologyCandidate] = []
        for candidate in candidates:
            if candidate.status != APPROVED:
                continue
            before_status = candidate.status
            candidate.status = APPLIED
            candidate.properties = dict(candidate.properties)
            candidate.properties["applied_manifest_path"] = str(manifest_path)
            candidate.properties["applied_at"] = utc_now_iso()
            applied.append(candidate)
            self._append_review_log(
                {
                    "review_id": str(uuid.uuid4()),
                    "candidate_id": candidate.candidate_id,
                    "decision": "apply",
                    "reviewer": "system",
                    "reviewer_type": "system",
                    "reason": f"merged into {manifest_path}",
                    "created_at": utc_now_iso(),
                    "before_status": before_status,
                    "after_status": APPLIED,
                }
            )
            _append_jsonl(
                self.applied_reviews_path,
                {
                    "candidate_id": candidate.candidate_id,
                    "concept_id": candidate.concept_id,
                    "manifest_path": str(manifest_path),
                    "applied_at": candidate.properties["applied_at"],
                },
            )
        if applied:
            self.save_candidates(candidates)
        return applied

    def _append_review_log(self, row: dict[str, Any]) -> None:
        _append_jsonl(self.review_log_path, row)


def build_test_candidate(candidate_id: str = "test.ontology.demo") -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id=candidate_id,
        concept_id="cond.test_practitioner_approval",
        canonical_name="테스트 승인 개념",
        node_type="ClaimCondition",
        aliases=["테스트 승인 개념", "테스트온톨로지"],
        planner={
            "conditions": ["테스트 승인 개념"],
            "intents": ["claim_condition_lookup", "session_claim_path_review"],
        },
        retrieval={
            "expansion_rules": [
                {
                    "match_any": ["테스트온톨로지"],
                    "expansion_terms": ["실무자 승인 테스트", "GraphDB 재구축 테스트"],
                }
            ]
        },
        source_evidence=[
            {
                "doc_short": "테스트",
                "doc_name": "테스트 온톨로지 후보",
                "page": 1,
                "chunk_id": "test-ontology-demo",
                "excerpt": "테스트 후보 자동 승인 흐름 검증용 후보입니다.",
                "confidence": 1.0,
            }
        ],
        risk_flags=["test_only"],
        test_candidate=True,
        extraction_run_id="manual-test-seed",
    )
