from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.graph.normalizer import normalize_name
from src.ontology.registry import ACTIVE_ONTOLOGY_MANIFEST, BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import APPLIED, APPROVED, OntologyCandidate, utc_now_iso

REINFORCEMENT_CANDIDATE_TYPES = {
    "alias_or_expansion",
    "evidence_tag",
    "search_query_expansion",
}


@dataclass(frozen=True)
class ManifestMergeResult:
    output_path: Path
    base_concept_count: int
    merged_candidate_count: int
    total_concept_count: int
    warnings: list[str] = field(default_factory=list)


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid manifest object: {path}")
    concepts = payload.get("concepts")
    if not isinstance(concepts, list):
        raise ValueError(f"manifest concepts must be a list: {path}")
    return payload


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _candidate_runtime_concepts(candidates: Iterable[OntologyCandidate]) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.status not in {APPROVED, APPLIED}:
            continue
        concepts.append(candidate.runtime_concept())
    return concepts


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in values:
        values.append(value)


def _merge_string_list(target: dict[str, Any], key: str, values: list[str]) -> None:
    merged = [str(item) for item in _as_list(target.get(key)) if str(item).strip()]
    for value in values:
        text = str(value).strip()
        if text:
            _append_unique(merged, text)
    if merged:
        target[key] = merged


def _merge_planner(target: dict[str, Any], planner: dict[str, Any]) -> None:
    if not planner:
        return
    target_planner = dict(target.get("planner") or {})
    for key, value in planner.items():
        if isinstance(value, list):
            _merge_string_list(target_planner, key, [str(item) for item in value])
    if target_planner:
        target["planner"] = target_planner


def _merge_retrieval(target: dict[str, Any], retrieval: dict[str, Any]) -> None:
    rules = retrieval.get("expansion_rules") if isinstance(retrieval.get("expansion_rules"), list) else []
    if not rules:
        return
    target_retrieval = dict(target.get("retrieval") or {})
    existing_rules = [
        dict(rule)
        for rule in _as_list(target_retrieval.get("expansion_rules"))
        if isinstance(rule, dict)
    ]
    existing_keys = {
        json.dumps(rule, ensure_ascii=False, sort_keys=True)
        for rule in existing_rules
    }
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        key = json.dumps(rule, ensure_ascii=False, sort_keys=True)
        if key not in existing_keys:
            existing_rules.append(dict(rule))
            existing_keys.add(key)
    target_retrieval["expansion_rules"] = existing_rules
    target["retrieval"] = target_retrieval


def _is_reinforcement_candidate(candidate: OntologyCandidate, base_ids: set[str]) -> bool:
    candidate_type = str(candidate.properties.get("candidate_type") or "").strip()
    target = str(candidate.properties.get("target_concept_id") or candidate.concept_id).strip()
    return candidate_type in REINFORCEMENT_CANDIDATE_TYPES and target in base_ids


def _apply_reinforcement_candidate(base_concepts: list[dict[str, Any]], candidate: OntologyCandidate) -> None:
    target_id = str(candidate.properties.get("target_concept_id") or candidate.concept_id).strip()
    for concept in base_concepts:
        if str(concept.get("concept_id") or "").strip() != target_id:
            continue
        _merge_string_list(concept, "aliases", candidate.aliases)
        _merge_string_list(concept, "candidate_aliases", candidate.candidate_aliases)
        _merge_string_list(concept, "evidence_tags", candidate.evidence_tags)
        _merge_planner(concept, candidate.planner)
        _merge_retrieval(concept, candidate.retrieval)
        properties = dict(concept.get("properties") or {})
        approval_ids = [str(item) for item in _as_list(properties.get("approval_candidate_ids"))]
        _append_unique(approval_ids, candidate.candidate_id)
        properties["approval_candidate_ids"] = approval_ids
        properties["last_approval_status"] = candidate.status
        if candidate.source_evidence:
            properties["source_evidence_count"] = int(properties.get("source_evidence_count") or 0) + len(candidate.source_evidence)
        concept["properties"] = properties
        return
    raise ValueError(f"target concept not found for reinforcement candidate: {target_id}")


def _validate_no_conflicts(base_concepts: list[dict[str, Any]], candidate_concepts: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    concept_ids: dict[str, str] = {}
    aliases: dict[str, str] = {}

    for source, concepts in (("base", base_concepts), ("candidate", candidate_concepts)):
        for concept in concepts:
            concept_id = str(concept.get("concept_id") or "").strip()
            canonical = str(concept.get("canonical_name") or "").strip()
            if not concept_id or not canonical:
                raise ValueError(f"{source}: concept_id and canonical_name are required")
            if concept_id in concept_ids:
                raise ValueError(f"duplicated concept_id: {concept_id}")
            concept_ids[concept_id] = source

            raw_aliases = concept.get("aliases") if isinstance(concept.get("aliases"), list) else []
            for alias in [canonical, *raw_aliases]:
                normalized = normalize_name(str(alias))
                if not normalized:
                    continue
                owner = aliases.get(normalized)
                if owner and owner != concept_id:
                    message = f"alias conflict: {alias} maps to both {owner} and {concept_id}"
                    if source == "base":
                        warnings.append(f"base manifest existing {message}")
                        continue
                    raise ValueError(message)
                aliases[normalized] = concept_id

            if source == "candidate" and not raw_aliases:
                warnings.append(f"{concept_id}: candidate has no aliases")
    return warnings


def merge_approved_candidates(
    candidates: Iterable[OntologyCandidate],
    *,
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
    output_path: str | Path = ACTIVE_ONTOLOGY_MANIFEST,
) -> ManifestMergeResult:
    base_path = Path(base_manifest_path)
    target_path = Path(output_path)
    base_payload = _load_manifest(base_path)
    base_concepts = [
        dict(item)
        for item in base_payload.get("concepts", [])
        if isinstance(item, dict)
    ]
    approved_candidates = [
        candidate
        for candidate in candidates
        if candidate.status in {APPROVED, APPLIED}
    ]
    base_ids = {
        str(concept.get("concept_id") or "").strip()
        for concept in base_concepts
    }
    reinforcement_candidates = [
        candidate
        for candidate in approved_candidates
        if _is_reinforcement_candidate(candidate, base_ids)
    ]
    for candidate in reinforcement_candidates:
        _apply_reinforcement_candidate(base_concepts, candidate)
    candidate_concepts = _candidate_runtime_concepts(
        candidate
        for candidate in approved_candidates
        if candidate not in reinforcement_candidates
    )
    warnings = _validate_no_conflicts(base_concepts, candidate_concepts)

    merged_payload = {
        "schema_version": str(base_payload.get("schema_version") or "1.0"),
        "version": f"{base_payload.get('version') or 'base'}+approved-{utc_now_iso()}",
        "description": (
            "Active ontology manifest generated from base concepts and "
            "practitioner-approved ontology review candidates."
        ),
        "concepts": [*base_concepts, *candidate_concepts],
    }
    _write_manifest(target_path, merged_payload)
    return ManifestMergeResult(
        output_path=target_path,
        base_concept_count=len(base_concepts),
        merged_candidate_count=len(candidate_concepts) + len(reinforcement_candidates),
        total_concept_count=len(merged_payload["concepts"]),
        warnings=warnings,
    )
