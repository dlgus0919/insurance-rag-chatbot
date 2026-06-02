from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional, Set

from src.graph.query_planner import GraphQueryPlan, GraphQueryPlanner
from src.graph.schema import EdgeType, NodeType
from src.graph.store import GraphStore
from src.graph.normalizer import normalize_code, normalize_name
from src.retrieval.chunk_lookup import ChunkLookupRef


@dataclass
class GraphEvidence:
    evidence_id: str
    chunk_id: Optional[str] = None
    canonical_chunk_id: Optional[str] = None
    source_chunk_id: Optional[str] = None
    doc_short: str = ""
    doc_name: Optional[str] = None
    pdf_filename: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_version: Optional[str] = None
    row_text: Optional[str] = None
    confidence: float = 1.0


@dataclass
class GraphFact:
    subject: str
    relation: str
    object: Optional[str]
    confidence: float
    status: Literal["confirmed", "candidate", "missing"]
    evidence: List[GraphEvidence] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphRetrievalResult:
    plan: GraphQueryPlan
    facts: List[GraphFact] = field(default_factory=list)
    source_chunk_ids: List[str] = field(default_factory=list)
    source_chunk_refs: List[ChunkLookupRef] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    session_assertions: List["SessionAssertion"] = field(default_factory=list)
    review_paths: List["GraphReviewPath"] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    review_actions: List[str] = field(default_factory=list)


@dataclass
class SessionAssertion:
    kind: Literal["diagnosis", "procedure", "fee_code", "coverage_topic", "condition", "complication", "claim_unit", "disease_grouping"]
    value: str
    source: Literal["question", "claim_form", "receipt_parser", "detail_statement_parser"] = "question"
    confidence: float = 1.0
    notes: str = ""


@dataclass
class GraphPathStep:
    source: Literal["session", "graphdb"]
    subject: str
    relation: str
    object: Optional[str]
    status: Literal["asserted", "confirmed", "candidate", "missing"]
    evidence: List[GraphEvidence] = field(default_factory=list)
    notes: str = ""


@dataclass
class GraphReviewPath:
    path_id: str
    path_type: Literal[
        "complication_review",
        "diagnosis_review",
        "procedure_policy_review",
        "claim_condition_review",
        "claim_calculation_review",
        "coordination_review",
        "generation_rule_review",
        "one_disease_review",
        "disease_grouping_review",
        "claim_unit_limit_review",
        "same_disease_surgery_review",
        "recurrent_treatment_review",
    ]
    steps: List[GraphPathStep] = field(default_factory=list)
    status: Literal["missing", "candidate", "review_required", "confirmed"] = "missing"
    summary: str = ""
    required_evidence: List[str] = field(default_factory=list)
    review_actions: List[str] = field(default_factory=list)
    exclusion_reasons: List[str] = field(default_factory=list)
    benefit_limits: List[str] = field(default_factory=list)
    deductible_rules: List[str] = field(default_factory=list)
    required_documents: List[str] = field(default_factory=list)
    coordination_rules: List[str] = field(default_factory=list)
    generation_rules: List[str] = field(default_factory=list)


def _grade_prefix_for_system(grade_system: str | None) -> str | None:
    if grade_system == "신1-5종":
        return "grade_new_1_5_"
    if grade_system == "1-5종":
        return "grade_1_5_"
    if grade_system == "1-3종":
        return "grade_1_3_"
    return None


def _sort_evidences(evidences: List[GraphEvidence]) -> List[GraphEvidence]:
    """Prefer manually corrected OCR evidence when the same fact has variants."""
    return sorted(
        evidences,
        key=lambda ev: (0 if ev.source_version == "v2_manual" else 1, ev.evidence_id),
    )


def _dedupe_facts(facts: List[GraphFact]) -> List[GraphFact]:
    """Collapse repeated graph facts while preserving first-seen ordering."""
    merged: dict[tuple[Any, ...], GraphFact] = {}
    order: list[tuple[Any, ...]] = []
    for fact in facts:
        if fact.relation == "PAYS_BY_RATIO":
            key = (
                fact.subject,
                fact.relation,
                fact.object,
                fact.properties.get("payment_ratio"),
            )
        else:
            key = (
                fact.subject,
                fact.relation,
                fact.object,
                fact.properties.get("appendix_number"),
                fact.properties.get("payment_ratio"),
            )
        if key not in merged:
            fact.evidence = _sort_evidences(fact.evidence)
            merged[key] = fact
            order.append(key)
            continue

        existing = merged[key]
        seen_evidence = {ev.evidence_id for ev in existing.evidence}
        for ev in fact.evidence:
            if ev.evidence_id not in seen_evidence:
                existing.evidence.append(ev)
                seen_evidence.add(ev.evidence_id)
        existing.evidence = _sort_evidences(existing.evidence)
        existing.confidence = max(existing.confidence, fact.confidence)

    return [merged[key] for key in order]


_REVIEW_GRAPH_STEP_LIMIT = 8
_SOURCE_PRIORITY_SCORE = {
    "high": 30,
    "medium": 15,
    "low": 5,
}


def _load_json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


_GENERATION_RULE_NAME_BY_CODE = {
    "4th": "4세대 실손 적용 규칙",
    "5th": "5세대 실손 적용 규칙",
}
_DEFAULT_CLAIM_DOCUMENTS = ("진료비 영수증", "진료비 세부내역서", "진단서")
_DEFAULT_DOCUMENT_REVIEW_ACTIONS = {
    "진료비 세부내역서": "세부내역서 요청",
    "진단서": "진단서 요청",
}


def _append_unique_value(target: list[str], value: str) -> bool:
    if value and value not in target:
        target.append(value)
        return True
    return False


def _plan_needs_document_review(plan: GraphQueryPlan) -> bool:
    if getattr(plan, "evidence_tags", None):
        return False
    if "증빙 서류" in (getattr(plan, "ambiguous_terms", []) or []):
        return True
    if any("증빙" in question or "서류" in question for question in (getattr(plan, "clarification_questions", []) or [])):
        return True
    claim_topics = {
        "실손", "3대비급여", "도수치료", "체외충격파치료", "증식치료",
        "비급여 주사료", "MRI", "MRA", "자기공명영상진단", "상급병실료 차액",
    }
    return bool(claim_topics.intersection(getattr(plan, "coverage_topics", []) or []))


def _augment_review_categories_from_plan(
    plan: GraphQueryPlan,
    required_evidence: list[str],
    review_actions: list[str],
    rule_categories: dict[str, list[str]],
) -> bool:
    """Add bounded canonical rule hints when the query explicitly asks for them.

    Clause retrieval still supplies document-grounded steps. This helper only
    prevents top-N path truncation from hiding canonical rule categories that
    are already seeded in the GraphDB ontology and directly named by the plan.
    """

    changed = False
    topics = set(getattr(plan, "coverage_topics", []) or [])
    conditions = set(getattr(plan, "conditions", []) or [])
    benefit_limits = rule_categories.setdefault("benefit_limits", [])
    deductible_rules = rule_categories.setdefault("deductible_rules", [])
    generation_rules = rule_categories.setdefault("generation_rules", [])
    required_documents = rule_categories.setdefault("required_documents", [])

    if {"MRI", "MRA", "자기공명영상진단"}.intersection(topics):
        changed |= _append_unique_value(benefit_limits, "MRI/MRA 한도")
        changed |= _append_unique_value(deductible_rules, "3대비급여 공제")
    if {"도수치료", "체외충격파치료", "증식치료"}.intersection(topics):
        changed |= _append_unique_value(benefit_limits, "도수치료 횟수 한도")
        changed |= _append_unique_value(benefit_limits, "3대비급여 연간 한도")
        changed |= _append_unique_value(deductible_rules, "3대비급여 공제")
    if "상급병실료 차액" in topics or "상급병실료 차액" in conditions:
        changed |= _append_unique_value(benefit_limits, "상급병실료 차액 한도")
    if getattr(plan, "policy_generation", None):
        rule_name = _GENERATION_RULE_NAME_BY_CODE.get(plan.policy_generation)
        if rule_name:
            changed |= _append_unique_value(generation_rules, rule_name)
    if _plan_needs_document_review(plan):
        for document in _DEFAULT_CLAIM_DOCUMENTS:
            changed |= _append_unique_value(required_documents, document)
            changed |= _append_unique_value(required_evidence, document)
            action = _DEFAULT_DOCUMENT_REVIEW_ACTIONS.get(document)
            if action:
                changed |= _append_unique_value(review_actions, action)
    return changed


class GraphRetriever:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.planner = GraphQueryPlanner()
        self.complication_keywords = ["합병증", "합병증 치료", "수술 후 합병증", "부작용", "후유증", "미용 목적 시술 후 합병증"]

    def _get_evidence_by_id(self, store: GraphStore, evidence_id: str) -> Optional[GraphEvidence]:
        rows = store.query("SELECT * FROM graph_evidence WHERE evidence_id = ?", (evidence_id,))
        if not rows:
            return None
        row = rows[0]
        metadata = _load_json_object(row["metadata_json"])
        return GraphEvidence(
            evidence_id=row["evidence_id"],
            chunk_id=row["chunk_id"],
            canonical_chunk_id=row["canonical_chunk_id"],
            source_chunk_id=metadata.get("source_chunk_id"),
            doc_short=row["doc_short"],
            doc_name=row["doc_name"],
            pdf_filename=row["pdf_filename"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            source_version=row["source_version"],
            row_text=row["row_text"],
            confidence=row["confidence"]
        )

    def _get_node_evidences(self, store: GraphStore, node_id: str) -> List[GraphEvidence]:
        evidences = []
        rows = store.query(
            """
            SELECT ge.*
            FROM graph_node_evidence gne
            JOIN graph_evidence ge ON gne.evidence_id = ge.evidence_id
            WHERE gne.node_id = ?
            """,
            (node_id,)
        )
        for r in rows:
            metadata = _load_json_object(r["metadata_json"])
            evidences.append(GraphEvidence(
                evidence_id=r["evidence_id"],
                chunk_id=r["chunk_id"],
                canonical_chunk_id=r["canonical_chunk_id"],
                source_chunk_id=metadata.get("source_chunk_id"),
                doc_short=r["doc_short"],
                doc_name=r["doc_name"],
                pdf_filename=r["pdf_filename"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                source_version=r["source_version"],
                row_text=r["row_text"],
                confidence=r["confidence"]
            ))
        return evidences

    def _get_edge_evidences(self, store: GraphStore, edge_id: str) -> List[GraphEvidence]:
        evidences = []
        rows = store.query(
            """
            SELECT ge.*
            FROM graph_edge_evidence gee
            JOIN graph_evidence ge ON gee.evidence_id = ge.evidence_id
            WHERE gee.edge_id = ?
            """,
            (edge_id,)
        )
        for r in rows:
            metadata = _load_json_object(r["metadata_json"])
            evidences.append(GraphEvidence(
                evidence_id=r["evidence_id"],
                chunk_id=r["chunk_id"],
                canonical_chunk_id=r["canonical_chunk_id"],
                source_chunk_id=metadata.get("source_chunk_id"),
                doc_short=r["doc_short"],
                doc_name=r["doc_name"],
                pdf_filename=r["pdf_filename"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                source_version=r["source_version"],
                row_text=r["row_text"],
                confidence=r["confidence"]
            ))
        return evidences

    def _query_nodes_by_type(self, store: GraphStore, node_type: NodeType, names: list[str]) -> list[Any]:
        if not names:
            return []
        matched: list[Any] = []
        seen: set[str] = set()
        for name in names:
            normalized = normalize_name(name)
            rows = store.query(
                """
                SELECT *
                FROM graph_nodes
                WHERE node_type = ?
                  AND (normalized_name = ? OR normalized_name LIKE ?)
                """,
                (node_type.value, normalized, f"%{normalized}%"),
            )
            for row in rows:
                if row["node_id"] not in seen:
                    matched.append(row)
                    seen.add(row["node_id"])
        return matched

    def _find_linked_sources(
        self,
        store: GraphStore,
        target_node_id: str,
        edge_type: EdgeType,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in store.query(
                """
                SELECT e.edge_id, e.properties_json, e.confidence,
                       src.node_id as node_id, src.node_type as node_type,
                       src.canonical_name as canonical_name, src.properties_json as node_props
                FROM graph_edges e
                JOIN graph_nodes src ON e.source_node_id = src.node_id
                WHERE e.target_node_id = ? AND e.edge_type = ?
                """,
                (target_node_id, edge_type.value),
            )
        ]

    def _find_linked_targets(
        self,
        store: GraphStore,
        source_node_id: str,
        edge_type: EdgeType,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in store.query(
                """
                SELECT e.edge_id, e.properties_json, e.confidence,
                       dst.node_id as node_id, dst.node_type as node_type,
                       dst.canonical_name as canonical_name, dst.properties_json as node_props
                FROM graph_edges e
                JOIN graph_nodes dst ON e.target_node_id = dst.node_id
                WHERE e.source_node_id = ? AND e.edge_type = ?
                """,
                (source_node_id, edge_type.value),
            )
        ]

    def _collect_rule_links_for_clause(
        self,
        store: GraphStore,
        clause_node_id: str,
        *,
        strong_match: bool,
        evidences: list[GraphEvidence],
    ) -> tuple[list[GraphPathStep], dict[str, list[str]]]:
        """Return policy rule node steps linked from a policy clause."""

        relation_specs = [
            ("exclusion_reasons", EdgeType.HAS_EXCLUSION_REASON),
            ("benefit_limits", EdgeType.HAS_BENEFIT_LIMIT),
            ("deductible_rules", EdgeType.HAS_DEDUCTIBLE_RULE),
            ("required_documents", EdgeType.REQUIRES_DOCUMENT),
            ("coordination_rules", EdgeType.HAS_COORDINATION_RULE),
            ("generation_rules", EdgeType.HAS_GENERATION_RULE),
        ]
        categories: dict[str, list[str]] = {key: [] for key, _ in relation_specs}
        steps: list[GraphPathStep] = []
        for category, relation in relation_specs:
            for target in self._find_linked_targets(store, clause_node_id, relation):
                name = target["canonical_name"]
                if name not in categories[category]:
                    categories[category].append(name)
                status: Literal["confirmed", "candidate"] = "confirmed" if strong_match else "candidate"
                if relation in {EdgeType.HAS_COORDINATION_RULE, EdgeType.HAS_GENERATION_RULE, EdgeType.REQUIRES_DOCUMENT}:
                    status = "candidate" if not strong_match else "confirmed"
                steps.append(
                    GraphPathStep(
                        source="graphdb",
                        subject=name,
                        relation=relation.value,
                        object=target["node_type"],
                        status=status,
                        evidence=evidences,
                        notes="문서 조항에서 추출한 정책 rule node",
                    )
                )
        return steps, categories

    @staticmethod
    def _merge_rule_categories(target: dict[str, list[str]], source: dict[str, list[str]]) -> None:
        for key, values in source.items():
            bucket = target.setdefault(key, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)

    def _build_session_assertions(self, plan: GraphQueryPlan, question: str) -> list[SessionAssertion]:
        assertions: list[SessionAssertion] = []
        for code in plan.diagnosis_codes:
            assertions.append(SessionAssertion(kind="diagnosis", value=code))
        if plan.procedure_name:
            assertions.append(SessionAssertion(kind="procedure", value=plan.procedure_name))
        if plan.hira_code:
            assertions.append(SessionAssertion(kind="fee_code", value=plan.hira_code))
        for topic in plan.coverage_topics:
            assertions.append(SessionAssertion(kind="coverage_topic", value=topic))
        for condition in plan.conditions:
            assertions.append(SessionAssertion(kind="condition", value=condition))
        if plan.complication_asserted:
            matched_concept = "합병증"
            for keyword in self.complication_keywords:
                if keyword in question:
                    matched_concept = keyword
                    break
            assertions.append(SessionAssertion(kind="complication", value=matched_concept))
        for claim_unit in getattr(plan, "claim_unit_terms", []) or []:
            assertions.append(SessionAssertion(kind="claim_unit", value=claim_unit))
        if getattr(plan, "same_disease_claimed", False):
            assertions.append(SessionAssertion(kind="disease_grouping", value="동일 질병 주장", notes="질문에서 동일 질병 또는 하나의 질병 여부가 주장됨"))
        if getattr(plan, "same_treatment_purpose_claimed", False):
            assertions.append(SessionAssertion(kind="disease_grouping", value="같은 치료 목적 주장", notes="질문에서 같은 치료 목적 여부가 주장됨"))
        if getattr(plan, "newly_found_disease_claimed", False):
            assertions.append(SessionAssertion(kind="disease_grouping", value="새로 발견된 질병 병행 주장", notes="질문에서 새로 발견된 질병 또는 병행 치료가 주장됨"))
        return assertions

    def _matches_context(self, plan: GraphQueryPlan, node_id: str, store: GraphStore) -> bool:
        generation_targets = self._find_linked_targets(store, node_id, EdgeType.APPLIES_TO_GENERATION)
        if plan.policy_generation and generation_targets:
            allowed = {row["canonical_name"] for row in generation_targets}
            if plan.policy_generation == "5th" and "5세대" not in allowed and "공통" not in allowed:
                return False
            if plan.policy_generation == "4th" and "4세대" not in allowed and "공통" not in allowed:
                return False

        visit_targets = self._find_linked_targets(store, node_id, EdgeType.APPLIES_TO_VISIT)
        if plan.visit_type and visit_targets:
            allowed = {row["canonical_name"] for row in visit_targets}
            mapping = {"outpatient": "통원", "hospitalization": "입원"}
            if mapping.get(plan.visit_type) not in allowed:
                return False

        facility_targets = self._find_linked_targets(store, node_id, EdgeType.APPLIES_TO_FACILITY)
        if plan.facility_type and facility_targets:
            allowed = {row["canonical_name"] for row in facility_targets}
            if plan.facility_type not in allowed:
                return False
        return True

    def _linked_target_names(self, store: GraphStore, node_id: str, edge_type: EdgeType) -> set[str]:
        return {row["canonical_name"] for row in self._find_linked_targets(store, node_id, edge_type)}

    def _review_clause_match_state(
        self,
        store: GraphStore,
        plan: GraphQueryPlan,
        clause: dict[str, Any],
        relation: EdgeType,
        matched_object: str,
    ) -> tuple[bool, int, str]:
        """Return whether a clause is directly usable for the user's asserted context."""
        node_id = clause["node_id"]
        props = _load_json_object(clause.get("node_props") or clause.get("properties_json"))
        condition_targets = self._linked_target_names(store, node_id, EdgeType.APPLIES_WHEN)
        topic_targets = self._linked_target_names(store, node_id, EdgeType.HAS_TOPIC)
        generation_targets = self._linked_target_names(store, node_id, EdgeType.APPLIES_TO_GENERATION)
        visit_targets = self._linked_target_names(store, node_id, EdgeType.APPLIES_TO_VISIT)
        facility_targets = self._linked_target_names(store, node_id, EdgeType.APPLIES_TO_FACILITY)

        plan_conditions = set(plan.conditions or [])
        plan_topics = set(plan.coverage_topics or [])
        condition_match = bool(condition_targets & plan_conditions)
        topic_match = bool(topic_targets & plan_topics)

        score = _SOURCE_PRIORITY_SCORE.get(str(props.get("source_priority") or ""), 0)
        score += int((clause.get("confidence") or 0) * 10)
        score += 8 if props.get("decision_polarity") in {"exclusion", "coverage", "review", "evidence"} else 0
        score += 8 if relation == EdgeType.APPLIES_WHEN else 0
        score += 6 if relation == EdgeType.HAS_TOPIC else 0
        score += 4 if relation == EdgeType.RELATES_TO_COMPLICATION else 0
        score += 25 if condition_match else 0
        score += 15 if topic_match else 0
        if matched_object and matched_object in condition_targets | topic_targets:
            score += 10

        if plan.policy_generation:
            generation_name = "5세대" if plan.policy_generation == "5th" else "4세대"
            if generation_name in generation_targets:
                score += 8
            elif "공통" in generation_targets:
                score += 3
        if plan.visit_type:
            visit_name = {"outpatient": "통원", "hospitalization": "입원"}.get(plan.visit_type)
            if visit_name and visit_name in visit_targets:
                score += 5
        if plan.facility_type and plan.facility_type in facility_targets:
            score += 5

        condition_gate_ok = not condition_targets or condition_match
        topic_gate_ok = not topic_targets or topic_match or not plan_topics
        context_direct = condition_match or topic_match or relation in {EdgeType.APPLIES_WHEN, EdgeType.HAS_TOPIC}
        if relation == EdgeType.RELATES_TO_COMPLICATION:
            context_direct = context_direct or not condition_targets
        strong = condition_gate_ok and topic_gate_ok and context_direct
        note = str(props.get("decision_polarity") or "")
        if strong:
            note = f"{note}; 입력 조건 직접 일치".strip("; ")
        elif condition_targets:
            note = f"{note}; 조건 후보({', '.join(sorted(condition_targets))})".strip("; ")
        return strong, score, note

    def _collect_review_paths(
        self,
        store: GraphStore,
        plan: GraphQueryPlan,
        question: str,
    ) -> tuple[list[SessionAssertion], list[GraphReviewPath], set[str]]:
        session_assertions = self._build_session_assertions(plan, question)
        review_paths: list[GraphReviewPath] = []
        source_chunk_ids: set[str] = set()

        def append_source_chunks(evidences: list[GraphEvidence]) -> None:
            for evidence in evidences:
                if evidence.chunk_id:
                    source_chunk_ids.add(evidence.chunk_id)

        one_disease_path = self._collect_one_disease_review_path(store, plan, question, session_assertions)
        if one_disease_path:
            review_paths.append(one_disease_path)
            for step in one_disease_path.steps:
                append_source_chunks(step.evidence)

        # complication review
        if plan.complication_asserted:
            concept_names = [a.value for a in session_assertions if a.kind == "complication"] or ["합병증"]
            nodes = self._query_nodes_by_type(store, NodeType.ComplicationConcept, concept_names)
            steps = [
                GraphPathStep(
                    source="session",
                    subject="질문/입력",
                    relation="ASSERTS",
                    object=name,
                    status="asserted",
                )
                for name in concept_names
            ]
            status: Literal["missing", "candidate", "review_required", "confirmed"] = "review_required"
            summary = "질문에서 합병증 상황이 주장되어 관련 약관 조항과 증빙 요건을 검토했습니다."
            required_evidence: list[str] = []
            review_actions: list[str] = []
            rule_categories: dict[str, list[str]] = {}
            confirmed_exclusion = False
            candidate_exclusion = False
            matched_any = False
            graph_steps: list[tuple[int, GraphPathStep, list[GraphEvidence], str]] = []
            for node in nodes:
                for clause in self._find_linked_sources(store, node["node_id"], EdgeType.RELATES_TO_COMPLICATION):
                    if not self._matches_context(plan, clause["node_id"], store):
                        continue
                    matched_any = True
                    evidences = self._get_node_evidences(store, clause["node_id"])
                    strong_match, score, note = self._review_clause_match_state(
                        store,
                        plan,
                        clause,
                        EdgeType.RELATES_TO_COMPLICATION,
                        node["canonical_name"],
                    )
                    graph_steps.append((
                        score,
                        GraphPathStep(
                            source="graphdb",
                            subject=clause["canonical_name"],
                            relation="RELATES_TO_COMPLICATION",
                            object=node["canonical_name"],
                            status="confirmed" if strong_match else "candidate",
                            evidence=evidences,
                            notes=note,
                        ),
                        evidences,
                        clause["node_id"],
                    ))
                    if _load_json_object(clause["node_props"]).get("decision_polarity") == "exclusion":
                        if strong_match:
                            confirmed_exclusion = True
                        else:
                            candidate_exclusion = True
                    for decision in self._find_linked_targets(store, clause["node_id"], EdgeType.HAS_DECISION):
                        graph_steps.append((
                            score - 1,
                            GraphPathStep(
                                source="graphdb",
                                subject=clause["canonical_name"],
                                relation="HAS_DECISION",
                                object=decision["canonical_name"],
                                status="confirmed" if strong_match else "candidate",
                                evidence=evidences,
                                notes=note,
                            ),
                            evidences,
                            clause["node_id"],
                        ))
                        if decision["canonical_name"] == "면책":
                            if strong_match:
                                confirmed_exclusion = True
                            else:
                                candidate_exclusion = True
                    for req in self._find_linked_targets(store, clause["node_id"], EdgeType.REQUIRES_EVIDENCE):
                        required_evidence.append(req["canonical_name"])
                    for action in self._find_linked_targets(store, clause["node_id"], EdgeType.HAS_REVIEW_ACTION):
                        review_actions.append(action["canonical_name"])
                    rule_steps, categories = self._collect_rule_links_for_clause(
                        store,
                        clause["node_id"],
                        strong_match=strong_match,
                        evidences=evidences,
                    )
                    self._merge_rule_categories(rule_categories, categories)
                    for rule_step in rule_steps:
                        graph_steps.append((score - 2, rule_step, evidences, clause["node_id"]))
            selected_graph_steps = sorted(
                graph_steps,
                key=lambda item: (-item[0], item[1].subject, item[1].relation, item[1].object or ""),
            )[:_REVIEW_GRAPH_STEP_LIMIT]
            seen_steps: set[tuple[str, str, str | None]] = set()
            for _, step, evidences, _ in selected_graph_steps:
                key = (step.subject, step.relation, step.object)
                if key in seen_steps:
                    continue
                seen_steps.add(key)
                append_source_chunks(evidences)
                steps.append(step)
            if not matched_any:
                status = "missing"
                summary = "합병증 관련 직접 조항을 구조화 그래프에서 확인하지 못했습니다."
            elif confirmed_exclusion:
                status = "confirmed"
                summary = "질문/입력 조건과 직접 맞는 합병증 관련 면책/제외 조항을 확인했습니다."
            elif candidate_exclusion:
                summary = "합병증 관련 면책 후보 조항이 있으나, 입력 조건과 직접 일치하는지 추가 확인이 필요합니다."
            review_paths.append(
                GraphReviewPath(
                    path_id=f"complication::{normalize_name(question)[:40]}",
                    path_type="complication_review",
                    steps=steps,
                    status=status,
                    summary=summary,
                    required_evidence=sorted(set(required_evidence)),
                    review_actions=sorted(set(review_actions)),
                    exclusion_reasons=sorted(set(rule_categories.get("exclusion_reasons", []))),
                    benefit_limits=sorted(set(rule_categories.get("benefit_limits", []))),
                    deductible_rules=sorted(set(rule_categories.get("deductible_rules", []))),
                    required_documents=sorted(set(rule_categories.get("required_documents", []))),
                    coordination_rules=sorted(set(rule_categories.get("coordination_rules", []))),
                    generation_rules=sorted(set(rule_categories.get("generation_rules", []))),
                )
            )

        # diagnosis review
        if plan.diagnosis_codes:
            for code in plan.diagnosis_codes:
                rows = store.query(
                    "SELECT * FROM graph_nodes WHERE node_type = ? AND normalized_name = ?",
                    (NodeType.DiagnosisCode.value, normalize_code(code)),
                )
                steps = [
                    GraphPathStep(
                        source="session",
                        subject="질문/입력",
                        relation="ASSERTS",
                        object=code,
                        status="asserted",
                    )
                ]
                status: Literal["missing", "candidate", "review_required", "confirmed"] = "missing"
                summary = "문서에서 직접 연결된 진단코드 근거를 찾지 못했습니다."
                required_evidence: list[str] = []
                review_actions: list[str] = []
                rule_categories: dict[str, list[str]] = {}
                if rows:
                    diag_node = rows[0]
                    clauses = self._find_linked_sources(store, diag_node["node_id"], EdgeType.RELATES_TO_DIAGNOSIS)
                    cases = self._find_linked_sources(store, diag_node["node_id"], EdgeType.RELATES_TO_DIAGNOSIS)
                    combined = clauses + [case for case in cases if case["node_id"] not in {c["node_id"] for c in clauses}]
                    if combined:
                        status = "confirmed"
                        summary = "문서에 직접 언급된 진단코드와 연결된 약관/사례 근거를 찾았습니다."
                    for node in combined:
                        if not self._matches_context(plan, node["node_id"], store):
                            continue
                        evidences = self._get_node_evidences(store, node["node_id"])
                        append_source_chunks(evidences)
                        steps.append(
                            GraphPathStep(
                                source="graphdb",
                                subject=node["canonical_name"],
                                relation="RELATES_TO_DIAGNOSIS",
                                object=code,
                                status="confirmed",
                                evidence=evidences,
                            )
                        )
                        for req in self._find_linked_targets(store, node["node_id"], EdgeType.REQUIRES_EVIDENCE):
                            required_evidence.append(req["canonical_name"])
                        for action in self._find_linked_targets(store, node["node_id"], EdgeType.HAS_REVIEW_ACTION):
                            review_actions.append(action["canonical_name"])
                        rule_steps, categories = self._collect_rule_links_for_clause(
                            store,
                            node["node_id"],
                            strong_match=True,
                            evidences=evidences,
                        )
                        self._merge_rule_categories(rule_categories, categories)
                        steps.extend(rule_steps[:_REVIEW_GRAPH_STEP_LIMIT])
                review_paths.append(
                    GraphReviewPath(
                        path_id=f"diagnosis::{normalize_name(code)}",
                        path_type="diagnosis_review",
                        steps=steps,
                        status=status,
                        summary=summary,
                        required_evidence=sorted(set(required_evidence)),
                        review_actions=sorted(set(review_actions)),
                        exclusion_reasons=sorted(set(rule_categories.get("exclusion_reasons", []))),
                        benefit_limits=sorted(set(rule_categories.get("benefit_limits", []))),
                        deductible_rules=sorted(set(rule_categories.get("deductible_rules", []))),
                        required_documents=sorted(set(rule_categories.get("required_documents", []))),
                        coordination_rules=sorted(set(rule_categories.get("coordination_rules", []))),
                        generation_rules=sorted(set(rule_categories.get("generation_rules", []))),
                    )
                )

        # claim condition / topic review
        condition_names = list(dict.fromkeys(plan.conditions + plan.coverage_topics))
        if condition_names:
            session_steps: list[GraphPathStep] = []
            graph_candidates: list[tuple[int, GraphPathStep, list[GraphEvidence], dict[str, Any], bool]] = []
            matched_any = False
            required_evidence: list[str] = []
            review_actions: list[str] = []
            rule_categories: dict[str, list[str]] = {}
            confirmed_exclusion = False
            for name in condition_names:
                session_steps.append(
                    GraphPathStep(source="session", subject="질문/입력", relation="ASSERTS", object=name, status="asserted")
                )
                cond_nodes = self._query_nodes_by_type(store, NodeType.ClaimCondition, [name])
                for cond in cond_nodes:
                    for clause in self._find_linked_sources(store, cond["node_id"], EdgeType.APPLIES_WHEN):
                        if not self._matches_context(plan, clause["node_id"], store):
                            continue
                        matched_any = True
                        evidences = self._get_node_evidences(store, clause["node_id"])
                        strong_match, score, note = self._review_clause_match_state(
                            store,
                            plan,
                            clause,
                            EdgeType.APPLIES_WHEN,
                            cond["canonical_name"],
                        )
                        graph_candidates.append((
                            score,
                            GraphPathStep(
                                source="graphdb",
                                subject=clause["canonical_name"],
                                relation="APPLIES_WHEN",
                                object=cond["canonical_name"],
                                status="confirmed" if strong_match else "candidate",
                                evidence=evidences,
                                notes=note,
                            )
                            ,
                            evidences,
                            clause,
                            strong_match,
                        ))
                topic_nodes = self._query_nodes_by_type(store, NodeType.CoverageItem, [name])
                for topic in topic_nodes:
                    for clause in self._find_linked_sources(store, topic["node_id"], EdgeType.HAS_TOPIC):
                        if not self._matches_context(plan, clause["node_id"], store):
                            continue
                        matched_any = True
                        evidences = self._get_node_evidences(store, clause["node_id"])
                        strong_match, score, note = self._review_clause_match_state(
                            store,
                            plan,
                            clause,
                            EdgeType.HAS_TOPIC,
                            topic["canonical_name"],
                        )
                        graph_candidates.append((
                            score,
                            GraphPathStep(
                                source="graphdb",
                                subject=clause["canonical_name"],
                                relation="HAS_TOPIC",
                                object=topic["canonical_name"],
                                status="confirmed" if strong_match else "candidate",
                                evidence=evidences,
                                notes=note,
                            )
                            ,
                            evidences,
                            clause,
                            strong_match,
                        ))
            steps: list[GraphPathStep] = list(session_steps)
            selected_candidates = sorted(
                graph_candidates,
                key=lambda item: (-item[0], item[1].subject, item[1].relation, item[1].object or ""),
            )
            seen_candidates: set[tuple[str, str, str | None]] = set()
            for _, step, evidences, clause, strong_match in selected_candidates:
                key = (step.subject, step.relation, step.object)
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                append_source_chunks(evidences)
                steps.append(step)
                clause_props = _load_json_object(clause.get("node_props"))
                if strong_match and clause_props.get("decision_polarity") == "exclusion":
                    confirmed_exclusion = True
                for decision in self._find_linked_targets(store, clause["node_id"], EdgeType.HAS_DECISION):
                    if strong_match and decision["canonical_name"] == "면책":
                        confirmed_exclusion = True
                for req in self._find_linked_targets(store, clause["node_id"], EdgeType.REQUIRES_EVIDENCE):
                    required_evidence.append(req["canonical_name"])
                for action in self._find_linked_targets(store, clause["node_id"], EdgeType.HAS_REVIEW_ACTION):
                    review_actions.append(action["canonical_name"])
                rule_steps, categories = self._collect_rule_links_for_clause(
                    store,
                    clause["node_id"],
                    strong_match=strong_match,
                    evidences=evidences,
                )
                self._merge_rule_categories(rule_categories, categories)
                for rule_step in rule_steps:
                    rule_key = (rule_step.subject, rule_step.relation, rule_step.object)
                    if rule_key not in seen_candidates:
                        seen_candidates.add(rule_key)
                        steps.append(rule_step)
                if len(steps) - len(session_steps) >= _REVIEW_GRAPH_STEP_LIMIT:
                    break
            augmented_by_plan = _augment_review_categories_from_plan(
                plan,
                required_evidence,
                review_actions,
                rule_categories,
            )
            has_review_path = matched_any or augmented_by_plan
            review_paths.append(
                GraphReviewPath(
                    path_id=f"condition::{normalize_name(' '.join(condition_names))[:40]}",
                    path_type="claim_condition_review",
                    steps=steps,
                    status="confirmed" if matched_any and confirmed_exclusion else ("review_required" if has_review_path else "missing"),
                    summary="문서 기반 보장 주제/판단 조건 검토 경로를 수집했습니다." if has_review_path else "직접 연결된 판단 조건 경로를 찾지 못했습니다.",
                    required_evidence=sorted(set(required_evidence)),
                    review_actions=sorted(set(review_actions)),
                    exclusion_reasons=sorted(set(rule_categories.get("exclusion_reasons", []))),
                    benefit_limits=sorted(set(rule_categories.get("benefit_limits", []))),
                    deductible_rules=sorted(set(rule_categories.get("deductible_rules", []))),
                    required_documents=sorted(set(rule_categories.get("required_documents", []))),
                    coordination_rules=sorted(set(rule_categories.get("coordination_rules", []))),
                    generation_rules=sorted(set(rule_categories.get("generation_rules", []))),
                )
            )

        # coordination-specific review path
        coordination_names = [name for name in condition_names if name in {"자동차보험", "산재보험", "타 보험 보상"}]
        if coordination_names:
            steps = [
                GraphPathStep(source="session", subject="질문/입력", relation="ASSERTS", object=name, status="asserted")
                for name in coordination_names
            ]
            coordination_rules: list[str] = []
            required_documents: list[str] = []
            for path in review_paths:
                for rule in path.coordination_rules:
                    if rule not in coordination_rules:
                        coordination_rules.append(rule)
                for doc in path.required_documents:
                    if doc not in required_documents:
                        required_documents.append(doc)
            review_paths.append(
                GraphReviewPath(
                    path_id=f"coordination::{normalize_name(' '.join(coordination_names))[:40]}",
                    path_type="coordination_review",
                    steps=steps,
                    status="review_required",
                    summary="자동차보험/산재보험/타보험 조정 가능성이 있어 자동 확정보다 지급내역과 중복 보상 여부 검토가 우선입니다.",
                    required_evidence=sorted(set(required_documents)),
                    review_actions=["인간 심사 필요"],
                    coordination_rules=sorted(set(coordination_rules)),
                    required_documents=sorted(set(required_documents)),
                )
            )

        # generation-specific review path
        if (
            plan.policy_generation
            or getattr(plan, "recurrent_or_continuing_treatment", False)
            or any(name in {"실손", "3대비급여", "도수치료", "MRI", "MRA", "자기공명영상진단"} for name in condition_names)
        ):
            generation_rules = sorted({rule for path in review_paths for rule in path.generation_rules})
            deductible_rules = sorted({rule for path in review_paths for rule in path.deductible_rules})
            benefit_limits = sorted({rule for path in review_paths for rule in path.benefit_limits})
            status: Literal["missing", "candidate", "review_required", "confirmed"] = "confirmed" if plan.policy_generation and (generation_rules or deductible_rules or benefit_limits) else "review_required"
            review_paths.append(
                GraphReviewPath(
                    path_id=f"generation::{plan.policy_generation or 'unknown'}::{normalize_name(' '.join(condition_names))[:24]}",
                    path_type="generation_rule_review",
                    steps=[
                        GraphPathStep(
                            source="session",
                            subject="질문/입력",
                            relation="ASSERTS",
                            object=plan.policy_generation or "세대 미확정",
                            status="asserted",
                        )
                    ],
                    status=status,
                    summary="실손 세대/방문 구분에 따라 한도와 공제 규칙이 달라질 수 있어 세대 기준을 함께 검토했습니다.",
                    review_actions=[] if plan.policy_generation else ["실손 세대 확인"],
                    generation_rules=generation_rules,
                    deductible_rules=deductible_rules,
                    benefit_limits=benefit_limits,
                )
            )

        return session_assertions, review_paths, source_chunk_ids

    def _collect_one_disease_review_path(
        self,
        store: GraphStore,
        plan: GraphQueryPlan,
        question: str,
        session_assertions: list[SessionAssertion],
    ) -> GraphReviewPath | None:
        requested_units = list(dict.fromkeys(getattr(plan, "claim_unit_terms", []) or []))
        if not requested_units and not getattr(plan, "disease_grouping_requested", False):
            return None
        if not requested_units:
            requested_units = ["하나의 질병"]

        steps: list[GraphPathStep] = [
            GraphPathStep(
                source="session",
                subject="질문/입력",
                relation="ASSERTS",
                object=assertion.value,
                status="asserted",
                notes=assertion.notes,
            )
            for assertion in session_assertions
            if assertion.kind in {"claim_unit", "disease_grouping", "complication", "diagnosis", "procedure"}
        ]
        required_documents: list[str] = []
        review_actions: list[str] = []
        benefit_limits: list[str] = []
        deductible_rules: list[str] = []
        generation_rules: list[str] = []
        matched_any = False
        seen_steps: set[tuple[str, str, str | None]] = set()

        def append_step(step: GraphPathStep) -> None:
            key = (step.subject, step.relation, step.object)
            if key not in seen_steps:
                seen_steps.add(key)
                steps.append(step)

        for unit in requested_units:
            unit_nodes = self._query_nodes_by_type(store, NodeType.ClaimUnitConcept, [unit])
            for unit_node in unit_nodes:
                unit_name = unit_node["canonical_name"]
                for clause in self._find_linked_sources(store, unit_node["node_id"], EdgeType.DEFINES_CLAIM_UNIT):
                    if not self._matches_context(plan, clause["node_id"], store):
                        continue
                    matched_any = True
                    clause_evidences = self._get_node_evidences(store, clause["node_id"])
                    append_step(
                        GraphPathStep(
                            source="graphdb",
                            subject=clause["canonical_name"],
                            relation=EdgeType.DEFINES_CLAIM_UNIT.value,
                            object=unit_name,
                            status="candidate",
                            evidence=clause_evidences,
                            notes="약관 원문에서 확인된 claim unit 후보",
                        )
                    )
                    rule_steps, categories = self._collect_rule_links_for_clause(
                        store,
                        clause["node_id"],
                        strong_match=False,
                        evidences=clause_evidences,
                    )
                    for rule_step in rule_steps:
                        append_step(rule_step)
                    benefit_limits.extend(categories.get("benefit_limits", []))
                    deductible_rules.extend(categories.get("deductible_rules", []))
                    generation_rules.extend(categories.get("generation_rules", []))
                    for action in self._find_linked_targets(store, clause["node_id"], EdgeType.REQUIRES_GROUPING_REVIEW):
                        review_actions.append(action["canonical_name"])
                        append_step(
                            GraphPathStep(
                                source="graphdb",
                                subject=clause["canonical_name"],
                                relation=EdgeType.REQUIRES_GROUPING_REVIEW.value,
                                object=action["canonical_name"],
                                status="candidate",
                                evidence=clause_evidences,
                            )
                        )
                    for rule in self._find_linked_targets(store, clause["node_id"], EdgeType.HAS_GROUPING_RULE):
                        rule_name = rule["canonical_name"]
                        append_step(
                            GraphPathStep(
                                source="graphdb",
                                subject=clause["canonical_name"],
                                relation=EdgeType.HAS_GROUPING_RULE.value,
                                object=rule_name,
                                status="candidate",
                                evidence=clause_evidences,
                                notes="하나의 질병 판단 기준 후보",
                            )
                        )
                        for criterion in self._find_linked_targets(store, rule["node_id"], EdgeType.HAS_RELATION_CRITERION):
                            append_step(
                                GraphPathStep(
                                    source="graphdb",
                                    subject=rule_name,
                                    relation=EdgeType.HAS_RELATION_CRITERION.value,
                                    object=criterion["canonical_name"],
                                    status="candidate",
                                    evidence=clause_evidences,
                                )
                            )
                        for context in self._find_linked_targets(store, rule["node_id"], EdgeType.APPLIES_TO_TREATMENT_CONTEXT):
                            append_step(
                                GraphPathStep(
                                    source="graphdb",
                                    subject=rule_name,
                                    relation=EdgeType.APPLIES_TO_TREATMENT_CONTEXT.value,
                                    object=context["canonical_name"],
                                    status="candidate",
                                    evidence=clause_evidences,
                                )
                            )
                        for doc in self._find_linked_targets(store, rule["node_id"], EdgeType.REQUIRES_GROUPING_EVIDENCE):
                            required_documents.append(doc["canonical_name"])
                            append_step(
                                GraphPathStep(
                                    source="graphdb",
                                    subject=rule_name,
                                    relation=EdgeType.REQUIRES_GROUPING_EVIDENCE.value,
                                    object=doc["canonical_name"],
                                    status="candidate",
                                    evidence=clause_evidences,
                                )
                            )

        if not matched_any:
            return GraphReviewPath(
                path_id=f"one_disease::{normalize_name(question)[:40]}",
                path_type="one_disease_review",
                steps=steps,
                status="missing",
                summary="하나의 질병 관련 구조화 조항을 GraphDB에서 확인하지 못했습니다.",
                review_actions=["인간 심사 필요"],
            )

        return GraphReviewPath(
            path_id=f"one_disease::{normalize_name(question)[:40]}",
            path_type="one_disease_review",
            steps=steps[: _REVIEW_GRAPH_STEP_LIMIT + len(requested_units) + 3],
            status="review_required",
            summary="하나의 질병 여부는 문서 기준과 청구 증빙을 함께 확인해야 하므로 자동 확정하지 않고 검토 경로로 제시합니다.",
            required_evidence=sorted(set(required_documents)),
            review_actions=sorted(set(review_actions or ["인간 심사 필요"])),
            benefit_limits=sorted(set(benefit_limits)),
            deductible_rules=sorted(set(deductible_rules)),
            required_documents=sorted(set(required_documents)),
            generation_rules=sorted(set(generation_rules)),
        )

    def retrieve(self, question: str, clarification: dict | None = None) -> GraphRetrievalResult:
        plan = self.planner.plan(question, clarification=clarification)
        result = GraphRetrievalResult(plan=plan)

        # fallback 대비: db_path가 없으면 경고만 남기고 리턴
        if not self.db_path.exists():
            result.warnings.append(f"Graph DB file not found at {self.db_path}. Running with empty graph fallback.")
            return result

        try:
            # 116번 라인의 read-only 연결 사용
            store = GraphStore(self.db_path, readonly=True)
        except Exception as e:
            result.warnings.append(f"Failed to connect to Graph DB: {e}. Running with empty graph fallback.")
            return result

        try:
            facts: List[GraphFact] = []
            source_chunk_ids: Set[str] = set()
            debug_info: dict[str, Any] = {}
            session_assertions, review_paths, review_chunk_ids = self._collect_review_paths(store, plan, question)
            source_chunk_ids.update(review_chunk_ids)
            result.session_assertions = session_assertions
            result.review_paths = review_paths
            result.required_evidence = sorted({
                item
                for path in review_paths
                for item in list(path.required_evidence or []) + list(path.required_documents or [])
            })
            result.review_actions = sorted({item for path in review_paths for item in path.review_actions})

            # INTENT 1: surgery_grade_lookup / same_grade_surgery_list
            if plan.procedure_name:
                norm_proc = normalize_name(plan.procedure_name)
                # 수술 노드 조회
                proc_nodes = store.query(
                    """
                    SELECT * FROM graph_nodes
                    WHERE node_type = 'SurgeryProcedure'
                      AND (normalized_name = ? OR node_id IN (
                          SELECT node_id FROM graph_aliases WHERE normalized_alias = ?
                      ))
                    """,
                    (norm_proc, norm_proc)
                )

                is_fuzzy = False
                if not proc_nodes:
                    # exact/alias lookup 실패 시 fuzzy lookup fallback
                    fuzzy_param = f"%{norm_proc}%"
                    proc_nodes = store.query(
                        """
                        SELECT * FROM graph_nodes
                        WHERE node_type = 'SurgeryProcedure'
                          AND normalized_name LIKE ?
                        """,
                        (fuzzy_param,)
                    )
                    if proc_nodes:
                        is_fuzzy = True

                if not proc_nodes:
                    # Missing 수술 노드
                    facts.append(GraphFact(
                        subject=plan.procedure_name,
                        relation="EXISTS",
                        object=None,
                        confidence=0.0,
                        status="missing",
                        properties={"reason": "Procedure node not found in graph database."}
                    ))
                else:
                    proc_node = proc_nodes[0]
                    proc_id = proc_node["node_id"]
                    proc_canonical = proc_node["canonical_name"]
                    debug_info["matched_proc_node"] = dict(proc_node)
                    debug_info["is_fuzzy_match"] = is_fuzzy

                    # 수술 등급 조회
                    grade_prefix = _grade_prefix_for_system(plan.grade_system)
                    grade_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n.node_id as grade_id, n.canonical_name as grade_name, n.properties_json as grade_props
                        FROM graph_edges e
                        JOIN graph_nodes n ON e.target_node_id = n.node_id
                        WHERE e.source_node_id = ? AND e.edge_type = 'HAS_GRADE'
                          AND (? IS NULL OR n.node_id LIKE ?)
                        ORDER BY
                          CASE
                            WHEN n.node_id LIKE 'grade_new_1_5_%' THEN 1
                            WHEN n.node_id LIKE 'grade_1_5_%' THEN 2
                            WHEN n.node_id LIKE 'grade_1_3_%' THEN 3
                            ELSE 4
                          END ASC
                        """,
                        (proc_id, grade_prefix, f"{grade_prefix}%" if grade_prefix else None)
                    )

                    grade_node_id = None
                    if not grade_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="HAS_GRADE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "Grade relation missing for surgery."}
                        ))
                    else:
                        grade_node_id = grade_edges[0]["grade_id"]
                        for ge in grade_edges:
                            grade_canonical = ge["grade_name"]

                            # Evidence 조회
                            evs = self._get_edge_evidences(store, ge["edge_id"])
                            if ge["source_evidence_id"]:
                                sev = self._get_evidence_by_id(store, ge["source_evidence_id"])
                                if sev and sev not in evs:
                                    evs.append(sev)

                            for ev in evs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # 등급 Fact 추가
                            if is_fuzzy:
                                status = "candidate"
                                confidence = 0.5
                            else:
                                status = "confirmed" if ge["edge_confidence"] >= 1.0 and len(evs) > 0 else "candidate"
                                confidence = ge["edge_confidence"]

                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="HAS_GRADE",
                                object=grade_canonical,
                                confidence=confidence,
                                status=status,
                                evidence=evs,
                                properties=json.loads(ge["grade_props"]) if ge["grade_props"] else {}
                            ))

                    # INTENT 2: same_grade_surgery_list (Peer 조회)
                    if "same_grade_surgery_list" in plan.intents and grade_node_id:
                        peers = store.query(
                            """
                            SELECT DISTINCT p.node_id, p.canonical_name, e.confidence as edge_confidence, e.edge_id,
                              -- 1. 질문 대상 수술과 동일 대분류 HAS_CATEGORY 공유 여부
                              (SELECT COUNT(*) FROM graph_edges e1
                               JOIN graph_edges e2 ON e1.target_node_id = e2.target_node_id
                               WHERE e1.edge_type = 'HAS_CATEGORY' AND e2.edge_type = 'HAS_CATEGORY'
                                 AND e1.source_node_id = p.node_id AND e2.source_node_id = ?) as share_cat,

                              -- 2. SOL [별표7] 후보 조항과 같은 category_large에 속하는지 여부
                              (SELECT COUNT(*) FROM graph_edges e_cat
                               JOIN graph_nodes n_cat ON e_cat.target_node_id = n_cat.node_id
                               WHERE e_cat.source_node_id = p.node_id AND e_cat.edge_type = 'HAS_CATEGORY'
                                 AND n_cat.canonical_name IN (
                                     SELECT json_extract(n_rule.properties_json, '$.category_large')
                                     FROM graph_edges e_rule
                                     JOIN graph_nodes n_rule ON e_rule.source_node_id = n_rule.node_id
                                     WHERE e_rule.target_node_id = ? AND e_rule.edge_type = 'POLICY_COVERS_PROCEDURE'
                                 )) as share_rule_cat,

                              -- 3. evidence 존재 여부
                              (CASE WHEN e.source_evidence_id IS NOT NULL THEN 1
                                    WHEN EXISTS (SELECT 1 FROM graph_edge_evidence WHERE edge_id = e.edge_id) THEN 1
                                    ELSE 0 END) as has_evidence
                            FROM graph_edges e
                            JOIN graph_nodes p ON e.source_node_id = p.node_id
                            WHERE e.target_node_id = ? AND e.edge_type = 'HAS_GRADE' AND e.source_node_id != ?
                            ORDER BY
                              share_cat DESC,
                              share_rule_cat DESC,
                              has_evidence DESC,
                              p.canonical_name ASC
                            LIMIT ?
                            """,
                            (proc_id, proc_id, grade_node_id, proc_id, plan.requested_peer_count)
                        )

                        if len(peers) < plan.requested_peer_count:
                            result.warnings.append(f"요청된 peer 개수({plan.requested_peer_count}개)보다 실제 반환할 수 있는 peer 후보({len(peers)}개)가 부족합니다.")

                        for peer in peers:
                            peer_id = peer["node_id"]
                            peer_canonical = peer["canonical_name"]

                            # Peer evidences
                            peevs = self._get_edge_evidences(store, peer["edge_id"])
                            for ev in peevs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # Peer 카테고리 정보 조회
                            cat_edges = store.query(
                                """
                                SELECT n.canonical_name
                                FROM graph_edges e
                                JOIN graph_nodes n ON e.target_node_id = n.node_id
                                WHERE e.source_node_id = ? AND e.edge_type = 'HAS_CATEGORY'
                                """,
                                (peer_id,)
                            )
                            peer_cats = [c["canonical_name"] for c in cat_edges]

                            # Peer의 appendix 7 rule 번호 등 약관 매핑 정보 조회
                            rule_edges = store.query(
                                """
                                SELECT n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props, e.confidence as edge_confidence
                                FROM graph_edges e
                                JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                                WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                                """,
                                (peer_id,)
                            )

                            rule_props = {}
                            if rule_edges:
                                rp = rule_edges[0]["rule_props"]
                                rule_props = json.loads(rp) if rp else {}

                            facts.append(GraphFact(
                                subject=peer_canonical,
                                relation="SAME_GRADE_PEER",
                                object=proc_canonical,
                                confidence=0.5 if is_fuzzy else peer["edge_confidence"],
                                status="candidate" if is_fuzzy else ("confirmed" if peer["edge_confidence"] >= 1.0 else "candidate"),
                                evidence=peevs,
                                properties={
                                    "categories": peer_cats,
                                    "grade_system": plan.grade_system or "신1-5종",
                                    "grade_value": plan.grade_value or "4",
                                    **rule_props
                                }
                            ))

                    # 약관 매핑 및 지급비율 조회 (POLICY_COVERS_PROCEDURE)
                    rule_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n_rule.node_id as rule_id, n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props
                        FROM graph_edges e
                        JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                        WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                        """,
                        (proc_id,)
                    )

                    if not rule_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="POLICY_COVERS_PROCEDURE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "Policy coverage mapping missing in graph DB."}
                        ))
                    else:
                        for re_edge in rule_edges:
                            rule_props = json.loads(re_edge["rule_props"]) if re_edge["rule_props"] else {}

                            # Evidence
                            revs = self._get_edge_evidences(store, re_edge["edge_id"])
                            if re_edge["source_evidence_id"]:
                                rsev = self._get_evidence_by_id(store, re_edge["source_evidence_id"])
                                if rsev and rsev not in revs:
                                    revs.append(rsev)

                            for ev in revs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # POLICY_COVERS_PROCEDURE 엣지는 0.8 이하 신뢰도이므로 무조건 candidate로 취급해야 한다!
                            confidence = 0.5 if is_fuzzy else re_edge["edge_confidence"]
                            facts.append(GraphFact(
                                subject=re_edge["rule_name"],
                                relation="POLICY_COVERS_PROCEDURE",
                                object=proc_canonical,
                                confidence=confidence,
                                status="candidate",
                                evidence=revs,
                                properties=rule_props
                            ))

            # INTENT 3: category_grade_listing (소화기계 5종 등 카테고리별 나열)
            if "category_grade_listing" in plan.intents and plan.category and plan.grade_value:
                # 5종 코드 매칭
                grade_node_key = f"grade_new_1_5_{plan.grade_value}"

                procs = store.query(
                    """
                    SELECT DISTINCT p.node_id, p.canonical_name, e_grd.edge_id, e_grd.source_evidence_id, e_grd.confidence as edge_confidence
                    FROM graph_nodes p
                    JOIN graph_edges e_cat ON p.node_id = e_cat.source_node_id AND e_cat.edge_type = 'HAS_CATEGORY'
                    JOIN graph_edges e_grd ON p.node_id = e_grd.source_node_id AND e_grd.edge_type = 'HAS_GRADE'
                    WHERE e_cat.target_node_id IN (
                        SELECT node_id FROM graph_nodes WHERE node_type = 'SurgeryCategory' AND normalized_name LIKE ?
                    ) AND e_grd.target_node_id = ?
                    """,
                    (f"%{normalize_name(plan.category)}%", grade_node_key)
                )

                debug_info["category_grade_listing_count"] = len(procs)

                for p_row_raw in procs:
                    p_row = dict(p_row_raw)
                    proc_id = p_row["node_id"]
                    proc_canonical = p_row["canonical_name"]

                    # HAS_GRADE evidence 조회
                    gevs = []
                    if p_row.get("edge_id"):
                        gevs = self._get_edge_evidences(store, p_row["edge_id"])
                        if p_row.get("source_evidence_id"):
                            gsev = self._get_evidence_by_id(store, p_row["source_evidence_id"])
                            if gsev and gsev not in gevs:
                                gevs.append(gsev)

                    for ev in gevs:
                        if ev.chunk_id:
                            source_chunk_ids.add(ev.chunk_id)

                    # 1. 등급 관계 추가
                    facts.append(GraphFact(
                        subject=proc_canonical,
                        relation="HAS_GRADE",
                        object=f"{plan.grade_system or '신1-5종'} {plan.grade_value}종",
                        confidence=p_row["edge_confidence"] if p_row.get("edge_confidence") is not None else 1.0,
                        status="confirmed" if len(gevs) > 0 else "candidate",
                        evidence=gevs
                    ))

                    # 2. 수가코드 (MedicalFeeCode) 조회
                    fee_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence,
                               n.node_id as fee_id,
                               n.canonical_name as fee_name,
                               json_extract(n.properties_json, '$.code') as fee_code
                        FROM graph_edges e
                        JOIN graph_nodes n ON e.target_node_id = n.node_id
                        WHERE e.source_node_id = ? AND e.edge_type = 'HAS_MEDICAL_FEE_CODE'
                        """,
                        (proc_id,)
                    )

                    if not fee_edges:
                        # 수가코드 missing 사실 기록 (환각 방지)
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="HAS_MEDICAL_FEE_CODE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": f"No MedicalFeeCode mapping found in GraphDB for {proc_canonical}."}
                        ))
                    else:
                        for fe in fee_edges:
                            # Evidence
                            fevs = self._get_edge_evidences(store, fe["edge_id"])
                            for ev in fevs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            fee_object = fe["fee_code"] or fe["fee_name"]
                            if fe["fee_code"] and fe["fee_name"] and fe["fee_code"] != fe["fee_name"]:
                                fee_object = f"{fe['fee_code']} ({fe['fee_name']})"

                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="HAS_MEDICAL_FEE_CODE",
                                object=fee_object,
                                confidence=fe["edge_confidence"],
                                status="confirmed" if fe["edge_confidence"] >= 0.95 and len(fevs) > 0 else "candidate",
                                evidence=fevs
                            ))

                    # 3. 약관 지급 비율 조회
                    rule_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props
                        FROM graph_edges e
                        JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                        WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                        """,
                        (proc_id,)
                    )

                    if not rule_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="PAYS_BY_RATIO",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "No policy rule payment ratio mapping found."}
                        ))
                    else:
                        for re_edge in rule_edges:
                            rule_props = json.loads(re_edge["rule_props"]) if re_edge["rule_props"] else {}
                            ratio_val = rule_props.get("payment_ratio")

                            revs = self._get_edge_evidences(store, re_edge["edge_id"])
                            if re_edge["source_evidence_id"]:
                                rsev = self._get_evidence_by_id(store, re_edge["source_evidence_id"])
                                if rsev and rsev not in revs:
                                    revs.append(rsev)
                            for ev in revs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # POLICY_COVERS_PROCEDURE 기반의 지급비율 정보이므로 candidate로 처리
                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="PAYS_BY_RATIO",
                                object=ratio_val,
                                confidence=re_edge["edge_confidence"],
                                status="candidate",
                                evidence=revs,
                                properties=rule_props
                            ))

            # INTENT 4: policy_appendix_payment_lookup (별표7의 특정 항목 조회 등)
            if "policy_appendix_payment_lookup" in plan.intents and plan.appendix and plan.appendix_numbers:
                numbers = plan.appendix_numbers
                placeholders = ",".join(["?"] * len(numbers))
                rules = store.query(
                    f"""
                    SELECT * FROM graph_nodes
                    WHERE node_type = 'PolicyBenefitRule'
                      AND json_extract(properties_json, '$.appendix_name') = ?
                      AND json_extract(properties_json, '$.appendix_number') IN ({placeholders})
                    """,
                    (plan.appendix, *numbers)
                )

                for rule in rules:
                    rule_id = rule["node_id"]
                    rule_props = json.loads(rule["properties_json"]) if rule["properties_json"] else {}

                    # 4.3 DEFINED_IN_APPENDIX evidence 연결 및 status 하향 처리
                    evs = self._get_node_evidences(store, rule_id)
                    for ev in evs:
                        if ev.chunk_id:
                            source_chunk_ids.add(ev.chunk_id)

                    status = "confirmed" if len(evs) > 0 else "candidate"
                    if len(evs) == 0:
                        result.warnings.append(f"주의: 규정 조항 '{rule_id}'에 연동된 근거(evidence) 문서가 존재하지 않아 검토 후보(candidate)로 하향 처리되었습니다.")

                    facts.append(GraphFact(
                        subject=rule_id,
                        relation="DEFINED_IN_APPENDIX",
                        object=plan.appendix,
                        confidence=1.0 if len(evs) > 0 else 0.5,
                        status=status,
                        evidence=evs,
                        properties=rule_props
                    ))

            facts = _dedupe_facts(facts)

            # 모든 fact에 대해 confirmed 이지만 evidence가 없는 경우 candidate로 강하 처리
            for fact in facts:
                fact.evidence = _sort_evidences(fact.evidence)
                if fact.status == "confirmed" and not fact.evidence:
                    fact.status = "candidate"
                    fact.confidence = 0.5

            # Warnings 구성
            warnings = list(result.warnings)
            has_candidate = any(f.status == "candidate" for f in facts)
            has_missing = any(f.status == "missing" for f in facts)
            if has_candidate:
                warnings.append("주의: 약관 매칭(POLICY_COVERS_PROCEDURE)은 confidence 0.8 이하의 추정(candidate) 관계입니다. 공식 지급 여부 판단 시 검토용 후보로만 활용해야 합니다.")
            if has_missing:
                warnings.append("알림: 일부 요청 항목(수가코드 혹은 약관 매핑 등)에 대한 구조화 데이터(missing)가 존재하지 않습니다.")
            if review_paths:
                warnings.append("알림: 문서 기반 검토 경로(graph review path)가 추가되어 자동 확정 대신 검토 중심으로 응답해야 할 수 있습니다.")

            result.facts = facts
            source_chunk_refs = _collect_source_chunk_refs(facts, review_paths)
            if source_chunk_ids:
                known_ids = {ref.requested_id for ref in source_chunk_refs}
                for chunk_id in sorted(source_chunk_ids):
                    if chunk_id not in known_ids:
                        source_chunk_refs.append(ChunkLookupRef(requested_id=chunk_id))
            result.source_chunk_ids = [ref.requested_id for ref in source_chunk_refs]
            result.source_chunk_refs = source_chunk_refs
            result.warnings = warnings
            result.debug = debug_info

        except Exception as e:
            result.warnings.append(f"Error during graph retrieval query execution: {e}")
        finally:
            store.close()

        return result


def _collect_source_chunk_refs(
    facts: list[GraphFact],
    review_paths: list[GraphReviewPath],
) -> list[ChunkLookupRef]:
    refs: list[ChunkLookupRef] = []
    seen: set[tuple[str, str | None, str | None, str, int | None, int | None]] = set()

    def append_evidence(evidence: GraphEvidence) -> None:
        if not evidence.chunk_id:
            return
        key = (
            evidence.chunk_id,
            evidence.canonical_chunk_id,
            evidence.source_chunk_id,
            evidence.doc_short,
            evidence.page_start,
            evidence.page_end,
        )
        if key in seen:
            return
        seen.add(key)
        refs.append(
            ChunkLookupRef(
                requested_id=evidence.chunk_id,
                canonical_chunk_id=evidence.canonical_chunk_id,
                source_chunk_id=evidence.source_chunk_id,
                doc_short=evidence.doc_short or None,
                page_start=evidence.page_start,
                page_end=evidence.page_end,
            )
        )

    for fact in facts:
        for evidence in fact.evidence:
            append_evidence(evidence)
    for path in review_paths:
        for step in path.steps:
            for evidence in step.evidence:
                append_evidence(evidence)
    return refs
