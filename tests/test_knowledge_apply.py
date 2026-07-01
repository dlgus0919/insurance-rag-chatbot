from __future__ import annotations

from src.ingest.knowledge_apply import KnowledgeApplyResult, apply_approved_knowledge


def test_apply_approved_knowledge_runs_steps_in_order(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda: calls.append("ontology") or {"merged_candidate_count": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda: calls.append("rules") or {"applied_candidate_ids": ["rulecand.demo"]},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert isinstance(result, KnowledgeApplyResult)
    assert calls == ["ontology", "rules", "graph"]
    assert result.status == "completed"
