from src.rag.auto_params import resolve_auto_rag_params


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
