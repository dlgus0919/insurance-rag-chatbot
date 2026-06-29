from __future__ import annotations

from src.claim_calculation.thread_recalculation import (
    RecalculationIntent,
    build_recalculation_payload,
    detect_recalculation_intent,
    find_target_line,
    find_target_lines,
    select_claim_snapshot,
)


SNAPSHOT = {
    "result": {
        "line_results": [
            {"input_name": "도수치료", "category": "3대비급여", "claimed_amount": "150000"},
            {
                "input_name": "미분류 비급여",
                "category": "미분류 비급여",
                "claimed_amount": "120000",
                "human_task_amount": "120000",
                "calculation_status": "human_task",
            },
        ]
    }
}


def test_detects_not_covered_condition() -> None:
    intent = detect_recalculation_intent("미분류 비급여 항목을 보상하지 않는다면 얼마인가요?")

    assert intent is not None
    assert intent.action == "not_covered"
    assert intent.target_text == "미분류 비급여"


def test_detects_insured_copay_condition() -> None:
    intent = detect_recalculation_intent("미분류 비급여가 급여 본인부담으로 확인됐다면 다시 계산해 주세요")

    assert intent is not None
    assert intent.action == "as_insured_copay"
    assert intent.target_text == "미분류 비급여"


def test_covered_without_category_requires_clarification() -> None:
    intent = detect_recalculation_intent("미분류 비급여를 보상한다면 얼마인가요?")

    assert intent is not None
    assert intent.action == "covered_unspecified"
    assert intent.target_text == "미분류 비급여"
    assert intent.needs_clarification is True


def test_explicit_nonpay_category_wins_over_unspecified_covered() -> None:
    intent = detect_recalculation_intent("도수치료를 비급여로 보상한다면")

    assert intent is not None
    assert intent.action == "as_nonpay"
    assert intent.target_text == "도수치료"
    assert intent.needs_clarification is False


def test_explicit_nonpay_category_uses_nearest_target_marker() -> None:
    intent = detect_recalculation_intent("가산료를 비급여로 계산하면")

    assert intent is not None
    assert intent.action == "as_nonpay"
    assert intent.target_text == "가산료"


def test_explicit_three_major_nonpay_category_wins_over_unspecified_covered() -> None:
    intent = detect_recalculation_intent("도수치료를 3대비급여로 보상한다면")

    assert intent is not None
    assert intent.action == "as_three_major_nonpay"
    assert intent.target_text == "도수치료"
    assert intent.needs_clarification is False


def test_detects_not_covered_with_topic_particle() -> None:
    intent = detect_recalculation_intent("미분류 비급여는 보상 제외인가요?")

    assert intent is not None
    assert intent.action == "not_covered"
    assert intent.target_text == "미분류 비급여"


def test_detects_not_covered_with_object_particle_before_condition() -> None:
    intent = detect_recalculation_intent("도수치료를 보상하지 않는다면")

    assert intent is not None
    assert intent.action == "not_covered"
    assert intent.target_text == "도수치료"


def test_nonpay_exclusion_context_is_not_loose_nonpay_reclassification() -> None:
    intent = detect_recalculation_intent("도수치료를 비급여 보상 대상에서 제외하면")

    assert intent is None


def test_find_target_line_by_substring() -> None:
    line = find_target_line(SNAPSHOT, "미분류 비급여")

    assert line is not None
    assert line["claimed_amount"] == "120000"


def test_find_target_line_does_not_match_generic_category_target() -> None:
    line = find_target_line(SNAPSHOT, "비급여")

    assert line is None


def test_find_target_lines_reports_ambiguous_substring_matches() -> None:
    snapshot = {
        "result": {
            "line_results": [
                {"line_id": "line-1", "input_name": "비타민D 주사", "category": "미분류 비급여"},
                {"line_id": "line-2", "input_name": "비타민D 검사", "category": "미분류 비급여"},
            ]
        }
    }

    matches = find_target_lines(snapshot, "비타민D")

    assert [line["line_id"] for line in matches] == ["line-1", "line-2"]


def test_select_claim_snapshot_requires_clarification_when_multiple_without_selector() -> None:
    snapshots = [{"claim_id": "claim-1"}, {"claim_id": "claim-2"}]

    selected, clarification = select_claim_snapshot(snapshots, "이 항목을 보상하지 않는다면?")

    assert selected is None
    assert "여러 건" in clarification
    assert "최근 계산" in clarification


def test_select_claim_snapshot_uses_latest_when_query_says_recent() -> None:
    snapshots = [{"claim_id": "claim-1"}, {"claim_id": "claim-2"}]

    selected, clarification = select_claim_snapshot(snapshots, "최근 계산 기준으로 비타민D 주사를 보상하지 않는다면?")

    assert selected == snapshots[-1]
    assert clarification == ""


def test_build_recalculation_payload_reclassifies_target_line_only() -> None:
    snapshot = {
        "input": {
            "items": [
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "claimed_amount": "150000",
                    "insured_copay_amount": "0",
                    "nonpay_amount": "150000",
                    "quantity": "1",
                    "user_category_hint": "3대비급여",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "claimed_amount": "48000",
                    "insured_copay_amount": "0",
                    "nonpay_amount": "48000",
                    "quantity": "1",
                    "user_category_hint": "",
                },
            ],
            "context": {"policy_generation": "4th", "visit_type": "outpatient", "coverage_topic": "실손"},
        },
        "result": {
            "line_results": [
                {"line_id": "line-1", "input_name": "도수치료", "claimed_amount": "150000"},
                {"line_id": "line-2", "input_name": "비타민D 주사", "claimed_amount": "48000"},
            ]
        },
    }
    intent = RecalculationIntent(action="as_insured_copay", target_text="비타민D 주사")
    target_line = find_target_lines(snapshot, "비타민D 주사")[0]

    payload = build_recalculation_payload(snapshot, intent, target_line)

    assert payload["items"][0]["input_name"] == "도수치료"
    assert payload["items"][0]["user_category_hint"] == "3대비급여"
    assert payload["items"][1]["input_name"] == "비타민D 주사"
    assert payload["items"][1]["insured_copay_amount"] == "48000"
    assert payload["items"][1]["nonpay_amount"] == "0"
    assert payload["items"][1]["user_category_hint"] == "급여 본인부담"
    assert payload["context"]["policy_generation"] == "4th"


def test_build_recalculation_payload_rejects_non_payload_actions() -> None:
    intent = RecalculationIntent(action="not_covered", target_text="미분류 비급여")

    try:
        build_recalculation_payload(SNAPSHOT, intent, SNAPSHOT["result"]["line_results"][1])
    except ValueError as exc:
        assert "직접 변환할 수 없는 의도" in str(exc)
    else:
        raise AssertionError("not_covered intent must not silently produce an unchanged payload")
