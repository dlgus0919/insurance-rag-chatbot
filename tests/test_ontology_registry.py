from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graph.query_planner import GraphQueryPlanner
from src.ontology.approval_integrity import BaseManifestLock, manifest_content_hash
from src.ontology.registry import (
    OntologyConcept,
    OntologyRegistry,
    RetrievalExpansionRule,
    get_default_ontology_registry,
    resolve_default_ontology_manifest,
)
from scripts.check_ontology_sync import check_registry


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _trusted_base(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "version": "base",
        "concepts": [
            {
                "concept_id": "cond.valid",
                "canonical_name": "검증된 조건",
                "node_type": "ClaimCondition",
                "aliases": ["검증 표현"],
                "planner": {"conditions": ["검증된 조건"]},
            }
        ],
    }
    base_path = _write_json(tmp_path / "concepts.json", payload)
    lock_path = tmp_path / "base_manifest.lock.json"
    BaseManifestLock.from_manifest(
        payload,
        source_commit="trusted",
        review_record_id="review-record",
    ).write(lock_path)
    return payload, base_path, lock_path


def _provenance(
    active: dict[str, object],
    lock: BaseManifestLock,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-18T00:00:00+00:00",
        "base_lock": lock.to_dict(),
        "trusted_base_content_hash": lock.manifest_content_hash,
        "active_content_hash": manifest_content_hash(active),
        "quarantined_concept_ids": [],
        "integrity_issues": [],
        "applied_operations": [],
    }


def _active_with_valid_and_unproven_concepts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    base, base_path, lock_path = _trusted_base(tmp_path)
    active = {
        **base,
        "version": "active",
        "concepts": [
            *base["concepts"],
            {
                "concept_id": "cond.unproven",
                "canonical_name": "격리 조건",
                "node_type": "ClaimCondition",
                "aliases": ["격리 표현"],
                "planner": {"conditions": ["격리 조건"]},
            },
        ],
    }
    active_path = _write_json(tmp_path / "concepts.active.json", active)
    lock = BaseManifestLock.load(lock_path)
    provenance_path = _write_json(
        tmp_path / "concepts.active.provenance.json",
        _provenance(active, lock),
    )
    return active_path, base_path, lock_path, provenance_path


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
    registry = OntologyRegistry(manifest_path, enforce_integrity=False)

    planner = GraphQueryPlanner(ontology_registry=registry)
    plan = planner.plan("새보험특례로 보상 가능한가요?")

    assert "새보험 특례" in plan.conditions
    assert "신규 약관 특례" in registry.expand_retrieval_query("새보험특례로 보상 가능한가요?")
    assert check_registry(registry) == []


def test_ontology_concept_preserves_legacy_positional_constructor_layout() -> None:
    expansion_rule = RetrievalExpansionRule(
        match_any=("legacy match",),
        expansion_terms=("legacy expansion",),
    )

    concept = OntologyConcept(
        "cond.legacy",
        "기존 호출 호환",
        "ClaimCondition",
        ("기존 별칭",),
        ("보장 주제",),
        ("조건",),
        ("의도",),
        ("청구 단위",),
        ("추가 질문",),
        ("필수 근거",),
        ("후보 별칭",),
        ("근거 태그",),
        (expansion_rule,),
        ("검색 우선어",),
        {"source": "legacy-call"},
    )

    assert concept.candidate_aliases == ("후보 별칭",)
    assert concept.evidence_tags == ("근거 태그",)
    assert concept.retrieval_expansion_rules == (expansion_rule,)
    assert concept.retrieval_lexical_priority_terms == ("검색 우선어",)
    assert concept.properties == {"source": "legacy-call"}
    assert concept.planner_required_context == ()
    assert concept.planner_clarification_fields == ()
    assert concept.planner_evidence_categories == ()


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

    errors = check_registry(OntologyRegistry(manifest_path, enforce_integrity=False))

    assert errors == ["bad.retrieval_only: retrieval expansion exists without planner mapping"]


def test_ontology_sync_check_rejects_candidate_alias_quality_issues(tmp_path) -> None:
    manifest = {
        "schema_version": "1.0",
        "version": "test",
        "concepts": [
            {
                "concept_id": "cov.one",
                "canonical_name": "첫 보장",
                "candidate_aliases": ["즉 비급여 도수치료", "비급여 주사제"],
                "planner": {"coverage_topics": ["첫 보장"]},
            },
            {
                "concept_id": "cov.two",
                "canonical_name": "둘째 보장",
                "candidate_aliases": ["비급여 주사제"],
                "planner": {"coverage_topics": ["둘째 보장"]},
            },
        ],
    }
    manifest_path = tmp_path / "concepts.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    errors = check_registry(OntologyRegistry(manifest_path, enforce_integrity=False))

    assert any("sentence-like evidence text" in error for error in errors)
    assert any("maps to multiple concepts" in error for error in errors)


def test_resolve_default_ontology_manifest_prefers_env(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "custom_concepts.json"
    manifest_path.write_text('{"schema_version":"1.0","version":"test","concepts":[]}', encoding="utf-8")

    monkeypatch.setenv("INSURANCE_ONTOLOGY_MANIFEST", str(manifest_path))

    assert resolve_default_ontology_manifest() == manifest_path


def test_registry_excludes_only_unproven_active_concepts(tmp_path: Path) -> None:
    active_path, base_path, lock_path, provenance_path = _active_with_valid_and_unproven_concepts(tmp_path)

    registry = OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=provenance_path,
    )

    assert [concept.concept_id for concept in registry.concepts] == ["cond.valid"]
    assert registry.integrity_report.state == "legacy_unverifiable"
    assert registry.integrity_report.quarantined_concept_ids == ("cond.unproven",)
    assert registry.find_matches("격리 표현") == []
    assert registry.find_matches("검증 표현")[0].concept_id == "cond.valid"


def test_registry_hides_all_concepts_when_active_provenance_is_missing(tmp_path: Path) -> None:
    active_path, base_path, lock_path, _provenance_path = _active_with_valid_and_unproven_concepts(tmp_path)

    registry = OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=tmp_path / "missing.provenance.json",
    )

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"
    assert registry.integrity_report.issue_counts()["ACTIVE_PROVENANCE_UNAVAILABLE"] == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("description", "changed manifest description"),
        ("schema_version", "2.0"),
    ],
)
def test_registry_hides_all_concepts_when_base_manifest_top_level_hash_drifts(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    base, base_path, lock_path = _trusted_base(tmp_path)
    base[field] = replacement
    _write_json(base_path, base)

    registry = OntologyRegistry(base_path, base_lock_path=lock_path)

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"
    assert registry.integrity_report.issue_counts()["BASE_MANIFEST_HASH_MISMATCH"] == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("description", "unapproved active description"),
        ("schema_version", "2.0"),
    ],
)
def test_registry_hides_all_concepts_when_active_top_level_metadata_drifts(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    base, base_path, lock_path = _trusted_base(tmp_path)
    active = {**base, "version": "active", field: replacement}
    active_path = _write_json(tmp_path / "concepts.active.json", active)
    lock = BaseManifestLock.load(lock_path)
    provenance_path = _write_json(
        tmp_path / "concepts.active.provenance.json",
        _provenance(active, lock),
    )

    registry = OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=provenance_path,
    )

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"
    assert registry.integrity_report.issue_counts() == {
        "UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA": 1
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("rogue_top_level", True),
        lambda payload: payload.pop("version"),
        lambda payload: payload.__setitem__("concepts", [{"concept_id": "cond.valid"}]),
    ],
)
def test_registry_hides_all_concepts_when_base_manifest_schema_is_invalid(
    tmp_path: Path,
    mutate,
) -> None:
    base, base_path, lock_path = _trusted_base(tmp_path)
    mutate(base)
    _write_json(base_path, base)

    registry = OntologyRegistry(base_path, base_lock_path=lock_path)

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("schema_version", 0),
        lambda payload: payload.pop("generated_at"),
        lambda payload: payload.__setitem__("rogue_top_level", True),
        lambda payload: payload.__setitem__("integrity_issues", ["not-an-object"]),
    ],
)
def test_registry_hides_all_concepts_when_active_provenance_schema_is_invalid(
    tmp_path: Path,
    mutate,
) -> None:
    active_path, base_path, lock_path, provenance_path = _active_with_valid_and_unproven_concepts(tmp_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    mutate(provenance)
    _write_json(provenance_path, provenance)

    registry = OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=provenance_path,
    )

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"


def test_registry_hides_all_concepts_when_active_manifest_has_rogue_top_level_field(
    tmp_path: Path,
) -> None:
    active_path, base_path, lock_path, provenance_path = _active_with_valid_and_unproven_concepts(tmp_path)
    active = json.loads(active_path.read_text(encoding="utf-8"))
    active["rogue_top_level"] = True
    _write_json(active_path, active)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["active_content_hash"] = manifest_content_hash(active)
    _write_json(provenance_path, provenance)

    registry = OntologyRegistry(
        active_path,
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        provenance_path=provenance_path,
    )

    assert registry.concepts == []
    assert registry.integrity_report.state == "stale"


def test_registry_reports_graph_manifest_integrity_mismatch(tmp_path: Path) -> None:
    _payload, base_path, lock_path = _trusted_base(tmp_path)
    registry = OntologyRegistry(base_path, base_lock_path=lock_path)

    expected = registry.graph_manifest_metadata()

    assert registry.graph_manifest_integrity_errors(expected) == []
    mismatched = dict(expected)
    mismatched["ontology_manifest_content_hash"] = "stale-hash"
    assert registry.graph_manifest_integrity_errors(mismatched) == [
        "ontology_manifest_content_hash: expected "
        f"{expected['ontology_manifest_content_hash']}, got stale-hash"
    ]


def test_registry_reports_missing_required_graph_metadata_even_when_expected_empty(
    tmp_path: Path,
) -> None:
    _payload, base_path, lock_path = _trusted_base(tmp_path)
    registry = OntologyRegistry(base_path, base_lock_path=lock_path)
    expected = registry.graph_manifest_metadata()
    assert expected["ontology_provenance_content_hash"] == ""
    missing = dict(expected)
    missing.pop("ontology_provenance_content_hash")

    assert registry.graph_manifest_integrity_errors(missing) == [
        "ontology_provenance_content_hash: expected <empty>, got <missing>"
    ]
