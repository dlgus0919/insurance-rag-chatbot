from types import SimpleNamespace

from src.claim_calculation.thread_context import (
    build_claim_thread_context,
    contextualize_claim_query,
    extract_claim_snapshots,
    select_active_claim_snapshot,
    snapshot_state,
)


def _snapshot_message(snapshot: dict) -> SimpleNamespace:
    return SimpleNamespace(
        role="assistant",
        content="보험금 계산 결과",
        sources=[{"__kind": "assistant_meta", "claim_snapshot": snapshot}],
    )


def test_thread_context_includes_completed_line_details() -> None:
    snapshot = {
        "schema_version": 2,
        "state": "completed",
        "result": {
            "line_results": [
                {
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                }
            ],
        },
    }

    context = build_claim_thread_context([_snapshot_message(snapshot)], "그 계산을 설명해줘")

    assert "도수치료" in context.prompt_context
    assert "3대비급여" in context.prompt_context
    assert "청구 150000원" in context.prompt_context
    assert "공제 45000원" in context.prompt_context
    assert "지급 105000원" in context.prompt_context


def test_latest_completed_snapshot_is_default_after_candidate_selection() -> None:
    snapshots = [
        {"schema_version": 2, "state": "candidate_pending", "claim_id": "candidate"},
        {"schema_version": 2, "state": "completed", "claim_id": "completed"},
    ]

    selected = select_active_claim_snapshot(snapshots, "그 계산에서 왜 공제됐나요?")

    assert selected is not None
    assert selected["state"] == "completed"


def test_v1_snapshot_with_candidates_is_compatible_candidate_pending() -> None:
    snapshot = {
        "schema_version": 1,
        "result": {"candidates": [{"code": "MX122", "name": "도수치료"}]},
    }

    assert snapshot_state(snapshot) == "candidate_pending"


def test_v2_snapshot_preserves_explicit_conditional_state() -> None:
    snapshot = {"schema_version": 2, "state": "conditional", "result": {}}

    assert snapshot_state(snapshot) == "conditional"


def test_extract_claim_snapshots_only_uses_assistant_meta_sources() -> None:
    assistant = _snapshot_message({"schema_version": 1, "result": {}})
    user = SimpleNamespace(
        role="user",
        content="보험금 계산을 요청합니다.",
        sources=[{"__kind": "assistant_meta", "claim_snapshot": {"schema_version": 1}}],
    )

    snapshots = extract_claim_snapshots([assistant, user])

    assert snapshots == [{"schema_version": 1, "result": {}}]


def test_contextualizes_retrieval_only_for_claim_references() -> None:
    snapshot = {
        "schema_version": 2,
        "state": "completed",
        "input": {"context": {"policy_generation": "4th"}},
        "result": {
            "line_results": [
                {
                    "input_name": "도수치료",
                    "category": "3대비급여",
                    "claimed_amount": "150000",
                    "deductible": "45000",
                    "payable_amount": "105000",
                    "calculation_status": "calculated",
                }
            ]
        },
    }
    history = [_snapshot_message(snapshot)]

    referenced = build_claim_thread_context(history, "그 계산의 공제금액이 나온 이유는 무엇인가요?")
    independent = build_claim_thread_context(history, "N39.3 진단코드의 보장 여부를 알려주세요.")

    assert referenced.references_claim is True
    assert "도수치료" in contextualize_claim_query("그 계산의 공제금액이 나온 이유는 무엇인가요?", referenced)
    assert independent.references_claim is False
    assert contextualize_claim_query("N39.3 진단코드의 보장 여부를 알려주세요.", independent) == "N39.3 진단코드의 보장 여부를 알려주세요."
