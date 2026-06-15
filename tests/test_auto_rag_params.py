from types import SimpleNamespace

from src.rag.auto_params import (
    TOPK_STRATEGY_RERANKER_THRESHOLD,
    apply_adaptive_k_to_hits,
    resolve_auto_rag_params,
    select_adaptive_k,
)
from src.retrieval import Hit


def test_auto_params_apply_coverage_judgment_conservatively() -> None:
    decision = resolve_auto_rag_params(
        question="도수치료 보상돼?",
        mode="general",
        filters={},
        requested_top_k=20,
        requested_temperature=1.3,
        auto_params=None,
        config_mode="apply",
    )

    assert decision.effective is True
    assert decision.profile == "coverage_judgment"
    assert decision.effective_top_k == 10
    assert decision.effective_temperature == 0.0
    assert decision.requested_top_k == 20
    assert decision.requested_temperature == 1.3


def test_auto_params_manual_override_keeps_requested_values() -> None:
    decision = resolve_auto_rag_params(
        question="실손 세대별 차이를 설명해줘",
        mode="general",
        filters={},
        requested_top_k=14,
        requested_temperature=0.6,
        auto_params=False,
        config_mode="apply",
    )

    assert decision.effective is False
    assert decision.manual_override is True
    assert decision.effective_top_k == 14
    assert decision.effective_temperature == 0.6


def test_auto_params_non_general_route_keeps_specialized_path_values() -> None:
    decision = resolve_auto_rag_params(
        question="식도조루술 수가 코드 알려줘",
        mode="quickcode",
        filters={"include_summary": True},
        requested_top_k=9,
        requested_temperature=0.4,
        auto_params=True,
        config_mode="apply",
    )

    assert decision.effective is False
    assert decision.effective_top_k == 9
    assert decision.effective_temperature == 0.4


def test_auto_params_observe_records_suggestion_without_applying() -> None:
    decision = resolve_auto_rag_params(
        question="MRI와 MRA 보상 기준 설명해줘",
        mode="general",
        filters={},
        requested_top_k=10,
        requested_temperature=0.2,
        auto_params=None,
        config_mode="observe",
    )

    assert decision.effective is False
    assert decision.suggested_top_k == 10
    assert decision.suggested_temperature == 0.1
    assert decision.effective_top_k == 10
    assert decision.effective_temperature == 0.2


def test_auto_params_threshold_strategy_retrieves_profile_max_before_cutoff() -> None:
    decision = resolve_auto_rag_params(
        question="도수치료 보상돼?",
        mode="general",
        filters={},
        requested_top_k=5,
        requested_temperature=0.7,
        auto_params=True,
        config_mode="apply",
        top_k_strategy=TOPK_STRATEGY_RERANKER_THRESHOLD,
    )

    assert decision.effective is True
    assert decision.effective_top_k == 10
    assert decision.retrieval_top_k == 12
    assert decision.cutoff_reason == "post_reranker_threshold_pending"


def test_auto_params_loads_temperature_policy_file(tmp_path) -> None:
    policy_path = tmp_path / "temperature.json"
    policy_path.write_text(
        '{"profiles": {"coverage_judgment": 0.15}, "default": 0.05}',
        encoding="utf-8",
    )

    decision = resolve_auto_rag_params(
        question="도수치료 보상돼?",
        mode="general",
        filters={},
        requested_top_k=5,
        requested_temperature=0.7,
        auto_params=True,
        config_mode="apply",
        temperature_policy_path=policy_path,
        max_temperature=0.2,
    )

    assert decision.effective_temperature == 0.15


def test_auto_params_loads_profile_policy_file(tmp_path) -> None:
    policy_path = tmp_path / "profiles.json"
    policy_path.write_text(
        """
        {
          "defaults": {"top_k": 7, "min_top_k": 5, "max_top_k": 9, "temperature": 0.12},
          "profiles": {
            "coverage_judgment": {
              "top_k": 11,
              "min_top_k": 9,
              "max_top_k": 13,
              "temperature": 0.05
            }
          }
        }
        """,
        encoding="utf-8",
    )

    decision = resolve_auto_rag_params(
        question="도수치료 보상돼?",
        mode="general",
        filters={},
        requested_top_k=5,
        requested_temperature=0.7,
        auto_params=True,
        config_mode="apply",
        profile_policy_path=policy_path,
        max_temperature=0.2,
        top_k_strategy=TOPK_STRATEGY_RERANKER_THRESHOLD,
    )

    assert decision.effective_top_k == 11
    assert decision.retrieval_top_k == 13
    assert decision.min_top_k == 9
    assert decision.max_top_k == 13
    assert decision.effective_temperature == 0.05


def test_select_adaptive_k_uses_first_large_reranker_score_drop() -> None:
    decision = select_adaptive_k(
        [0.95, 0.91, 0.88, 0.48, 0.46],
        base_k=5,
        min_k=2,
        max_k=5,
        drop_abs=0.2,
        drop_ratio=0.3,
    )

    assert decision.selected_k == 3
    assert decision.cutoff_reason == "drop_abs"
    assert decision.applied is True


def test_apply_adaptive_k_preserves_required_graph_hit_after_cutoff() -> None:
    hits = [
        Hit(id=f"c{i}", score=1.0 - i * 0.1, document=f"chunk {i}", metadata={})
        for i in range(6)
    ]
    decision = resolve_auto_rag_params(
        question="AA157은 무엇인가요?",
        mode="general",
        filters={},
        requested_top_k=5,
        requested_temperature=0.7,
        auto_params=True,
        config_mode="apply",
        top_k_strategy=TOPK_STRATEGY_RERANKER_THRESHOLD,
    )
    reranker_scores = [
        SimpleNamespace(chunk_id="c0", score=0.95),
        SimpleNamespace(chunk_id="c1", score=0.9),
        SimpleNamespace(chunk_id="c2", score=0.86),
        SimpleNamespace(chunk_id="c3", score=0.82),
        SimpleNamespace(chunk_id="c4", score=0.48),
        SimpleNamespace(chunk_id="c5", score=0.47),
    ]

    selected, cutoff = apply_adaptive_k_to_hits(
        hits,
        reranker_scores,
        decision,
        drop_abs=0.2,
        preserve_chunk_ids={"c5"},
    )

    assert cutoff.selected_k == 4
    assert [hit.id for hit in selected] == ["c0", "c1", "c2", "c3", "c5"]


def test_apply_adaptive_k_preserves_first_hit_for_requested_doc() -> None:
    hits = [
        Hit(id="a1", score=0.95, document="a1", metadata={"doc_short": "약관"}),
        Hit(id="a2", score=0.9, document="a2", metadata={"doc_short": "약관"}),
        Hit(id="a3", score=0.86, document="a3", metadata={"doc_short": "약관"}),
        Hit(id="a4", score=0.82, document="a4", metadata={"doc_short": "약관"}),
        Hit(id="a5", score=0.8, document="a5", metadata={"doc_short": "약관"}),
        Hit(id="a6", score=0.78, document="a6", metadata={"doc_short": "약관"}),
        Hit(id="b1", score=0.48, document="b1", metadata={"doc_short": "표준약관"}),
    ]
    decision = resolve_auto_rag_params(
        question="AA157은 무엇인가요?",
        mode="general",
        filters={"doc_filter": ["약관", "표준약관"]},
        requested_top_k=5,
        requested_temperature=0.7,
        auto_params=True,
        config_mode="apply",
        top_k_strategy=TOPK_STRATEGY_RERANKER_THRESHOLD,
    )
    reranker_scores = [
        SimpleNamespace(chunk_id=hit.id, score=score)
        for hit, score in zip(hits, [0.95, 0.9, 0.86, 0.82, 0.8, 0.78, 0.48])
    ]

    selected, cutoff = apply_adaptive_k_to_hits(
        hits,
        reranker_scores,
        decision,
        drop_abs=0.2,
        preserve_doc_shorts={"약관", "표준약관"},
    )

    assert cutoff.selected_k == 6
    assert [hit.id for hit in selected] == ["a1", "a2", "a3", "a4", "a5", "a6", "b1"]
