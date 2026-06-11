from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from src.graph.normalizer import normalize_name
from src.ontology.review_store import OntologyCandidate


SENTENCE_FRAGMENT_MARKERS = (
    "즉 ",
    "이에 반해",
    "해당되어",
    "하기로",
    "구분",
    "위한 ",
    "등에 대해",
    "않아야",
)


@dataclass(frozen=True)
class CandidateQualityIssue:
    severity: str
    code: str
    message: str
    term: str = ""
    related: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "term": self.term,
            "related": self.related,
            "recommendation": self.recommendation,
        }


def is_sentence_fragment(text: str) -> bool:
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if any(marker in value for marker in SENTENCE_FRAGMENT_MARKERS):
        return True
    # A candidate alias should usually be a compact concept expression. Long
    # predicate-like phrases are evidence snippets, not stable ontology terms.
    return len(value) >= 18 and (" " in value) and value.endswith(("된", "되어", "으며", "하고", "하는", "하기"))


def _candidate_label(candidate: OntologyCandidate) -> str:
    return f"{candidate.concept_id}({candidate.canonical_name}, {candidate.status})"


def _candidate_alias_owner_map(candidates: Iterable[OntologyCandidate]) -> dict[str, list[OntologyCandidate]]:
    owners: dict[str, list[OntologyCandidate]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for candidate in candidates:
        for alias in candidate.candidate_aliases:
            normalized = normalize_name(alias)
            if not normalized:
                continue
            key = (normalized, candidate.concept_id)
            if key in seen_pairs:
                continue
            owners.setdefault(normalized, []).append(candidate)
            seen_pairs.add(key)
    return owners


def _multi_owner_candidate_aliases(candidates: Iterable[OntologyCandidate]) -> set[str]:
    owner_map = _candidate_alias_owner_map(candidates)
    return {
        normalized
        for normalized, owners in owner_map.items()
        if len({owner.concept_id for owner in owners}) > 1
    }


def analyze_candidate_quality(
    candidate: OntologyCandidate,
    *,
    all_candidates: Iterable[OntologyCandidate] | None = None,
) -> list[CandidateQualityIssue]:
    issues: list[CandidateQualityIssue] = []
    for alias in candidate.candidate_aliases:
        if is_sentence_fragment(alias):
            issues.append(
                CandidateQualityIssue(
                    severity="warning",
                    code="sentence_fragment_alias",
                    term=alias,
                    message=f"'{alias}' 표현은 개념명보다 원문 문장 조각에 가깝습니다.",
                    recommendation="개념 alias로 바로 승인하지 말고 보류한 뒤 짧은 업무 용어로 정제하세요.",
                )
            )

    if all_candidates is not None:
        owner_map = _candidate_alias_owner_map(all_candidates)
        for alias in candidate.candidate_aliases:
            normalized = normalize_name(alias)
            owners = owner_map.get(normalized, [])
            owner_concepts = {owner.concept_id for owner in owners}
            if len(owner_concepts) <= 1:
                continue
            issues.append(
                CandidateQualityIssue(
                    severity="warning",
                    code="candidate_alias_multi_owner",
                    term=alias,
                    related=[_candidate_label(owner) for owner in owners],
                    message=f"'{alias}' 표현이 여러 후보 concept에 동시에 연결되어 있습니다.",
                    recommendation="표현 소유권이 명확한 concept 하나만 승인하고, 나머지는 보류 또는 거절하세요.",
                )
            )
    return issues


def sanitize_candidate_aliases(
    candidates: Iterable[OntologyCandidate],
) -> tuple[list[OntologyCandidate], list[dict[str, Any]]]:
    """Remove unsafe candidate aliases from review candidates.

    The repair is deliberately conservative: sentence-like evidence snippets and
    aliases that currently belong to multiple concept IDs are removed from every
    candidate. A practitioner can later reintroduce a concise alias for one
    owner concept through a new approval candidate.
    """

    original = [OntologyCandidate.from_dict(candidate.to_dict()) for candidate in candidates]
    duplicated_aliases = _multi_owner_candidate_aliases(original)
    repaired: list[OntologyCandidate] = []
    changes: list[dict[str, Any]] = []
    for candidate in original:
        kept: list[str] = []
        removed: list[dict[str, str]] = []
        for alias in candidate.candidate_aliases:
            normalized = normalize_name(alias)
            reason = ""
            if is_sentence_fragment(alias):
                reason = "sentence_fragment_alias"
            elif normalized in duplicated_aliases:
                reason = "candidate_alias_multi_owner"
            if reason:
                removed.append({"alias": alias, "reason": reason})
                continue
            kept.append(alias)
        if removed:
            candidate.candidate_aliases = kept
            candidate.properties = dict(candidate.properties)
            quality = dict(candidate.properties.get("quality_repair") or {})
            history = list(quality.get("removed_candidate_aliases") or [])
            history.extend(removed)
            quality["removed_candidate_aliases"] = history
            quality["repair_policy"] = "remove_sentence_fragments_and_multi_owner_aliases"
            candidate.properties["quality_repair"] = quality
            changes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "concept_id": candidate.concept_id,
                    "canonical_name": candidate.canonical_name,
                    "removed": removed,
                }
            )
        repaired.append(candidate)
    return repaired, changes


def find_manifest_candidate_alias_issues(concepts: Iterable[Any]) -> list[CandidateQualityIssue]:
    owners: dict[str, list[tuple[str, str, str]]] = {}
    issues: list[CandidateQualityIssue] = []
    seen_fragment_terms: set[tuple[str, str]] = set()

    for concept in concepts:
        concept_id = str(getattr(concept, "concept_id", "") or "").strip()
        canonical_name = str(getattr(concept, "canonical_name", "") or "").strip()
        if isinstance(concept, dict):
            concept_id = str(concept.get("concept_id") or "").strip()
            canonical_name = str(concept.get("canonical_name") or "").strip()
            aliases = concept.get("candidate_aliases") if isinstance(concept.get("candidate_aliases"), list) else []
        else:
            aliases = list(getattr(concept, "candidate_aliases", []) or [])

        for alias in aliases:
            term = " ".join(str(alias or "").split())
            normalized = normalize_name(term)
            if not normalized:
                continue
            owners.setdefault(normalized, []).append((concept_id, canonical_name, term))
            if is_sentence_fragment(term):
                key = (concept_id, normalized)
                if key in seen_fragment_terms:
                    continue
                seen_fragment_terms.add(key)
                issues.append(
                    CandidateQualityIssue(
                        severity="error",
                        code="sentence_fragment_alias",
                        term=term,
                        related=[f"{concept_id}({canonical_name})"],
                        message=f"{concept_id}: candidate_alias '{term}' is sentence-like evidence text",
                        recommendation="Remove it or replace it with a concise concept expression before applying.",
                    )
                )

    for normalized, hits in owners.items():
        concept_ids = {concept_id for concept_id, _, _ in hits}
        if len(concept_ids) <= 1:
            continue
        term = hits[0][2]
        issues.append(
            CandidateQualityIssue(
                severity="error",
                code="candidate_alias_multi_owner",
                term=term,
                related=[f"{concept_id}({canonical_name})" for concept_id, canonical_name, _ in hits],
                message=f"candidate_alias '{term}' maps to multiple concepts: {', '.join(sorted(concept_ids))}",
                recommendation="Keep the alias on one owner concept or convert it to a retrieval expansion rule.",
            )
        )
    return issues
