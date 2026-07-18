"""Field-level approval and manifest integrity primitives.

The module intentionally stays domain-neutral.  It records which manifest
content was reviewed and lets callers fail closed when an active concept cannot
be traced to that reviewed content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, Mapping

from src.ontology.manifest_schema import (
    validate_active_provenance_schema,
    validate_ontology_manifest_schema,
)

if TYPE_CHECKING:
    from src.ontology.review_store import OntologyCandidate


IntegrityState = Literal["valid", "quarantined", "stale", "legacy_unverifiable"]


def canonical_json_hash(value: Any) -> str:
    """Return the SHA-256 hash of canonical JSON without dropping any keys."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_content_hash(payload: dict[str, Any]) -> str:
    """Hash content while excluding only generated manifest version text."""

    content = dict(payload)
    content.pop("version", None)
    return canonical_json_hash(content)


@dataclass(frozen=True)
class BaseManifestLock:
    schema_version: int
    manifest_content_hash: str
    concept_hashes: dict[str, str]
    source_commit: str
    review_record_id: str

    def validate(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("base lock schema_version must be 1")
        for field in (
            "manifest_content_hash",
            "source_commit",
            "review_record_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"base lock {field} is required")
        if not isinstance(self.concept_hashes, dict) or not self.concept_hashes:
            raise ValueError("base lock concept_hashes must not be empty")
        for concept_id, content_hash in self.concept_hashes.items():
            if (
                not isinstance(concept_id, str)
                or not concept_id.strip()
                or not isinstance(content_hash, str)
                or not content_hash.strip()
            ):
                raise ValueError("base lock concept_hashes must contain non-empty values")

    @classmethod
    def from_manifest(
        cls,
        payload: dict[str, Any],
        *,
        source_commit: str,
        review_record_id: str,
    ) -> "BaseManifestLock":
        validate_ontology_manifest_schema(payload)
        concepts = payload.get("concepts")
        if not isinstance(concepts, list):
            raise ValueError("manifest concepts must be a list")
        concept_hashes: dict[str, str] = {}
        for concept in concepts:
            if not isinstance(concept, dict):
                raise ValueError("manifest concepts must contain objects")
            concept_id = str(concept.get("concept_id") or "").strip()
            if not concept_id:
                raise ValueError("manifest concept_id is required")
            if concept_id in concept_hashes:
                raise ValueError(f"duplicate manifest concept_id: {concept_id}")
            concept_hashes[concept_id] = canonical_json_hash(concept)
        lock = cls(
            schema_version=1,
            manifest_content_hash=manifest_content_hash(payload),
            concept_hashes=concept_hashes,
            source_commit=str(source_commit).strip(),
            review_record_id=str(review_record_id).strip(),
        )
        lock.validate()
        return lock

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BaseManifestLock":
        if not isinstance(payload, dict):
            raise ValueError("base lock must be a JSON object")
        concept_hashes = payload.get("concept_hashes")
        if not isinstance(concept_hashes, dict):
            raise ValueError("base lock concept_hashes must be an object")
        for concept_id, content_hash in concept_hashes.items():
            if (
                not isinstance(concept_id, str)
                or not concept_id.strip()
                or not isinstance(content_hash, str)
                or not content_hash.strip()
            ):
                raise ValueError("base lock concept_hashes must contain non-empty string values")

        schema_version = payload.get("schema_version")
        if type(schema_version) is not int:
            raise ValueError("base lock schema_version must be 1")
        required_strings: dict[str, str] = {}
        for field in (
            "manifest_content_hash",
            "source_commit",
            "review_record_id",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"base lock {field} is required")
            required_strings[field] = value.strip()
        lock = cls(
            schema_version=schema_version,
            manifest_content_hash=required_strings["manifest_content_hash"],
            concept_hashes=dict(concept_hashes),
            source_commit=required_strings["source_commit"],
            review_record_id=required_strings["review_record_id"],
        )
        lock.validate()
        return lock

    @classmethod
    def load(cls, path: str | Path) -> "BaseManifestLock":
        with Path(path).open(encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise ValueError("base lock must be a JSON object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: str | Path) -> None:
        self.validate()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    concept_id: str
    path: str
    message: str


@dataclass(frozen=True)
class ManifestIntegrityReport:
    state: IntegrityState
    manifest_content_hash: str
    trusted_base_content_hash: str
    issues: tuple[IntegrityIssue, ...]
    quarantined_concept_ids: tuple[str, ...]

    def issue_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts


@dataclass(frozen=True)
class ManifestSemanticDiff:
    """One effective manifest change expressed using the approval path contract."""

    operation: "ApprovalOperation"
    concept_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "operation": self.operation.operation,
            "path": self.operation.path,
            "value_hash": self.operation.value_hash,
            "concept_id": self.concept_id,
        }


@dataclass(frozen=True)
class ActiveManifestAudit:
    """Audit result for an active manifest and its immutable provenance sidecar."""

    report: ManifestIntegrityReport
    active_content_hash: str
    provenance_content_hash: str
    concept_diffs: tuple[ManifestSemanticDiff, ...]
    approved_operations: tuple[ApprovalOperation, ...]


def provenance_content_hash(payload: dict[str, Any]) -> str:
    """Hash provenance content while excluding only its generated timestamp."""

    content = dict(payload)
    content.pop("generated_at", None)
    return canonical_json_hash(content)


@dataclass(frozen=True)
class ApprovalOperation:
    operation: Literal["add", "replace", "remove"]
    path: str
    value_hash: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalOperation":
        operation = str(payload.get("operation") or "").strip()
        if operation not in {"add", "replace", "remove"}:
            raise ValueError(f"invalid approval operation: {operation}")
        path = str(payload.get("path") or "").strip()
        value_hash = str(payload.get("value_hash") or "").strip()
        if not path or not value_hash:
            raise ValueError("approval operation path and value_hash are required")
        return cls(operation=operation, path=path, value_hash=value_hash)

    def to_dict(self) -> dict[str, str]:
        return {
            "operation": self.operation,
            "path": self.path,
            "value_hash": self.value_hash,
        }


@dataclass(frozen=True)
class ApprovedEvidence:
    chunk_id: str
    content_hash: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovedEvidence":
        chunk_id = str(payload.get("chunk_id") or "").strip()
        content_hash = str(payload.get("content_hash") or "").strip()
        if not chunk_id or not content_hash:
            raise ValueError("approved evidence chunk_id and content_hash are required")
        return cls(chunk_id=chunk_id, content_hash=content_hash)

    def to_dict(self) -> dict[str, str]:
        return {"chunk_id": self.chunk_id, "content_hash": self.content_hash}


@dataclass(frozen=True)
class ApprovalPatch:
    schema_version: int
    candidate_id: str
    candidate_payload_hash: str
    base_manifest_hash: str
    allowed_operations: tuple[ApprovalOperation, ...]
    approved_evidence: tuple[ApprovedEvidence, ...]
    reviewer: str
    reviewed_at: str

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ApprovalPatchError("approval patch schema_version must be 1")
        for field in (
            "candidate_id",
            "candidate_payload_hash",
            "base_manifest_hash",
            "reviewer",
            "reviewed_at",
        ):
            if not str(getattr(self, field) or "").strip():
                raise ApprovalPatchError(f"approval patch {field} is required")
        if not isinstance(self.allowed_operations, tuple):
            raise ApprovalPatchError("approval patch allowed_operations must be a tuple")
        if not self.allowed_operations:
            raise ApprovalPatchError("approval patch allowed_operations must not be empty")
        for operation in self.allowed_operations:
            if not isinstance(operation, ApprovalOperation):
                raise ApprovalPatchError(
                    "approval patch allowed_operations must contain approval operations"
                )
            try:
                ApprovalOperation.from_dict(operation.to_dict())
            except ValueError as exc:
                raise ApprovalPatchError(str(exc)) from exc
        if not isinstance(self.approved_evidence, tuple):
            raise ApprovalPatchError("approval patch approved_evidence must be a tuple")
        for evidence in self.approved_evidence:
            if not isinstance(evidence, ApprovedEvidence):
                raise ApprovalPatchError(
                    "approval patch approved_evidence must contain approved evidence"
                )
            try:
                ApprovedEvidence.from_dict(evidence.to_dict())
            except ValueError as exc:
                raise ApprovalPatchError(str(exc)) from exc

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalPatch":
        operations = payload.get("allowed_operations")
        evidence = payload.get("approved_evidence")
        if not isinstance(operations, list):
            raise ValueError("approval patch allowed_operations must be a list")
        if not isinstance(evidence, list):
            raise ValueError("approval patch approved_evidence must be a list")
        if any(not isinstance(row, dict) for row in operations):
            raise ValueError("approval patch allowed_operations must contain objects")
        if any(not isinstance(row, dict) for row in evidence):
            raise ValueError("approval patch approved_evidence must contain objects")
        patch = cls(
            schema_version=int(payload.get("schema_version") or 0),
            candidate_id=str(payload.get("candidate_id") or "").strip(),
            candidate_payload_hash=str(payload.get("candidate_payload_hash") or "").strip(),
            base_manifest_hash=str(payload.get("base_manifest_hash") or "").strip(),
            allowed_operations=tuple(
                ApprovalOperation.from_dict(row)
                for row in operations
            ),
            approved_evidence=tuple(
                ApprovedEvidence.from_dict(row)
                for row in evidence
            ),
            reviewer=str(payload.get("reviewer") or "").strip(),
            reviewed_at=str(payload.get("reviewed_at") or "").strip(),
        )
        patch.validate()
        return patch

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "candidate_payload_hash": self.candidate_payload_hash,
            "base_manifest_hash": self.base_manifest_hash,
            "allowed_operations": [operation.to_dict() for operation in self.allowed_operations],
            "approved_evidence": [evidence.to_dict() for evidence in self.approved_evidence],
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
        }

    def content_hash(self) -> str:
        return canonical_json_hash(self.to_dict())


class ApprovalPatchError(ValueError):
    """Raised when a candidate approval cannot be represented safely."""


class StaleApprovalPatchError(ApprovalPatchError):
    """Raised when a logged patch no longer matches its candidate payload."""


class LegacyApprovalUnverifiableError(ApprovalPatchError):
    """Raised when a legacy approved candidate lacks field-level provenance."""


def escape_json_pointer_segment(value: str) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _candidate_type(candidate: "OntologyCandidate") -> str:
    return str(candidate.properties.get("candidate_type") or "new_concept").strip()


def _target_concept_id(candidate: "OntologyCandidate") -> str:
    return str(candidate.properties.get("target_concept_id") or candidate.concept_id).strip()


def _policy_groups(
    candidate_type: str,
    approval_path_policy: Mapping[str, tuple[str, ...] | list[str]] | None,
) -> tuple[str, ...]:
    if approval_path_policy is None:
        from src.ontology.policy import load_review_policy

        approval_path_policy = load_review_policy().approval_path_policy
    values = approval_path_policy.get(candidate_type, ())
    return tuple(str(value).strip() for value in values if str(value).strip())


def _concept_ids(manifest: dict[str, Any]) -> set[str]:
    concepts = manifest.get("concepts")
    if not isinstance(concepts, list):
        raise ApprovalPatchError("base manifest concepts must be a list")
    return {
        str(concept.get("concept_id") or "").strip()
        for concept in concepts
        if isinstance(concept, dict) and str(concept.get("concept_id") or "").strip()
    }


def _operation(
    operation: Literal["add", "replace", "remove"],
    path: str,
    value: Any,
) -> ApprovalOperation:
    return ApprovalOperation(operation=operation, path=path, value_hash=canonical_json_hash(value))


def _string_list_operations(
    *,
    prefix: str,
    values: Any,
) -> list[tuple[ApprovalOperation, str]]:
    if not isinstance(values, list):
        return []
    operations: list[tuple[ApprovalOperation, str]] = []
    for value in values:
        text = str(value).strip()
        if text:
            operations.append(
                (_operation("add", f"{prefix}/{canonical_json_hash(text)}", text), text)
            )
    return operations


def project_candidate_operation_values(
    candidate: "OntologyCandidate",
    base_manifest: dict[str, Any],
    *,
    approval_path_policy: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> dict[str, tuple[ApprovalOperation, Any]]:
    """Project policy-authorized candidate fields into semantic operations."""

    candidate_type = _candidate_type(candidate)
    groups = _policy_groups(candidate_type, approval_path_policy)
    if not groups:
        raise ApprovalPatchError(f"candidate type has no approval path policy: {candidate_type}")
    target_id = _target_concept_id(candidate)
    if not target_id:
        raise ApprovalPatchError("candidate target concept_id is required")
    existing = target_id in _concept_ids(base_manifest)
    if candidate_type != "new_concept" and not existing:
        raise ApprovalPatchError(f"reinforcement target concept is not present in base: {target_id}")

    prefix = f"/concepts/{escape_json_pointer_segment(target_id)}"
    scalar_operation: Literal["add", "replace"] = "replace" if existing else "add"
    projected: dict[str, tuple[ApprovalOperation, Any]] = {}

    def add(operation: ApprovalOperation, value: Any) -> None:
        projected[operation.path] = (operation, value)

    if "canonical_name" in groups and candidate.canonical_name:
        add(_operation(scalar_operation, f"{prefix}/canonical_name", candidate.canonical_name), candidate.canonical_name)
    if "node_type" in groups and candidate.node_type:
        add(_operation(scalar_operation, f"{prefix}/node_type", candidate.node_type), candidate.node_type)
    if "aliases" in groups:
        for operation, value in _string_list_operations(
            prefix=f"{prefix}/aliases",
            values=candidate.aliases,
        ):
            add(operation, value)
    if "candidate_aliases" in groups:
        for operation, value in _string_list_operations(
            prefix=f"{prefix}/candidate_aliases",
            values=candidate.candidate_aliases,
        ):
            add(operation, value)
    if "evidence_tags" in groups:
        for operation, value in _string_list_operations(
            prefix=f"{prefix}/evidence_tags",
            values=candidate.evidence_tags,
        ):
            add(operation, value)
    if "planner" in groups:
        for key, values in sorted(candidate.planner.items()):
            for operation, value in _string_list_operations(
                prefix=f"{prefix}/planner/{escape_json_pointer_segment(key)}",
                values=values,
            ):
                add(operation, value)
    if "retrieval.expansion_rules" in groups:
        for rule in candidate.retrieval.get("expansion_rules", []):
            if isinstance(rule, dict):
                operation = _operation(
                    "add",
                    f"{prefix}/retrieval/expansion_rules/{canonical_json_hash(rule)}",
                    rule,
                )
                add(operation, rule)
    if "retrieval.lexical_priority_terms" in groups:
        for operation, value in _string_list_operations(
            prefix=f"{prefix}/retrieval/lexical_priority_terms",
            values=candidate.retrieval.get("lexical_priority_terms"),
        ):
            add(operation, value)
    if "runtime_properties" in groups:
        for key, value in sorted(candidate.runtime_properties.items()):
            operation = _operation(
                scalar_operation,
                f"{prefix}/properties/{escape_json_pointer_segment(key)}",
                value,
            )
            add(operation, value)
    return dict(sorted(projected.items()))


def project_candidate_operations(
    candidate: "OntologyCandidate",
    base_manifest: dict[str, Any],
    *,
    approval_path_policy: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> tuple[ApprovalOperation, ...]:
    return tuple(
        operation
        for operation, _value in project_candidate_operation_values(
            candidate,
            base_manifest,
            approval_path_policy=approval_path_policy,
        ).values()
    )


_OPERATION_FIELD_LABELS = {
    "canonical_name": "대표명",
    "node_type": "개념 유형",
    "aliases": "기존 별칭",
    "candidate_aliases": "검색 후보 표현",
    "evidence_tags": "근거 태그",
    "planner": "검토 안내",
    "retrieval": "검색 확장 규칙",
    "properties": "실행 속성",
}


def _operation_field_label(path: str) -> str:
    segments = [segment for segment in str(path).split("/") if segment]
    field = segments[2] if len(segments) > 2 else ""
    return _OPERATION_FIELD_LABELS.get(field, "승인 변경 항목")


def _bounded_value_preview(path: str, value: Any, *, limit: int = 160) -> str:
    segments = [segment for segment in str(path).split("/") if segment]
    if len(segments) > 2 and segments[2] == "properties":
        return "내부 실행 속성 값은 이 화면에서 표시하지 않습니다."
    if isinstance(value, str):
        preview = value
    else:
        preview = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return preview if len(preview) <= limit else f"{preview[: limit - 1]}…"


def project_candidate_operation_previews(
    candidate: "OntologyCandidate",
    base_manifest: dict[str, Any],
    *,
    approval_path_policy: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> list[dict[str, str]]:
    """Return bounded, field-level choices without exposing raw control payloads."""

    projected = project_candidate_operation_values(
        candidate,
        base_manifest,
        approval_path_policy=approval_path_policy,
    )
    return [
        {
            "operation": operation.operation,
            "path": operation.path,
            "field_label": _operation_field_label(operation.path),
            "value_preview": _bounded_value_preview(operation.path, value),
            "value_hash": operation.value_hash,
        }
        for operation, value in projected.values()
    ]


def build_approval_patch(
    candidate: "OntologyCandidate",
    base_manifest: dict[str, Any],
    *,
    approved_paths: list[str] | tuple[str, ...],
    reviewer: str,
    reviewed_at: str,
    approval_path_policy: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> ApprovalPatch:
    available = project_candidate_operation_values(
        candidate,
        base_manifest,
        approval_path_policy=approval_path_policy,
    )
    selected_paths = tuple(dict.fromkeys(str(path).strip() for path in approved_paths if str(path).strip()))
    if not selected_paths:
        raise ApprovalPatchError("approved_paths are required for approve decisions")
    unavailable = [path for path in selected_paths if path not in available]
    if unavailable:
        raise ApprovalPatchError(f"approved path is not available: {unavailable[0]}")
    selected = tuple(available[path][0] for path in sorted(selected_paths))
    evidence: list[ApprovedEvidence] = []
    for row in candidate.source_evidence:
        chunk_id = str(row.get("chunk_id") or "").strip()
        if chunk_id:
            evidence.append(ApprovedEvidence(chunk_id=chunk_id, content_hash=canonical_json_hash(row)))
    return ApprovalPatch(
        schema_version=1,
        candidate_id=candidate.candidate_id,
        candidate_payload_hash=candidate.approval_payload_hash(),
        base_manifest_hash=manifest_content_hash(base_manifest),
        allowed_operations=selected,
        approved_evidence=tuple(evidence),
        reviewer=str(reviewer),
        reviewed_at=str(reviewed_at),
    )


def build_base_manifest_lock(
    payload: dict[str, Any],
    *,
    source_commit: str,
    review_record_id: str,
) -> BaseManifestLock:
    return BaseManifestLock.from_manifest(
        payload,
        source_commit=source_commit,
        review_record_id=review_record_id,
    )


def build_trusted_base_projection(
    base_payload: dict[str, Any],
    lock: BaseManifestLock,
) -> tuple[dict[str, Any], ManifestIntegrityReport]:
    """Return only base concepts whose full payload matches the reviewed lock."""

    validate_ontology_manifest_schema(base_payload)
    lock.validate()
    concepts = base_payload.get("concepts")
    if not isinstance(concepts, list):
        raise ValueError("manifest concepts must be a list")

    matching: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    issues: list[IntegrityIssue] = []
    quarantined: list[str] = []

    for concept in concepts:
        if not isinstance(concept, dict):
            raise ValueError("manifest concepts must contain objects")
        concept_id = str(concept.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError("manifest concept_id is required")
        if concept_id in observed_ids:
            raise ValueError(f"duplicate manifest concept_id: {concept_id}")
        observed_ids.add(concept_id)

        expected_hash = lock.concept_hashes.get(concept_id)
        actual_hash = canonical_json_hash(concept)
        if expected_hash is None:
            issues.append(
                IntegrityIssue(
                    code="UNTRUSTED_BASE_CONCEPT",
                    concept_id=concept_id,
                    path=f"/concepts/{concept_id}",
                    message="concept is absent from the reviewed base lock",
                )
            )
            quarantined.append(concept_id)
            continue
        if expected_hash != actual_hash:
            issues.append(
                IntegrityIssue(
                    code="BASE_CONCEPT_HASH_MISMATCH",
                    concept_id=concept_id,
                    path=f"/concepts/{concept_id}",
                    message="concept content no longer matches the reviewed base lock",
                )
            )
            quarantined.append(concept_id)
            continue
        matching.append(dict(concept))

    for concept_id in sorted(set(lock.concept_hashes) - observed_ids):
        issues.append(
            IntegrityIssue(
                code="LOCKED_CONCEPT_MISSING",
                concept_id=concept_id,
                path=f"/concepts/{concept_id}",
                message="reviewed base concept is missing from the current manifest",
            )
        )
        quarantined.append(concept_id)

    projection = dict(base_payload)
    projection["concepts"] = matching
    projection_hash = manifest_content_hash(projection)
    locked_concepts_match = {
        str(concept.get("concept_id") or "").strip()
        for concept in matching
    } == set(lock.concept_hashes)
    if locked_concepts_match and projection_hash != lock.manifest_content_hash:
        issues.append(
            IntegrityIssue(
                code="BASE_MANIFEST_HASH_MISMATCH",
                concept_id="",
                path="/manifest_content_hash",
                message="trusted base projection does not match the reviewed manifest lock",
            )
        )
    state: IntegrityState = (
        "stale"
        if any(issue.code == "BASE_MANIFEST_HASH_MISMATCH" for issue in issues)
        else "valid"
        if not issues
        else "quarantined"
    )
    report = ManifestIntegrityReport(
        state=state,
        manifest_content_hash=projection_hash,
        trusted_base_content_hash=lock.manifest_content_hash,
        issues=tuple(issues),
        quarantined_concept_ids=tuple(dict.fromkeys(quarantined)),
    )
    return projection, report


def _manifest_concept_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    concepts = payload.get("concepts")
    if not isinstance(concepts, list):
        raise ValueError("manifest concepts must be a list")
    concept_map: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        if not isinstance(concept, dict):
            raise ValueError("manifest concepts must contain objects")
        concept_id = str(concept.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError("manifest concept_id is required")
        if concept_id in concept_map:
            raise ValueError(f"duplicate manifest concept_id: {concept_id}")
        concept_map[concept_id] = concept
    return concept_map


def _list_diffs(
    *,
    concept_id: str,
    prefix: str,
    before: Any,
    after: Any,
) -> list[ManifestSemanticDiff]:
    before_values = list(before) if isinstance(before, list) else []
    after_values = list(after) if isinstance(after, list) else []
    differences: list[ManifestSemanticDiff] = []
    for value in after_values:
        if value not in before_values:
            operation = _operation("add", f"{prefix}/{canonical_json_hash(value)}", value)
            differences.append(ManifestSemanticDiff(operation=operation, concept_id=concept_id))
    for value in before_values:
        if value not in after_values:
            operation = _operation("remove", f"{prefix}/{canonical_json_hash(value)}", value)
            differences.append(ManifestSemanticDiff(operation=operation, concept_id=concept_id))
    return differences


def _scalar_diff(
    *,
    concept_id: str,
    path: str,
    before: Any,
    after: Any,
) -> ManifestSemanticDiff | None:
    if before == after:
        return None
    if after is None:
        operation = _operation("remove", path, before)
    elif before is None:
        operation = _operation("add", path, after)
    else:
        operation = _operation("replace", path, after)
    return ManifestSemanticDiff(operation=operation, concept_id=concept_id)


def manifest_semantic_diffs(
    trusted_base: dict[str, Any],
    active_payload: dict[str, Any],
) -> tuple[ManifestSemanticDiff, ...]:
    """Return effective supported-field changes from trusted base to active payload.

    The function intentionally only understands the same generic fields accepted
    by field-level approval patches. Any unsupported field change is represented
    by an explicit synthetic path, which can never match a valid approval patch
    and therefore fails closed in the audit.
    """

    base_by_id = _manifest_concept_map(trusted_base)
    active_by_id = _manifest_concept_map(active_payload)
    differences: list[ManifestSemanticDiff] = []
    supported_top_level = {
        "concept_id",
        "canonical_name",
        "node_type",
        "aliases",
        "candidate_aliases",
        "evidence_tags",
        "planner",
        "retrieval",
        "properties",
    }

    for concept_id in sorted(set(base_by_id) | set(active_by_id)):
        before = base_by_id.get(concept_id)
        after = active_by_id.get(concept_id)
        prefix = f"/concepts/{escape_json_pointer_segment(concept_id)}"
        if before is None:
            before = {"concept_id": concept_id}
        if after is None:
            operation = _operation("remove", prefix, before)
            differences.append(ManifestSemanticDiff(operation=operation, concept_id=concept_id))
            continue

        for field in ("canonical_name", "node_type"):
            difference = _scalar_diff(
                concept_id=concept_id,
                path=f"{prefix}/{field}",
                before=before.get(field),
                after=after.get(field),
            )
            if difference is not None:
                differences.append(difference)

        for field in ("aliases", "candidate_aliases", "evidence_tags"):
            differences.extend(
                _list_diffs(
                    concept_id=concept_id,
                    prefix=f"{prefix}/{field}",
                    before=before.get(field),
                    after=after.get(field),
                )
            )

        before_planner = before.get("planner") if isinstance(before.get("planner"), dict) else {}
        after_planner = after.get("planner") if isinstance(after.get("planner"), dict) else {}
        for key in sorted(set(before_planner) | set(after_planner)):
            differences.extend(
                _list_diffs(
                    concept_id=concept_id,
                    prefix=f"{prefix}/planner/{escape_json_pointer_segment(key)}",
                    before=before_planner.get(key),
                    after=after_planner.get(key),
                )
            )

        before_retrieval = before.get("retrieval") if isinstance(before.get("retrieval"), dict) else {}
        after_retrieval = after.get("retrieval") if isinstance(after.get("retrieval"), dict) else {}
        for key in sorted(set(before_retrieval) | set(after_retrieval)):
            differences.extend(
                _list_diffs(
                    concept_id=concept_id,
                    prefix=f"{prefix}/retrieval/{escape_json_pointer_segment(key)}",
                    before=before_retrieval.get(key),
                    after=after_retrieval.get(key),
                )
            )

        before_properties = before.get("properties") if isinstance(before.get("properties"), dict) else {}
        after_properties = after.get("properties") if isinstance(after.get("properties"), dict) else {}
        for key in sorted(set(before_properties) | set(after_properties)):
            difference = _scalar_diff(
                concept_id=concept_id,
                path=f"{prefix}/properties/{escape_json_pointer_segment(key)}",
                before=before_properties.get(key),
                after=after_properties.get(key),
            )
            if difference is not None:
                differences.append(difference)

        for field in sorted((set(before) | set(after)) - supported_top_level):
            difference = _scalar_diff(
                concept_id=concept_id,
                path=f"{prefix}/__unsupported__/{escape_json_pointer_segment(field)}",
                before=before.get(field),
                after=after.get(field),
            )
            if difference is not None:
                differences.append(difference)

    return tuple(sorted(differences, key=lambda item: (item.concept_id, item.operation.path)))


def _provenance_operations(payload: dict[str, Any]) -> tuple[ApprovalOperation, ...]:
    rows = payload.get("applied_operations")
    if not isinstance(rows, list):
        raise ValueError("provenance applied_operations must be a list")
    operations: list[ApprovalOperation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("provenance applied_operations must contain objects")
        operations.append(ApprovalOperation.from_dict(row))
    return tuple(operations)


def audit_active_manifest(
    base_payload: dict[str, Any],
    base_lock: BaseManifestLock,
    active_payload: dict[str, Any],
    provenance_payload: dict[str, Any],
) -> ActiveManifestAudit:
    """Audit active manifest deltas against the locked base and provenance."""

    validate_ontology_manifest_schema(active_payload)
    validate_active_provenance_schema(provenance_payload)
    base_lock.validate()
    trusted_base, base_report = build_trusted_base_projection(base_payload, base_lock)
    issues = list(base_report.issues)
    quarantined = list(base_report.quarantined_concept_ids)
    for field in ("schema_version", "description"):
        if active_payload.get(field) != trusted_base.get(field):
            issues.append(
                IntegrityIssue(
                    code="UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA",
                    concept_id="",
                    path=f"/{field}",
                    message="active manifest metadata differs from the trusted base without an approval operation",
                )
            )
    actual_active_hash = manifest_content_hash(active_payload)
    provenance_active_hash = str(provenance_payload.get("active_content_hash") or "").strip()
    provenance_base_hash = str(provenance_payload.get("trusted_base_content_hash") or "").strip()
    provenance_lock = provenance_payload.get("base_lock")

    if provenance_active_hash != actual_active_hash:
        issues.append(
            IntegrityIssue(
                code="ACTIVE_CONTENT_HASH_MISMATCH",
                concept_id="",
                path="/active_content_hash",
                message="active manifest content hash does not match provenance",
            )
        )
    if provenance_base_hash != base_report.trusted_base_content_hash:
        issues.append(
            IntegrityIssue(
                code="TRUSTED_BASE_HASH_MISMATCH",
                concept_id="",
                path="/trusted_base_content_hash",
                message="provenance trusted base hash does not match the reviewed lock",
            )
        )
    try:
        parsed_provenance_lock = BaseManifestLock.from_dict(provenance_lock)
    except ValueError:
        parsed_provenance_lock = None
    if parsed_provenance_lock is None or parsed_provenance_lock.to_dict() != base_lock.to_dict():
        issues.append(
            IntegrityIssue(
                code="BASE_LOCK_MISMATCH",
                concept_id="",
                path="/base_lock",
                message="provenance base lock does not match the reviewed lock",
            )
        )

    approved_operations = _provenance_operations(provenance_payload)
    approved_keys = {
        (operation.operation, operation.path, operation.value_hash)
        for operation in approved_operations
    }
    concept_diffs = manifest_semantic_diffs(trusted_base, active_payload)
    actual_keys = {
        (difference.operation.operation, difference.operation.path, difference.operation.value_hash)
        for difference in concept_diffs
    }
    for difference in concept_diffs:
        key = (
            difference.operation.operation,
            difference.operation.path,
            difference.operation.value_hash,
        )
        if key in approved_keys:
            continue
        issues.append(
            IntegrityIssue(
                code="LEGACY_UNVERIFIABLE_ACTIVE_DELTA",
                concept_id=difference.concept_id,
                path=difference.operation.path,
                message="active manifest delta has no matching field-level approval patch",
            )
        )
        if difference.concept_id:
            quarantined.append(difference.concept_id)
    for operation in approved_operations:
        key = (operation.operation, operation.path, operation.value_hash)
        if key in actual_keys:
            continue
        issues.append(
            IntegrityIssue(
                code="STALE_APPROVAL_OPERATION",
                concept_id="",
                path=operation.path,
                message="approved operation is absent from the active manifest",
            )
        )

    stale_codes = {
        "ACTIVE_CONTENT_HASH_MISMATCH",
        "TRUSTED_BASE_HASH_MISMATCH",
        "BASE_LOCK_MISMATCH",
        "BASE_MANIFEST_HASH_MISMATCH",
        "UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA",
        "STALE_APPROVAL_OPERATION",
        "LOCKED_CONCEPT_MISSING",
    }
    legacy_codes = {"LEGACY_UNVERIFIABLE_ACTIVE_DELTA"}
    issue_codes = {issue.code for issue in issues}
    if issue_codes.intersection(stale_codes):
        state: IntegrityState = "stale"
    elif issue_codes.intersection(legacy_codes):
        state = "legacy_unverifiable"
    elif issues:
        state = "quarantined"
    else:
        state = "valid"
    report = ManifestIntegrityReport(
        state=state,
        manifest_content_hash=actual_active_hash,
        trusted_base_content_hash=base_report.trusted_base_content_hash,
        issues=tuple(issues),
        quarantined_concept_ids=tuple(dict.fromkeys(quarantined)),
    )
    return ActiveManifestAudit(
        report=report,
        active_content_hash=actual_active_hash,
        provenance_content_hash=provenance_content_hash(provenance_payload),
        concept_diffs=concept_diffs,
        approved_operations=approved_operations,
    )
