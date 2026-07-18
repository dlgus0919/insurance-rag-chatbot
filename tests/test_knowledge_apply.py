from __future__ import annotations

from src.ingest.knowledge_apply import KnowledgeApplyResult, apply_approved_knowledge


def test_apply_approved_knowledge_runs_steps_in_order(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {
            "status": "dry_run" if dry_run else "applied",
            "valid": True,
            "merged_candidate_count": 1,
        },
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda *, dry_run=False: calls.append(f"rules:{dry_run}") or {"applied_candidate_ids": ["rulecand.demo"]},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.collect_approved_intake_source_refs",
        lambda *_args: calls.append("collect_sources") or ["source-ref"],
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.promote_approved_sources",
        lambda refs: calls.append(f"promote_sources:{len(refs)}") or [{"status": "promoted"}],
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_search_indexes",
        lambda: calls.append("search-index") or None,
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert isinstance(result, KnowledgeApplyResult)
    assert calls == [
        "ontology:True",
        "rules:True",
        "collect_sources",
        "promote_sources:1",
        "ontology:False",
        "rules:False",
        "search-index",
        "graph",
    ]
    assert result.status == "completed"
    assert result.index_rebuilt is True
    assert result.graph_rebuilt is True
    assert result.sources == [{"status": "promoted"}]


def test_apply_approved_knowledge_stops_when_rule_preflight_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {
            "status": "dry_run" if dry_run else "applied",
            "valid": True,
            "merged_candidate_count": 1,
        },
    )

    def fail_rules(*, dry_run: bool = False):
        calls.append(f"rules:{dry_run}")
        raise ValueError("duplicate rule_id: demo")

    monkeypatch.setattr("src.ingest.knowledge_apply.apply_rule_candidates", fail_rules)
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.collect_approved_intake_source_refs",
        lambda *_args: calls.append("collect_sources") or [],
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_search_indexes",
        lambda: calls.append("search-index") or None,
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "failed_preflight"
    assert "duplicate rule_id" in result.rules["error"]
    assert calls == ["ontology:True", "rules:True"]


def test_apply_approved_knowledge_stops_before_other_steps_when_ontology_integrity_is_invalid(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {
            "status": "legacy_unverifiable",
            "valid": False,
            "legacy_unverifiable_candidate_ids": ["cand-legacy"],
        },
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda *, dry_run=False: calls.append(f"rules:{dry_run}") or {},
    )

    result = apply_approved_knowledge()

    assert result.status == "failed_preflight"
    assert result.ontology["status"] == "legacy_unverifiable"
    assert calls == ["ontology:True"]


def test_apply_approved_knowledge_stops_when_source_promotion_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {
            "status": "dry_run" if dry_run else "applied",
            "valid": True,
            "merged_candidate_count": 1,
        },
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda *, dry_run=False: calls.append(f"rules:{dry_run}") or {"applied_candidate_ids": []},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.collect_approved_intake_source_refs",
        lambda *_args: calls.append("collect_sources") or ["source-ref"],
    )

    def fail_promote(_refs):
        calls.append("promote_sources")
        raise FileNotFoundError("missing staging chunks")

    monkeypatch.setattr("src.ingest.knowledge_apply.promote_approved_sources", fail_promote)
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_search_indexes",
        lambda: calls.append("search-index") or None,
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "failed_preflight"
    assert result.index_rebuilt is False
    assert result.graph_rebuilt is False
    assert "missing staging chunks" in result.sources[0]["error"]
    assert calls == ["ontology:True", "rules:True", "collect_sources", "promote_sources"]
