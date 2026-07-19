from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.config import SAFE_BASELINE_RUNTIME_ROOT_ENV

from src.graph.normalizer import normalize_name
from src.ontology.approval_integrity import (
    BaseManifestLock,
    IntegrityIssue,
    ManifestIntegrityReport,
    audit_active_manifest,
    build_trusted_base_projection,
    manifest_content_hash,
)
from src.ontology.manifest_schema import (
    validate_active_provenance_schema,
    validate_ontology_manifest_schema,
)


ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "data" / "ontology"
BASE_ONTOLOGY_MANIFEST = ONTOLOGY_DIR / "concepts.json"
ACTIVE_ONTOLOGY_MANIFEST = ONTOLOGY_DIR / "concepts.active.json"
BASE_ONTOLOGY_LOCK = ONTOLOGY_DIR / "policies" / "base_manifest.lock.json"
ACTIVE_ONTOLOGY_PROVENANCE = ONTOLOGY_DIR / "concepts.active.provenance.json"
DEFAULT_ONTOLOGY_MANIFEST = BASE_ONTOLOGY_MANIFEST
SAFE_BASELINE_RUNTIME_ROOT_ENV = "INSURANCE_SAFE_BASELINE_RUNTIME_ROOT"
NODE_TYPE_PREFIXES = {
    "ComplicationConcept": "comp",
    "ClaimCondition": "cond",
    "DecisionConcept": "decision",
    "EvidenceRequirement": "evidence_req",
    "PolicyGeneration": "generation",
    "VisitContext": "visit",
    "FacilityContext": "facility",
    "ReviewAction": "review_action",
    "CoverageItem": "cov",
    "ExclusionReason": "exclusion_reason",
    "BenefitLimit": "benefit_limit",
    "DeductibleRule": "deductible_rule",
    "RequiredDocument": "required_document",
    "CoordinationRule": "coordination_rule",
    "RenewalOrGenerationRule": "generation_rule",
    "ClaimUnitConcept": "claim_unit",
    "DiseaseGroupingRule": "disease_grouping_rule",
    "DiseaseRelationCriterion": "disease_relation_criterion",
    "TreatmentEpisodeContext": "treatment_episode_context",
}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


_STANDALONE_DRINKING_ALIAS = re.compile(
    r'(?<![0-9A-Za-z가-힣])술(?=$|[\s.,!?;:()\[\]{}\'"“”‘’]|[은는이가을를과와도만로에의]|(?:먹|마시)(?:고|다|면|면서|는|던|었|았|어|겠습니다))'
)


def matches_ontology_alias(text: str, alias: str) -> bool:
    """Return whether an ontology alias occurs as a usable user expression."""

    normalized_alias = str(alias or "").strip()
    if not normalized_alias:
        return False
    # The manifest owns the short alias. This boundary only prevents the Korean
    # suffix in surgical terms from being misread as the standalone drinking word.
    if normalized_alias == "술":
        return bool(_STANDALONE_DRINKING_ALIAS.search(text))
    return normalized_alias.casefold() in text.casefold()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(matches_ontology_alias(text, term) for term in terms)


@dataclass(frozen=True)
class ConceptMatch:
    concept_id: str
    canonical_name: str
    alias: str
    groups: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RetrievalExpansionRule:
    match_any: tuple[str, ...] = field(default_factory=tuple)
    context_any: tuple[str, ...] = field(default_factory=tuple)
    normalized_contains_any: tuple[str, ...] = field(default_factory=tuple)
    expansion_terms: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetrievalExpansionRule":
        return cls(
            match_any=tuple(_as_str_list(payload.get("match_any"))),
            context_any=tuple(_as_str_list(payload.get("context_any"))),
            normalized_contains_any=tuple(_as_str_list(payload.get("normalized_contains_any"))),
            expansion_terms=tuple(_as_str_list(payload.get("expansion_terms"))),
        )

    def matches(self, question: str, normalized_question: str) -> bool:
        if self.match_any and not _contains_any(question, self.match_any):
            return False
        if self.normalized_contains_any and not _contains_any(normalized_question, self.normalized_contains_any):
            return False
        if self.context_any and not _contains_any(question, self.context_any):
            return False
        return bool(self.expansion_terms)


@dataclass(frozen=True)
class OntologyConcept:
    concept_id: str
    canonical_name: str
    node_type: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    planner_coverage_topics: tuple[str, ...] = field(default_factory=tuple)
    planner_conditions: tuple[str, ...] = field(default_factory=tuple)
    planner_intents: tuple[str, ...] = field(default_factory=tuple)
    planner_claim_unit_terms: tuple[str, ...] = field(default_factory=tuple)
    planner_clarification_questions: tuple[str, ...] = field(default_factory=tuple)
    planner_required_evidence: tuple[str, ...] = field(default_factory=tuple)
    candidate_aliases: tuple[str, ...] = field(default_factory=tuple)
    evidence_tags: tuple[str, ...] = field(default_factory=tuple)
    retrieval_expansion_rules: tuple[RetrievalExpansionRule, ...] = field(default_factory=tuple)
    retrieval_lexical_priority_terms: tuple[str, ...] = field(default_factory=tuple)
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OntologyConcept":
        planner = payload.get("planner") if isinstance(payload.get("planner"), dict) else {}
        retrieval = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
        rules = retrieval.get("expansion_rules") if isinstance(retrieval.get("expansion_rules"), list) else []
        return cls(
            concept_id=str(payload.get("concept_id") or "").strip(),
            canonical_name=str(payload.get("canonical_name") or "").strip(),
            node_type=str(payload.get("node_type") or "").strip(),
            aliases=tuple(_as_str_list(payload.get("aliases"))),
            planner_coverage_topics=tuple(_as_str_list(planner.get("coverage_topics"))),
            planner_conditions=tuple(_as_str_list(planner.get("conditions"))),
            planner_intents=tuple(_as_str_list(planner.get("intents"))),
            planner_claim_unit_terms=tuple(_as_str_list(planner.get("claim_unit_terms"))),
            planner_clarification_questions=tuple(_as_str_list(planner.get("clarification_questions"))),
            planner_required_evidence=tuple(_as_str_list(planner.get("required_evidence"))),
            candidate_aliases=tuple(_as_str_list(payload.get("candidate_aliases"))),
            evidence_tags=tuple(_as_str_list(payload.get("evidence_tags"))),
            retrieval_expansion_rules=tuple(
                RetrievalExpansionRule.from_dict(rule)
                for rule in rules
                if isinstance(rule, dict)
            ),
            retrieval_lexical_priority_terms=tuple(_as_str_list(retrieval.get("lexical_priority_terms"))),
            properties=dict(payload.get("properties") or {}),
        )

    @property
    def node_prefix(self) -> str:
        configured = str(self.properties.get("node_prefix") or "").strip()
        if configured:
            return configured
        return NODE_TYPE_PREFIXES.get(self.node_type, self.node_type.lower() or "concept")

    @property
    def node_id(self) -> str:
        configured = str(self.properties.get("node_id") or "").strip()
        if configured:
            return configured
        return f"{self.node_prefix}_{normalize_name(self.canonical_name)}"


class OntologyRegistry:
    """Versioned ontology manifest loaded once and shared by runtime components."""

    def __init__(
        self,
        manifest_path: str | Path = DEFAULT_ONTOLOGY_MANIFEST,
        *,
        base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
        base_lock_path: str | Path = BASE_ONTOLOGY_LOCK,
        provenance_path: str | Path | None = None,
        enforce_integrity: bool = True,
    ):
        self.manifest_path = Path(manifest_path)
        self.base_manifest_path = Path(base_manifest_path)
        self.base_lock_path = Path(base_lock_path)
        self.provenance_path = (
            Path(provenance_path)
            if provenance_path is not None
            else self._default_provenance_path()
        )
        self.enforce_integrity = enforce_integrity
        self.schema_version = ""
        self.version = ""
        self.concepts: list[OntologyConcept] = []
        self.integrity_report = ManifestIntegrityReport(
            state="stale",
            manifest_content_hash="",
            trusted_base_content_hash="",
            issues=(),
            quarantined_concept_ids=(),
        )
        self.provenance_content_hash = ""
        self._approved_operation_paths: set[str] = set()
        self._load()
        self._validate()
        self._compile_indexes()

    def _default_provenance_path(self) -> Path | None:
        if self.manifest_path.name.endswith(".active.json"):
            return self.manifest_path.with_name(
                f"{self.manifest_path.stem}.provenance.json"
            )
        return None

    @property
    def _is_active_manifest(self) -> bool:
        return self.provenance_path is not None

    @staticmethod
    def _read_payload(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("manifest must be a JSON object")
        validate_ontology_manifest_schema(payload)
        return payload

    def _set_integrity_failure(
        self,
        code: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.integrity_report = ManifestIntegrityReport(
            state="stale",
            manifest_content_hash=manifest_content_hash(payload) if payload else "",
            trusted_base_content_hash="",
            issues=(IntegrityIssue(code=code, concept_id="", path="/integrity", message=message),),
            quarantined_concept_ids=(),
        )
        self._approved_operation_paths = set()
        self.concepts = []

    def _set_concepts(self, payload: dict[str, Any]) -> None:
        self.schema_version = str(payload.get("schema_version") or "")
        self.version = str(payload.get("version") or "")
        self.concepts = [
            OntologyConcept.from_dict(item)
            for item in payload.get("concepts", [])
            if isinstance(item, dict)
        ]

    def _load_base(self, payload: dict[str, Any]) -> None:
        self._approved_operation_paths = set()
        try:
            lock = BaseManifestLock.load(self.base_lock_path)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_integrity_failure(
                "BASE_LOCK_UNAVAILABLE",
                "reviewed base lock is unavailable or invalid",
                payload=payload,
            )
            return
        try:
            trusted_payload, report = build_trusted_base_projection(payload, lock)
        except ValueError:
            self._set_integrity_failure(
                "BASE_MANIFEST_INVALID",
                "base manifest cannot be projected against the reviewed lock",
                payload=payload,
            )
            return
        self.integrity_report = report
        if report.state == "stale":
            self.concepts = []
            return
        self._set_concepts(trusted_payload)

    def _load_active(self, payload: dict[str, Any]) -> None:
        self._approved_operation_paths = set()
        try:
            base_payload = self._read_payload(self.base_manifest_path)
            lock = BaseManifestLock.load(self.base_lock_path)
            if self.provenance_path is None:
                raise FileNotFoundError("active provenance path is required")
            provenance_payload = self._read_payload_like(self.provenance_path)
        except FileNotFoundError:
            self._set_integrity_failure(
                "ACTIVE_PROVENANCE_UNAVAILABLE",
                "active manifest provenance or reviewed base input is unavailable",
                payload=payload,
            )
            return
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_integrity_failure(
                "ACTIVE_INTEGRITY_INPUT_INVALID",
                "active manifest integrity input is invalid",
                payload=payload,
            )
            return

        try:
            audit = audit_active_manifest(base_payload, lock, payload, provenance_payload)
        except (ValueError, KeyError, TypeError):
            self._set_integrity_failure(
                "ACTIVE_INTEGRITY_AUDIT_FAILED",
                "active manifest provenance cannot be verified",
                payload=payload,
            )
            return

        self.integrity_report = audit.report
        self.provenance_content_hash = audit.provenance_content_hash
        if audit.report.state == "stale":
            self.concepts = []
            return
        quarantined = set(audit.report.quarantined_concept_ids)
        filtered_payload = dict(payload)
        filtered_payload["concepts"] = [
            concept
            for concept in payload.get("concepts", [])
            if isinstance(concept, dict)
            and str(concept.get("concept_id") or "").strip() not in quarantined
        ]
        self._set_concepts(filtered_payload)
        if audit.report.state == "valid":
            self._approved_operation_paths = {
                operation.path for operation in audit.approved_operations
            }

    def approved_decision_profile_payloads(self) -> list[dict[str, Any]]:
        """Return only active decision profiles covered by applied provenance.

        Profiles are policy payloads, not inferred runtime knowledge.  Their
        explicit operation path must be present in the validated active
        provenance sidecar before a RAG response may use them.
        """

        if not self._is_active_manifest or self.integrity_report.state != "valid":
            return []
        payloads: list[dict[str, Any]] = []
        for concept in self.concepts:
            profiles = concept.properties.get("approved_decision_profiles")
            if not isinstance(profiles, list):
                continue
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                operation_path = str(profile.get("approval_operation_path") or "").strip()
                if not operation_path or operation_path not in self._approved_operation_paths:
                    continue
                enriched = dict(profile)
                enriched["concept_id"] = concept.concept_id
                payloads.append(enriched)
        return payloads

    @staticmethod
    def _read_payload_like(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("integrity sidecar must be a JSON object")
        validate_active_provenance_schema(payload)
        return payload

    def _load(self) -> None:
        try:
            payload = self._read_payload(self.manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_integrity_failure(
                "MANIFEST_READ_FAILED",
                "ontology manifest is unavailable or invalid",
            )
            return
        if not self.enforce_integrity:
            self.integrity_report = ManifestIntegrityReport(
                state="valid",
                manifest_content_hash=manifest_content_hash(payload),
                trusted_base_content_hash="",
                issues=(),
                quarantined_concept_ids=(),
            )
            self._set_concepts(payload)
            return
        if self._is_active_manifest:
            self._load_active(payload)
            return
        self._load_base(payload)

    def _validate(self) -> None:
        seen: set[str] = set()
        errors: list[str] = []
        for concept in self.concepts:
            if not concept.concept_id:
                errors.append("concept_id is required")
            if not concept.canonical_name:
                errors.append(f"{concept.concept_id}: canonical_name is required")
            if concept.concept_id in seen:
                errors.append(f"{concept.concept_id}: duplicated concept_id")
            seen.add(concept.concept_id)
        if errors:
            raise ValueError("Invalid ontology manifest: " + "; ".join(errors))

    def _compile_indexes(self) -> None:
        self._coverage_aliases: dict[str, tuple[str, ...]] = {}
        self._condition_aliases: dict[str, tuple[str, ...]] = {}
        self._candidate_aliases: dict[str, tuple[str, ...]] = {}
        self._claim_unit_aliases: dict[str, tuple[str, ...]] = {}
        self._coverage_topics: list[str] = []
        self._conditions: list[str] = []
        self._evidence_tags: list[str] = []
        self._planner_intents_by_concept: dict[str, tuple[str, ...]] = {}

        for concept in self.concepts:
            aliases = tuple(dict.fromkeys((*concept.aliases, concept.canonical_name)))
            for topic in concept.planner_coverage_topics:
                _append_unique(self._coverage_topics, topic)
                existing = list(self._coverage_aliases.get(topic, ()))
                for alias in aliases:
                    _append_unique(existing, alias)
                self._coverage_aliases[topic] = tuple(existing)
            for condition in concept.planner_conditions:
                _append_unique(self._conditions, condition)
                existing = list(self._condition_aliases.get(condition, ()))
                for alias in aliases:
                    _append_unique(existing, alias)
                self._condition_aliases[condition] = tuple(existing)
            for claim_unit in concept.planner_claim_unit_terms:
                existing = list(self._claim_unit_aliases.get(claim_unit, ()))
                for alias in aliases:
                    _append_unique(existing, alias)
                self._claim_unit_aliases[claim_unit] = tuple(existing)
            if concept.candidate_aliases:
                self._candidate_aliases[concept.canonical_name] = concept.candidate_aliases
            for tag in concept.evidence_tags:
                _append_unique(self._evidence_tags, tag)
            if concept.planner_intents:
                self._planner_intents_by_concept[concept.concept_id] = concept.planner_intents

    @property
    def coverage_topics(self) -> list[str]:
        return list(self._coverage_topics)

    @property
    def conditions(self) -> list[str]:
        return list(self._conditions)

    @property
    def evidence_tags(self) -> list[str]:
        return list(self._evidence_tags)

    @property
    def term_aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._coverage_aliases)

    @property
    def condition_aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._condition_aliases)

    @property
    def term_candidate_aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._candidate_aliases)

    @property
    def claim_unit_aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._claim_unit_aliases)

    def find_matches(self, text: str) -> list[ConceptMatch]:
        """Return manifest-backed alias matches from concepts that passed integrity checks."""

        matches: list[ConceptMatch] = []
        for concept in self.concepts:
            groups = tuple(
                dict.fromkeys(
                    (*concept.planner_coverage_topics, *concept.planner_conditions)
                )
            )
            for alias in (*concept.aliases, concept.canonical_name):
                if matches_ontology_alias(text, alias):
                    matches.append(
                        ConceptMatch(
                            concept_id=concept.concept_id,
                            canonical_name=concept.canonical_name,
                            alias=alias,
                            groups=groups,
                        )
                    )
        return matches

    def expand_retrieval_query(self, question: str) -> str:
        normalized_question = question.replace(" ", "")
        expansion_terms: list[str] = []
        for concept in self.concepts:
            for rule in concept.retrieval_expansion_rules:
                if rule.matches(question, normalized_question):
                    for term in rule.expansion_terms:
                        if term not in question:
                            _append_unique(expansion_terms, term)
        if not expansion_terms:
            return question
        return f"{question} {' '.join(expansion_terms)}"

    def planner_guidance(
        self,
        coverage_topics: Iterable[str],
        conditions: Iterable[str],
    ) -> tuple[list[str], list[str]]:
        """Return manifest-owned questions and evidence for matched concepts."""

        selected = set(coverage_topics) | set(conditions)
        questions: list[str] = []
        evidence: list[str] = []
        for concept in self.concepts:
            concept_topics = set(concept.planner_coverage_topics) | set(concept.planner_conditions)
            if not selected.intersection(concept_topics):
                continue
            for question in concept.planner_clarification_questions:
                _append_unique(questions, question)
            for item in concept.planner_required_evidence:
                _append_unique(evidence, item)
        return questions, evidence

    def lexical_priority_terms(self, question: str) -> list[str]:
        """Return manifest-owned exact terms for the currently matched concept."""

        terms: list[str] = []
        for concept in self.concepts:
            aliases = (*concept.aliases, concept.canonical_name)
            if not _contains_any(question, aliases):
                continue
            for term in concept.retrieval_lexical_priority_terms:
                _append_unique(terms, term)
        return terms

    def concepts_for_graph_seed(self) -> list[OntologyConcept]:
        return [concept for concept in self.concepts if concept.node_type]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "schema_version": self.schema_version,
            "version": self.version,
            "concept_count": len(self.concepts),
            "alias_count": sum(len(concept.aliases) for concept in self.concepts),
            "candidate_alias_count": sum(len(concept.candidate_aliases) for concept in self.concepts),
            "retrieval_rule_count": sum(len(concept.retrieval_expansion_rules) for concept in self.concepts),
            "coverage_topic_count": len(self._coverage_topics),
            "condition_count": len(self._conditions),
            "ontology_integrity": self.integrity_summary(),
        }

    def integrity_summary(self) -> dict[str, Any]:
        return {
            "state": self.integrity_report.state,
            "manifest_content_hash": self.integrity_report.manifest_content_hash,
            "quarantined_concept_count": len(self.integrity_report.quarantined_concept_ids),
            "issue_counts": self.integrity_report.issue_counts(),
        }

    def integrity_diagnostics(self) -> dict[str, Any]:
        return {
            **self.integrity_summary(),
            "trusted_base_content_hash": self.integrity_report.trusted_base_content_hash,
            "quarantined_concept_ids": list(self.integrity_report.quarantined_concept_ids),
            "issues": [
                {
                    "code": issue.code,
                    "concept_id": issue.concept_id,
                    "path": issue.path,
                    "message": issue.message,
                }
                for issue in self.integrity_report.issues
            ],
        }

    def graph_manifest_metadata(self) -> dict[str, str]:
        """Return the bounded ontology-integrity fields recorded by graph builds."""

        return {
            "ontology_manifest_content_hash": self.integrity_report.manifest_content_hash,
            "ontology_provenance_content_hash": self.provenance_content_hash,
            "ontology_integrity_state": self.integrity_report.state,
            "ontology_quarantined_concept_count": str(
                len(self.integrity_report.quarantined_concept_ids)
            ),
        }

    def graph_manifest_integrity_errors(self, manifest: Mapping[str, str]) -> list[str]:
        """Report graph manifest values that do not match this verified registry."""

        expected = self.graph_manifest_metadata()
        errors: list[str] = []
        for key, value in expected.items():
            if key not in manifest:
                errors.append(f"{key}: expected {value or '<empty>'}, got <missing>")
                continue
            actual = str(manifest[key])
            if actual != value:
                errors.append(
                    f"{key}: expected {value or '<empty>'}, got {actual or '<empty>'}"
                )
        return errors


@lru_cache(maxsize=1)
def get_default_ontology_registry() -> OntologyRegistry:
    runtime_root = _configured_safe_baseline_runtime_root()
    if runtime_root is not None:
        from src.ontology.safe_baseline import load_safe_baseline_runtime_registry

        return load_safe_baseline_runtime_registry(runtime_root)
    return OntologyRegistry(resolve_default_ontology_manifest())


def _configured_safe_baseline_runtime_root() -> Path | None:
    configured = os.getenv(SAFE_BASELINE_RUNTIME_ROOT_ENV, "").strip()
    return Path(configured) if configured else None


def resolve_default_ontology_manifest() -> Path:
    runtime_root = _configured_safe_baseline_runtime_root()
    if runtime_root is not None:
        return runtime_root / "ontology" / "concepts.active.json"
    configured = os.getenv("INSURANCE_ONTOLOGY_MANIFEST", "").strip()
    if configured:
        return Path(configured)
    if ACTIVE_ONTOLOGY_MANIFEST.exists():
        return ACTIVE_ONTOLOGY_MANIFEST
    return BASE_ONTOLOGY_MANIFEST
