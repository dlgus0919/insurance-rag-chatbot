import hashlib
import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.query_planner import GraphQueryPlanner
from src.graph.store import GraphStore
from src.ontology.registry import OntologyRegistry


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "ontology" / "concepts.json"
LOCK_PATH = ROOT / "data" / "ontology" / "policies" / "base_manifest.lock.json"
AUDIT_PATH = (
    ROOT
    / "docs"
    / "review_artifacts"
    / "2026-07-19-v1.2.0-practitioner-decision-audit.json"
)

APPROVED_IDS = {
    "evidence.claim_document_requirements",
    "cond.claim_payment_timeline",
    "cond.korean_medicine_treatment_context",
    "cond.dental_treatment_classification",
    "cond.foreign_medical_institution",
    "cond.nonclaim_history_discount",
}
APPROVED_ACTIVE_ALIASES = {
    "evidence.claim_document_requirements": [
        "보험금 청구 서류",
        "청구 구비서류",
        "추가 청구서류",
    ],
    "cond.claim_payment_timeline": [
        "보험금 지급기일",
        "보험금 지급 지연 사유",
        "지급예정일",
    ],
    "cond.korean_medicine_treatment_context": [
        "한방 치료",
        "한의원 진료",
        "한방 의료기관",
    ],
    "cond.dental_treatment_classification": [
        "치과 치료",
        "치과 질환",
        "치아 질환",
    ],
    "cond.foreign_medical_institution": [
        "해외 의료기관",
        "해외 진료",
        "외국 의료기관",
    ],
    "cond.nonclaim_history_discount": ["무사고 할인", "무청구 할인"],
}
REJECTED_IDS = {
    "cond.policy_source_authority",
    "dev.cov.indemnity_medical.2f8f7057fb90",
    "dev.cond.motorcycle_riding.fc842c72db6f",
    "dev.cov.superior_room_difference.d1fad7d62df5",
    "cov.hair_loss",
    "cond.age_related_hair_loss",
    "cond.disease_related_hair_loss",
    "cond.treatment_side_effect_hair_loss",
    "cond.work_daily_life_impairment",
    "cond.pay_nonpay_status",
}
LEGACY_HELD_CANDIDATE_IDS = {
    "dev.cov.indemnity_medical.2f8f7057fb90",
    "dev.cond.motorcycle_riding.fc842c72db6f",
    "dev.cov.superior_room_difference.d1fad7d62df5",
}
FROZEN_FILES = {
    "data/rules/claim_deductible_rules.active.json": (
        "ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818"
    ),
    "data/rules/rule_links.active.json": (
        "ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9"
    ),
    "src/claim_calculation/processing_policy.py": (
        "5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f"
    ),
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v120_practitioner_projection_contains_only_approved_general_concepts():
    manifest = _load_json(MANIFEST_PATH)
    concepts = {row["concept_id"]: row for row in manifest["concepts"]}

    assert manifest["version"] == "v1.2.0"
    assert len(concepts) == 55
    assert sum(len(aliases) for aliases in APPROVED_ACTIVE_ALIASES.values()) == 17
    assert APPROVED_IDS <= concepts.keys()
    assert not (REJECTED_IDS & concepts.keys())

    for concept_id, approved_aliases in APPROVED_ACTIVE_ALIASES.items():
        concept = concepts[concept_id]
        assert concept["aliases"] == approved_aliases
        assert not concept.get("candidate_aliases")

    discount = concepts["cond.nonclaim_history_discount"]
    encoded_discount = json.dumps(discount, ensure_ascii=False)
    assert "비급여 보험료 차등제" not in encoded_discount

    for concept_id in APPROVED_IDS:
        concept = concepts[concept_id]
        encoded = json.dumps(concept, ensure_ascii=False)
        assert "runtime_decision" not in concept.get("properties", {})
        assert "deductible" not in encoded.casefold()
        assert "payable" not in encoded.casefold()
        assert "150,000" not in encoded
        assert "350,000" not in encoded
        assert "30%" not in encoded
        assert "?" not in encoded

    registry = OntologyRegistry(
        MANIFEST_PATH,
        base_manifest_path=MANIFEST_PATH,
        base_lock_path=LOCK_PATH,
    )
    assert registry.integrity_summary()["state"] == "valid"
    assert len(registry.concepts) == 55


def test_v120_default_runtime_registry_excludes_unapproved_hair_payloads():
    registry = OntologyRegistry(
        MANIFEST_PATH,
        base_manifest_path=MANIFEST_PATH,
        base_lock_path=LOCK_PATH,
    )
    runtime_concept_ids = {concept.concept_id for concept in registry.concepts}
    rejected_hair_ids = {
        "cov.hair_loss",
        "cond.age_related_hair_loss",
        "cond.disease_related_hair_loss",
        "cond.treatment_side_effect_hair_loss",
        "cond.work_daily_life_impairment",
        "cond.pay_nonpay_status",
    }

    assert not (rejected_hair_ids & runtime_concept_ids)
    assert not registry.find_matches("탈모 보상 가능?")
    assert not [
        payload
        for payload in registry.approved_decision_profile_payloads()
        if payload.get("concept_id") in rejected_hair_ids
    ]

    plan = GraphQueryPlanner(ontology_registry=registry).plan("탈모 보상 가능?")
    assert plan.coverage_topics == []
    assert plan.conditions == []
    assert plan.clarification_questions == []
    assert plan.required_evidence == []


def test_v120_practitioner_decision_audit_preserves_rejections_without_runtime_payload():
    audit = _load_json(AUDIT_PATH)
    decisions = {row["concept_id"]: row for row in audit["decisions"]}
    decisions_by_candidate = {
        row["candidate_id"]: row
        for row in audit["decisions"]
        if row.get("candidate_id")
    }

    assert audit["status"] == "implemented_in_isolated_candidate"
    assert {row["concept_id"] for row in audit["runtime_projection"]} == APPROVED_IDS
    assert decisions["cond.policy_source_authority"]["decision"] == "rejected"
    for concept_id in REJECTED_IDS - {
        "cond.policy_source_authority",
        *LEGACY_HELD_CANDIDATE_IDS,
    }:
        assert decisions[concept_id]["decision"] == "rejected"
        assert decisions[concept_id]["runtime_included"] is False
    for candidate_id in LEGACY_HELD_CANDIDATE_IDS:
        assert decisions_by_candidate[candidate_id]["decision"] == "rejected"
        assert decisions_by_candidate[candidate_id]["runtime_included"] is False


def test_v120_keeps_active_claim_calculation_boundary_frozen():
    for relative_path, expected_hash in FROZEN_FILES.items():
        assert _hash(ROOT / relative_path) == expected_hash


def test_v120_approved_aliases_seed_into_candidate_graph_only(tmp_path: Path):
    registry = OntologyRegistry(
        MANIFEST_PATH,
        base_manifest_path=MANIFEST_PATH,
        base_lock_path=LOCK_PATH,
    )
    store = GraphStore(tmp_path / "candidate.sqlite", build_mode=True)
    try:
        PolicyReviewExtractor(store, ontology_registry=registry)._seed_ontology_registry_nodes()
        store.commit()
        seeded_ids = {
            row["node_id"]
            for row in store.query(
                "SELECT node_id FROM graph_nodes WHERE created_by = 'ontology_registry'"
            )
        }
        aliases_by_node = {
            concept.node_id: {
                row["alias"]
                for row in store.query(
                    """
                    SELECT alias FROM graph_aliases
                    WHERE node_id = ? AND source = 'ontology_registry'
                    """,
                    (concept.node_id,),
                )
            }
            for concept in registry.concepts_for_graph_seed()
        }
    finally:
        store.close()

    concept_by_id = {concept.concept_id: concept for concept in registry.concepts_for_graph_seed()}
    for concept_id, approved_aliases in APPROVED_ACTIVE_ALIASES.items():
        concept = concept_by_id[concept_id]
        assert concept.node_id in seeded_ids
        assert set(approved_aliases).issubset(aliases_by_node[concept.node_id])

    assert not (REJECTED_IDS & concept_by_id.keys())
    assert all(
        "비급여 보험료 차등제" not in aliases
        for aliases in aliases_by_node.values()
    )
