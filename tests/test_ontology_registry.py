from __future__ import annotations

import json

from src.graph.query_planner import GraphQueryPlanner
from src.ontology.registry import OntologyRegistry, get_default_ontology_registry, resolve_default_ontology_manifest
from scripts.check_ontology_sync import check_registry


def test_default_ontology_registry_loads_runtime_indexes() -> None:
    registry = get_default_ontology_registry()

    diagnostics = registry.diagnostics()
    assert diagnostics["concept_count"] >= 30
    assert diagnostics["retrieval_rule_count"] >= 4
    assert "실손" in registry.coverage_topics
    assert registry.term_aliases["실손"][:2] == ("실손", "실비")
    assert registry.term_candidate_aliases["MRI"] == ("엠알아이", "엠알 아이")


def test_registry_expands_retrieval_query_from_manifest() -> None:
    registry = get_default_ontology_registry()

    expanded = registry.expand_retrieval_query("이륜자동차를 운전하다가 사고가 났습니다.")

    assert "이륜자동차 부담보 특별약관" in expanded
    assert "알릴 의무" in expanded


def test_query_planner_uses_registry_for_motorcycle_condition() -> None:
    planner = GraphQueryPlanner()
    plan = planner.plan("이륜자동차를 타다 사고가 났는데 보상되나요?")

    assert "이륜자동차 운전/탑승" in plan.conditions
    assert "claim_condition_lookup" in plan.intents
    assert "session_claim_path_review" in plan.intents


def test_custom_manifest_adds_new_concept_without_planner_code_change(tmp_path) -> None:
    manifest = {
        "schema_version": "1.0",
        "version": "test",
        "concepts": [
            {
                "concept_id": "cond.new_policy_exception",
                "canonical_name": "새보험 특례",
                "node_type": "ClaimCondition",
                "aliases": ["새보험특례", "신상품 특례"],
                "planner": {
                    "conditions": ["새보험 특례"],
                    "intents": ["claim_condition_lookup", "session_claim_path_review"],
                },
                "retrieval": {
                    "expansion_rules": [
                        {
                            "match_any": ["새보험특례"],
                            "expansion_terms": ["신규 약관 특례", "추가 심사 필요"],
                        }
                    ]
                },
            }
        ],
    }
    manifest_path = tmp_path / "concepts.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    registry = OntologyRegistry(manifest_path)

    planner = GraphQueryPlanner(ontology_registry=registry)
    plan = planner.plan("새보험특례로 보상 가능한가요?")

    assert "새보험 특례" in plan.conditions
    assert "신규 약관 특례" in registry.expand_retrieval_query("새보험특례로 보상 가능한가요?")
    assert check_registry(registry) == []


def test_ontology_sync_check_rejects_retrieval_only_concept(tmp_path) -> None:
    manifest = {
        "schema_version": "1.0",
        "version": "test",
        "concepts": [
            {
                "concept_id": "bad.retrieval_only",
                "canonical_name": "검색 전용",
                "aliases": ["검색전용"],
                "retrieval": {
                    "expansion_rules": [
                        {"match_any": ["검색전용"], "expansion_terms": ["확장어"]}
                    ]
                },
            }
        ],
    }
    manifest_path = tmp_path / "concepts.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    errors = check_registry(OntologyRegistry(manifest_path))

    assert errors == ["bad.retrieval_only: retrieval expansion exists without planner mapping"]


def test_resolve_default_ontology_manifest_prefers_env(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "custom_concepts.json"
    manifest_path.write_text('{"schema_version":"1.0","version":"test","concepts":[]}', encoding="utf-8")

    monkeypatch.setenv("INSURANCE_ONTOLOGY_MANIFEST", str(manifest_path))

    assert resolve_default_ontology_manifest() == manifest_path
