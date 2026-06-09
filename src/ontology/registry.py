from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from src.graph.normalizer import normalize_name


ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "data" / "ontology"
BASE_ONTOLOGY_MANIFEST = ONTOLOGY_DIR / "concepts.json"
ACTIVE_ONTOLOGY_MANIFEST = ONTOLOGY_DIR / "concepts.active.json"
DEFAULT_ONTOLOGY_MANIFEST = BASE_ONTOLOGY_MANIFEST
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


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term and term in text for term in terms)


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
    candidate_aliases: tuple[str, ...] = field(default_factory=tuple)
    evidence_tags: tuple[str, ...] = field(default_factory=tuple)
    retrieval_expansion_rules: tuple[RetrievalExpansionRule, ...] = field(default_factory=tuple)
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
            candidate_aliases=tuple(_as_str_list(payload.get("candidate_aliases"))),
            evidence_tags=tuple(_as_str_list(payload.get("evidence_tags"))),
            retrieval_expansion_rules=tuple(
                RetrievalExpansionRule.from_dict(rule)
                for rule in rules
                if isinstance(rule, dict)
            ),
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

    def __init__(self, manifest_path: str | Path = DEFAULT_ONTOLOGY_MANIFEST):
        self.manifest_path = Path(manifest_path)
        self.schema_version = ""
        self.version = ""
        self.concepts: list[OntologyConcept] = []
        self._load()
        self._validate()
        self._compile_indexes()

    def _load(self) -> None:
        with self.manifest_path.open(encoding="utf-8") as f:
            payload = json.load(f)
        self.schema_version = str(payload.get("schema_version") or "")
        self.version = str(payload.get("version") or "")
        self.concepts = [
            OntologyConcept.from_dict(item)
            for item in payload.get("concepts", [])
            if isinstance(item, dict)
        ]

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
        }


@lru_cache(maxsize=1)
def get_default_ontology_registry() -> OntologyRegistry:
    return OntologyRegistry(resolve_default_ontology_manifest())


def resolve_default_ontology_manifest() -> Path:
    configured = os.getenv("INSURANCE_ONTOLOGY_MANIFEST", "").strip()
    if configured:
        return Path(configured)
    if ACTIVE_ONTOLOGY_MANIFEST.exists():
        return ACTIVE_ONTOLOGY_MANIFEST
    return BASE_ONTOLOGY_MANIFEST
