from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.graph.normalizer import normalize_name
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphFact, GraphRetriever, GraphRetrievalResult
from src.graph.schema import Alias, Edge, Evidence, Node, EdgeType, NodeType
from src.graph.store import GraphStore


@pytest.fixture
def populated_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name

    store = GraphStore(path)

    # 1. Nodes
    # SurgeryProcedure
    proc1 = Node(
        node_id="proc_bronchial",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="기관지 식도루 폐쇄술",
        normalized_name="기관지식도루폐쇄술"
    )
    proc2 = Node(
        node_id="proc_lung_transplant",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="폐장 이식수술",
        normalized_name="폐장이식수술"
    )
    # Digestive category grade 5 procedures
    proc_liver = Node(
        node_id="proc_liver_transplant",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="간장 이식수술",
        normalized_name="간장이식수술"
    )
    proc_pancreas = Node(
        node_id="proc_pancreas_transplant",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="췌장 이식수술",
        normalized_name="췌장이식수술"
    )

    # SurgeryGrade
    grade4 = Node(
        node_id="grade_new_1_5_4",
        node_type=NodeType.SurgeryGrade,
        canonical_name="신1-5종 4종",
        normalized_name="신15종4종",
        properties={"payment_ratio": "50%"}
    )
    grade5 = Node(
        node_id="grade_new_1_5_5",
        node_type=NodeType.SurgeryGrade,
        canonical_name="신1-5종 5종",
        normalized_name="신15종5종",
        properties={"payment_ratio": "100%"}
    )

    # SurgeryCategory
    cat_resp = Node(
        node_id="cat_respiratory",
        node_type=NodeType.SurgeryCategory,
        canonical_name="호흡기계",
        normalized_name="호흡기계"
    )
    cat_dig = Node(
        node_id="cat_digestive",
        node_type=NodeType.SurgeryCategory,
        canonical_name="소화기계",
        normalized_name="소화기계"
    )

    # MedicalFeeCode
    fee_liver = Node(
        node_id="fee_liver_001",
        node_type=NodeType.MedicalFeeCode,
        canonical_name="QZ966",
        normalized_name="qz966"
    )

    # PolicyBenefitRule
    rule18 = Node(
        node_id="rule_sol_18",
        node_type=NodeType.PolicyBenefitRule,
        canonical_name="SOL 처음건강보험 별표7 18번",
        normalized_name="sol처음건강보험별표718번",
        properties={"appendix_number": "18", "grade_value": "4", "payment_ratio": "50%"}
    )

    for n in [proc1, proc2, proc_liver, proc_pancreas, grade4, grade5, cat_resp, cat_dig, fee_liver, rule18]:
        store.upsert_node(n)

    # 2. Evidence
    ev1 = Evidence(
        evidence_id="ev_001",
        chunk_id="chk_001",
        doc_short="자사_SOL건강",
        page_start=384,
        row_text="[별표7] 18. 기관지 식도루 폐쇄술 - 4종"
    )
    store.upsert_evidence(ev1)

    # 3. Edges
    # Has Grade (Exact mappings)
    edge_g1 = Edge(
        edge_id="edge_g_bronchial",
        source_node_id="proc_bronchial",
        target_node_id="grade_new_1_5_4",
        edge_type=EdgeType.HAS_GRADE,
        confidence=1.0,
        source_evidence_id="ev_001"
    )
    edge_g2 = Edge(
        edge_id="edge_g_lung",
        source_node_id="proc_lung_transplant",
        target_node_id="grade_new_1_5_4",
        edge_type=EdgeType.HAS_GRADE,
        confidence=1.0,
        source_evidence_id="ev_001"
    )
    edge_g3 = Edge(
        edge_id="edge_g_liver",
        source_node_id="proc_liver_transplant",
        target_node_id="grade_new_1_5_5",
        edge_type=EdgeType.HAS_GRADE,
        confidence=1.0,
        source_evidence_id="ev_001"
    )
    edge_g4 = Edge(
        edge_id="edge_g_pancreas",
        source_node_id="proc_pancreas_transplant",
        target_node_id="grade_new_1_5_5",
        edge_type=EdgeType.HAS_GRADE,
        confidence=1.0,
        source_evidence_id="ev_001"
    )

    # Has Category
    edge_c1 = Edge(
        edge_id="edge_c_bronchial",
        source_node_id="proc_bronchial",
        target_node_id="cat_respiratory",
        edge_type=EdgeType.HAS_CATEGORY,
        confidence=1.0
    )
    edge_c2 = Edge(
        edge_id="edge_c_liver",
        source_node_id="proc_liver_transplant",
        target_node_id="cat_digestive",
        edge_type=EdgeType.HAS_CATEGORY,
        confidence=1.0
    )
    edge_c3 = Edge(
        edge_id="edge_c_pancreas",
        source_node_id="proc_pancreas_transplant",
        target_node_id="cat_digestive",
        edge_type=EdgeType.HAS_CATEGORY,
        confidence=1.0
    )

    # Policy Covers Procedure (Confidence 0.8)
    edge_p1 = Edge(
        edge_id="edge_p_bronchial",
        source_node_id="rule_sol_18",
        target_node_id="proc_bronchial",
        edge_type=EdgeType.POLICY_COVERS_PROCEDURE,
        confidence=0.8,
        source_evidence_id="ev_001"
    )

    # Medical Fee Code
    edge_f1 = Edge(
        edge_id="edge_f_liver",
        source_node_id="proc_liver_transplant",
        target_node_id="fee_liver_001",
        edge_type=EdgeType.HAS_MEDICAL_FEE_CODE,
        confidence=1.0,
        source_evidence_id="ev_001"
    )

    for e in [edge_g1, edge_g2, edge_g3, edge_g4, edge_c1, edge_c2, edge_c3, edge_p1, edge_f1]:
        store.upsert_edge(e)
        if e.source_evidence_id:
            store.link_edge_evidence(e.edge_id, e.source_evidence_id, "support")

    store.commit()
    store.close()

    yield path
    try:
        Path(path).unlink()
    except OSError:
        pass


def test_retriever_hard_query_1(populated_db: str) -> None:
    retriever = GraphRetriever(populated_db)
    query = (
        "기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, "
        "이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. "
        "그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘."
    )
    result = retriever.retrieve(query)

    assert len(result.facts) > 0

    # 1. Check Grade Fact (confirmed)
    grade_facts = [f for f in result.facts if f.relation == "HAS_GRADE" and f.subject == "기관지 식도루 폐쇄술"]
    assert len(grade_facts) == 1
    assert grade_facts[0].object == "신1-5종 4종"
    assert grade_facts[0].status == "confirmed"
    assert len(grade_facts[0].evidence) == 1
    assert grade_facts[0].evidence[0].chunk_id == "chk_001"
    assert "chk_001" in result.source_chunk_ids

    # 2. Check Peer Fact
    peer_facts = [f for f in result.facts if f.relation == "SAME_GRADE_PEER"]
    assert len(peer_facts) >= 1
    assert peer_facts[0].subject == "폐장 이식수술"

    # 3. Check Policy Covers Fact (candidate)
    policy_facts = [f for f in result.facts if f.relation == "POLICY_COVERS_PROCEDURE"]
    assert len(policy_facts) == 1
    assert policy_facts[0].status == "candidate"  # POLICY_COVERS_PROCEDURE must be candidate
    assert policy_facts[0].properties.get("appendix_number") == "18"


def test_retriever_hard_query_2(populated_db: str) -> None:
    retriever = GraphRetriever(populated_db)
    query = (
        "신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 "
        "소화기계 카테고리에서 모두 나열해줘. "
        "각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘."
    )
    result = retriever.retrieve(query)

    # Check that digestive grade 5 surgeries are fetched: 간장 이식수술, 췌장 이식수술
    facts = result.facts
    assert len(facts) > 0

    # Liver Transplant: has fee code (confirmed), missing policy (missing)
    liver_fee = [f for f in facts if f.subject == "간장 이식수술" and f.relation == "HAS_MEDICAL_FEE_CODE"]
    assert len(liver_fee) == 1
    assert liver_fee[0].object == "QZ966"
    assert liver_fee[0].status == "confirmed"

    # Pancreas Transplant: missing fee code (missing), missing policy (missing)
    pancreas_fee = [f for f in facts if f.subject == "췌장 이식수술" and f.relation == "HAS_MEDICAL_FEE_CODE"]
    assert len(pancreas_fee) == 1
    assert pancreas_fee[0].object is None
    assert pancreas_fee[0].status == "missing"


def test_retriever_missing_db() -> None:
    # Testing graceful fallback on non-existent DB
    retriever = GraphRetriever("non_existent_db_12345.sqlite")
    result = retriever.retrieve("기관지 식도루 폐쇄술의 수술 등급을 알려줘.")

    assert len(result.facts) == 0
    assert len(result.warnings) == 1
    assert "not found" in result.warnings[0]
