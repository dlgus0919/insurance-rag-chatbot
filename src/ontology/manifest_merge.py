from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.graph.normalizer import normalize_name
from src.ontology.approval_integrity import (
    ApprovalOperation,
    ApprovalPatch,
    ApprovalPatchError,
    ApprovedEvidence,
    BaseManifestLock,
    LegacyApprovalUnverifiableError,
    ManifestIntegrityReport,
    StaleApprovalPatchError,
    build_trusted_base_projection,
    canonical_json_hash,
    manifest_content_hash,
    project_candidate_operation_values,
)
from src.ontology.candidate_quality import find_manifest_candidate_alias_issues
from src.ontology.manifest_schema import (
    validate_active_provenance_schema,
    validate_ontology_manifest_schema,
)
from src.ontology.registry import (
    ACTIVE_ONTOLOGY_MANIFEST,
    ACTIVE_ONTOLOGY_PROVENANCE,
    BASE_ONTOLOGY_LOCK,
    BASE_ONTOLOGY_MANIFEST,
)
from src.ontology.review_store import APPLIED, APPROVED, OntologyCandidate, utc_now_iso


@dataclass(frozen=True)
class ManifestMergeResult:
    output_path: Path
    base_concept_count: int
    merged_candidate_count: int
    total_concept_count: int
    provenance_path: Path | None = None
    active_content_hash: str = ""
    trusted_base_content_hash: str = ""
    applied_operation_count: int = 0
    quarantined_concept_ids: tuple[str, ...] = field(default_factory=tuple)
    warnings: list[str] = field(default_factory=list)


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid manifest object: {path}")
    validate_ontology_manifest_schema(payload)
    return payload


def validate_manifest_schema(payload: dict[str, Any]) -> None:
    validate_ontology_manifest_schema(payload)


def _validate_manifest_schema(payload: dict[str, Any]) -> None:
    """Backward-compatible private alias for internal merge validation."""

    validate_manifest_schema(payload)


def _write_json_temp(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _write_manifest_and_provenance(
    *,
    output_path: Path,
    manifest: dict[str, Any],
    provenance_path: Path,
    provenance: dict[str, Any],
) -> None:
    provenance_temp = _write_json_temp(provenance_path, provenance)
    manifest_temp = _write_json_temp(output_path, manifest)
    try:
        # A runtime audit fails closed while only the provenance sidecar has been
        # replaced. Once the active manifest is replaced, their hashes agree.
        os.replace(provenance_temp, provenance_path)
        os.replace(manifest_temp, output_path)
    finally:
        provenance_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in values:
        values.append(value)


def _unescape_json_pointer_segment(value: str) -> str:
    return str(value).replace("~1", "/").replace("~0", "~")


def _concept_by_id(concepts: dict[str, dict[str, Any]], concept_id: str) -> dict[str, Any]:
    return concepts.setdefault(concept_id, {"concept_id": concept_id})


def _apply_list_operation(target: dict[str, Any], key: str, operation: ApprovalOperation, value: Any) -> None:
    values = _as_list(target.get(key))
    if operation.operation == "remove":
        target[key] = [item for item in values if item != value]
        return
    _append_unique(values, deepcopy(value))
    target[key] = values


def _apply_operation(
    concepts: dict[str, dict[str, Any]],
    operation: ApprovalOperation,
    value: Any,
) -> None:
    segments = [segment for segment in operation.path.split("/") if segment]
    if len(segments) < 3 or segments[0] != "concepts":
        raise ApprovalPatchError(f"unsupported approval operation path: {operation.path}")
    concept_id = _unescape_json_pointer_segment(segments[1])
    field = segments[2]
    target = _concept_by_id(concepts, concept_id)

    if field in {"canonical_name", "node_type"} and len(segments) == 3:
        if operation.operation == "remove":
            target.pop(field, None)
        else:
            target[field] = deepcopy(value)
        return
    if field in {"aliases", "candidate_aliases", "evidence_tags"} and len(segments) == 4:
        _apply_list_operation(target, field, operation, value)
        return
    if field == "planner" and len(segments) == 5:
        planner_key = _unescape_json_pointer_segment(segments[3])
        planner = dict(target.get("planner") or {})
        _apply_list_operation(planner, planner_key, operation, value)
        if planner:
            target["planner"] = planner
        else:
            target.pop("planner", None)
        return
    if (
        field == "retrieval"
        and len(segments) == 5
        and segments[3] in {"expansion_rules", "lexical_priority_terms"}
    ):
        retrieval = dict(target.get("retrieval") or {})
        _apply_list_operation(retrieval, segments[3], operation, value)
        if retrieval:
            target["retrieval"] = retrieval
        else:
            target.pop("retrieval", None)
        return
    if field == "properties" and len(segments) == 4:
        property_key = _unescape_json_pointer_segment(segments[3])
        properties = dict(target.get("properties") or {})
        if operation.operation == "remove":
            properties.pop(property_key, None)
        else:
            properties[property_key] = deepcopy(value)
        if properties:
            target["properties"] = properties
        else:
            target.pop("properties", None)
        return
    raise ApprovalPatchError(f"unsupported approval operation path: {operation.path}")


def _candidate_evidence(candidate: OntologyCandidate) -> tuple[ApprovedEvidence, ...]:
    evidence: list[ApprovedEvidence] = []
    for row in candidate.source_evidence:
        chunk_id = str(row.get("chunk_id") or "").strip()
        if chunk_id:
            evidence.append(
                ApprovedEvidence(chunk_id=chunk_id, content_hash=canonical_json_hash(row))
            )
    return tuple(evidence)


def _validated_patch_values(
    candidate: OntologyCandidate,
    patch: ApprovalPatch,
    base_payload: dict[str, Any],
    trusted_base_content_hash: str,
) -> dict[str, tuple[ApprovalOperation, Any]]:
    patch.validate()
    if patch.candidate_id != candidate.candidate_id:
        raise StaleApprovalPatchError(
            f"approval patch candidate id mismatch: {candidate.candidate_id}"
        )
    if patch.candidate_payload_hash != candidate.approval_payload_hash():
        raise StaleApprovalPatchError(
            f"candidate approval payload is stale: {candidate.candidate_id}"
        )
    if patch.base_manifest_hash != trusted_base_content_hash:
        raise StaleApprovalPatchError(
            f"approval patch base manifest is stale: {candidate.candidate_id}"
        )
    if patch.approved_evidence != _candidate_evidence(candidate):
        raise StaleApprovalPatchError(
            f"approval patch evidence is stale: {candidate.candidate_id}"
        )
    if not patch.allowed_operations:
        raise ApprovalPatchError(
            f"approval patch has no approved operations: {candidate.candidate_id}"
        )

    projected = project_candidate_operation_values(candidate, base_payload)
    selected: dict[str, tuple[ApprovalOperation, Any]] = {}
    seen_paths: set[str] = set()
    for operation in patch.allowed_operations:
        if operation.path in seen_paths:
            raise ApprovalPatchError(
                f"duplicate approval operation path: {candidate.candidate_id}: {operation.path}"
            )
        seen_paths.add(operation.path)
        expected = projected.get(operation.path)
        if expected is None or expected[0] != operation:
            raise StaleApprovalPatchError(
                f"approval patch operation is stale: {candidate.candidate_id}: {operation.path}"
            )
        selected[operation.path] = expected
    return dict(sorted(selected.items()))


def _validate_concepts(
    concepts: list[dict[str, Any]],
    *,
    trusted_base_ids: set[str],
) -> list[str]:
    warnings: list[str] = []
    concept_ids: set[str] = set()
    aliases: dict[str, str] = {}
    reported_base_conflicts: set[tuple[str, str, str]] = set()

    for concept in concepts:
        concept_id = str(concept.get("concept_id") or "").strip()
        canonical = str(concept.get("canonical_name") or "").strip()
        if not concept_id or not canonical:
            raise ValueError("concept_id and canonical_name are required")
        if concept_id in concept_ids:
            raise ValueError(f"duplicated concept_id: {concept_id}")
        concept_ids.add(concept_id)
        raw_aliases = concept.get("aliases") if isinstance(concept.get("aliases"), list) else []
        for alias in [canonical, *raw_aliases]:
            normalized = normalize_name(str(alias))
            if not normalized:
                continue
            owner = aliases.get(normalized)
            if owner and owner != concept_id:
                if owner in trusted_base_ids and concept_id in trusted_base_ids:
                    conflict = (str(alias), owner, concept_id)
                    if conflict not in reported_base_conflicts:
                        warnings.append(
                            f"base manifest existing alias conflict: {alias} maps to both {owner} and {concept_id}"
                        )
                        reported_base_conflicts.add(conflict)
                    continue
                raise ValueError(f"alias conflict: {alias} maps to both {owner} and {concept_id}")
            aliases[normalized] = concept_id

    quality_issues = find_manifest_candidate_alias_issues(concepts)
    blocking = [issue for issue in quality_issues if issue.severity == "error"]
    if blocking:
        messages = "; ".join(issue.message for issue in blocking[:10])
        if len(blocking) > 10:
            messages = f"{messages}; ... {len(blocking) - 10} more"
        raise ValueError(f"candidate_alias quality conflict: {messages}")
    return warnings


def _provenance_payload(
    *,
    base_lock: BaseManifestLock,
    integrity_report: ManifestIntegrityReport,
    active_content_hash: str,
    applied: list[tuple[OntologyCandidate, ApprovalPatch, ApprovalOperation]],
) -> dict[str, Any]:
    operations = [
        {
            "candidate_id": candidate.candidate_id,
            "candidate_payload_hash": patch.candidate_payload_hash,
            "approval_patch_hash": patch.content_hash(),
            **operation.to_dict(),
        }
        for candidate, patch, operation in applied
    ]
    return {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "base_lock": base_lock.to_dict(),
        "trusted_base_content_hash": integrity_report.trusted_base_content_hash,
        "active_content_hash": active_content_hash,
        "quarantined_concept_ids": list(integrity_report.quarantined_concept_ids),
        "integrity_issues": [asdict(issue) for issue in integrity_report.issues],
        "applied_operations": operations,
    }


def merge_approved_candidates(
    candidates: Iterable[OntologyCandidate],
    *,
    approval_patches: Mapping[str, ApprovalPatch],
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
    base_lock_path: str | Path = BASE_ONTOLOGY_LOCK,
    output_path: str | Path = ACTIVE_ONTOLOGY_MANIFEST,
    provenance_path: str | Path = ACTIVE_ONTOLOGY_PROVENANCE,
) -> ManifestMergeResult:
    """Build an active manifest from a locked base and explicit approval patches."""

    base_path = Path(base_manifest_path)
    target_path = Path(output_path)
    target_provenance_path = Path(provenance_path)
    base_payload = _load_manifest(base_path)
    base_lock = BaseManifestLock.load(base_lock_path)
    trusted_base, integrity_report = build_trusted_base_projection(base_payload, base_lock)
    trusted_base_hash = manifest_content_hash(trusted_base)
    if trusted_base_hash != base_lock.manifest_content_hash:
        raise StaleApprovalPatchError("trusted base manifest does not match the reviewed lock")

    approved_candidates = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.status in {APPROVED, APPLIED}
        ),
        key=lambda candidate: candidate.candidate_id,
    )
    selected_operations: list[tuple[OntologyCandidate, ApprovalPatch, ApprovalOperation, Any]] = []
    for candidate in approved_candidates:
        patch = approval_patches.get(candidate.candidate_id)
        if patch is None:
            raise LegacyApprovalUnverifiableError(
                f"legacy approved candidate has no field-level patch: {candidate.candidate_id}"
            )
        for operation, value in _validated_patch_values(
            candidate,
            patch,
            trusted_base,
            trusted_base_hash,
        ).values():
            selected_operations.append((candidate, patch, operation, value))

    concept_map: dict[str, dict[str, Any]] = {}
    for concept in trusted_base.get("concepts", []):
        if not isinstance(concept, dict):
            raise ValueError("trusted base concepts must contain objects")
        concept_id = str(concept.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError("trusted base concept_id is required")
        concept_map[concept_id] = deepcopy(concept)

    applied: list[tuple[OntologyCandidate, ApprovalPatch, ApprovalOperation]] = []
    for candidate, patch, operation, value in sorted(
        selected_operations,
        key=lambda item: (item[0].candidate_id, item[2].path),
    ):
        _apply_operation(concept_map, operation, value)
        applied.append((candidate, patch, operation))

    concepts = list(concept_map.values())
    trusted_base_ids = {
        str(concept.get("concept_id") or "").strip()
        for concept in trusted_base.get("concepts", [])
        if isinstance(concept, dict)
    }
    warnings = _validate_concepts(concepts, trusted_base_ids=trusted_base_ids)
    merged_payload = {
        "schema_version": str(trusted_base.get("schema_version") or "1.0"),
        "version": f"{trusted_base.get('version') or 'base'}+approved-{utc_now_iso()}",
        "description": str(trusted_base.get("description") or ""),
        "concepts": concepts,
    }
    _validate_manifest_schema(merged_payload)
    active_content_hash = manifest_content_hash(merged_payload)
    provenance = _provenance_payload(
        base_lock=base_lock,
        integrity_report=integrity_report,
        active_content_hash=active_content_hash,
        applied=applied,
    )
    validate_active_provenance_schema(provenance)
    _write_manifest_and_provenance(
        output_path=target_path,
        manifest=merged_payload,
        provenance_path=target_provenance_path,
        provenance=provenance,
    )
    return ManifestMergeResult(
        output_path=target_path,
        provenance_path=target_provenance_path,
        base_concept_count=len(trusted_base_ids),
        merged_candidate_count=len({candidate.candidate_id for candidate, _, _ in applied}),
        total_concept_count=len(concepts),
        active_content_hash=active_content_hash,
        trusted_base_content_hash=trusted_base_hash,
        applied_operation_count=len(applied),
        quarantined_concept_ids=integrity_report.quarantined_concept_ids,
        warnings=warnings,
    )
