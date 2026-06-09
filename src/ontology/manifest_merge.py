from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.graph.normalizer import normalize_name
from src.ontology.registry import ACTIVE_ONTOLOGY_MANIFEST, BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import APPLIED, APPROVED, OntologyCandidate, utc_now_iso


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
                    raise ValueError(f"alias conflict: {alias} maps to both {owner} and {concept_id}")
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
    candidate_concepts = _candidate_runtime_concepts(candidates)
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
        merged_candidate_count=len(candidate_concepts),
        total_concept_count=len(merged_payload["concepts"]),
        warnings=warnings,
    )
