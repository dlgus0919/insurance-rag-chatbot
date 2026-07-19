from __future__ import annotations

from dataclasses import replace

import pytest

from src.rag.conversation_context import (
    ClarificationRequest,
    ClarificationSlot,
    ConversationQueryScope,
    ConversationState,
    UserAssertion,
    parse_conversation_state,
    resolve_conversation_context,
    restore_conversation_state,
    serialize_conversation_state,
    state_with_pending_clarification,
)


def _state(*, manifest_hash: str = "manifest-v1") -> ConversationState:
    return ConversationState(
        schema_version=1,
        clarification_request=ClarificationRequest(
            schema_version=1,
            request_id="request-1",
            topic_anchor="직전 보상 판단",
            origin_turn_id="turn-1",
            status="pending",
            slots=(
                ClarificationSlot(
                    slot_id="condition-a",
                    evidence_condition_id="condition-a",
                    question="해당 조건이 확인되었나요?",
                    allowed_values=("yes", "no", "unknown"),
                    evidence_chunk_ids=("chunk-1",),
                ),
            ),
            ontology_manifest_hash=manifest_hash,
            query_scope=ConversationQueryScope(
                route="claim_review",
                intent="coverage_review",
                policy_generation="4th",
                doc_filter=("policy-a",),
                index_mode="v2_only",
            ),
        ),
        user_assertions=(),
    )


def _history(state: ConversationState) -> list[dict[str, object]]:
    return [
        {
            "role": "assistant",
            "content": "확인할 조건이 있습니다.",
            "sources": {
                "assistant_meta": {
                    "conversation_state": serialize_conversation_state(state),
                }
            },
        }
    ]


def _two_slot_state() -> ConversationState:
    state = _state()
    request = state.clarification_request
    assert request is not None
    second_slot = replace(
        request.slots[0],
        slot_id="condition-b",
        evidence_condition_id="condition-b",
        question="다음 조건도 확인되었나요?",
    )
    return replace(state, clarification_request=replace(request, slots=(request.slots[0], second_slot)))


def test_conversation_state_round_trip_excludes_raw_user_text() -> None:
    payload = serialize_conversation_state(_state())

    assert payload["schema_version"] == 1
    assert "user_text" not in repr(payload)
    assert parse_conversation_state(payload) == _state()


def test_restore_ignores_legacy_and_malformed_rows() -> None:
    state, warnings = restore_conversation_state(
        [
            {"role": "assistant", "sources": {"assistant_meta": {"conversation_state": {"schema_version": 0}}}},
            {"role": "assistant", "sources": {"assistant_meta": {"conversation_state": {"schema_version": 1}}}},
            *_history(_state()),
        ],
        current_manifest_hash="manifest-v1",
    )

    assert state == _state()
    assert [warning.code for warning in warnings] == ["MALFORMED_CONVERSATION_STATE"]


def test_restore_marks_pending_request_stale_when_manifest_changes() -> None:
    state, warnings = restore_conversation_state(
        _history(_state()),
        current_manifest_hash="manifest-v2",
    )

    assert state.clarification_request is not None
    assert state.clarification_request.status == "stale"
    assert state.clarification_request.slots == ()
    assert [warning.code for warning in warnings] == ["STALE_CONVERSATION_STATE"]


def test_state_bounds_reject_excessive_slots_and_assertions() -> None:
    state = _state()
    request = state.clarification_request
    assert request is not None
    too_many_slots = tuple(replace(request.slots[0], slot_id=f"s-{index}") for index in range(9))

    with pytest.raises(ValueError, match="slots"):
        serialize_conversation_state(replace(state, clarification_request=replace(request, slots=too_many_slots)))

    too_many_assertions = tuple(
        UserAssertion(
            assertion_id=f"assertion-{index}",
            request_id="request-1",
            slot_id="condition-a",
            value="yes",
            resolution="confirmed",
            source_message_id=None,
            supersedes=None,
        )
        for index in range(21)
    )
    with pytest.raises(ValueError, match="assertions"):
        serialize_conversation_state(replace(state, user_assertions=too_many_assertions))


def test_explicit_selection_resolves_pending_slot_without_asking_again() -> None:
    resolved = resolve_conversation_context(
        "예, 해당 조건이 확인되었습니다.",
        _history(_state()),
        current_manifest_hash="manifest-v1",
        clarification={"request_id": "request-1", "slot_id": "condition-a", "value": "yes"},
    )

    assert resolved.kind == "clarification_response"
    assert resolved.assertion_draft is not None
    assert resolved.assertion_draft.value == "yes"
    assert resolved.pending_request is None
    assert resolved.route_query == "직전 보상 판단"
    assert resolved.graph_clarification == {"selections": [{"group": "condition-a", "value": "yes"}]}


def test_free_text_yes_and_short_alternative_are_session_assertions() -> None:
    yes = resolve_conversation_context(
        "네", _history(_state()), current_manifest_hash="manifest-v1"
    )
    alternative = resolve_conversation_context(
        "아니요, 다른 진단으로 확인됐습니다.",
        _history(_state()),
        current_manifest_hash="manifest-v1",
    )

    assert yes.kind == "clarification_response"
    assert yes.assertion_draft is not None and yes.assertion_draft.value == "yes"
    assert alternative.kind == "clarification_response"
    assert alternative.assertion_draft is not None
    assert alternative.assertion_draft.value == "asserted_alternative"
    assert alternative.assertion_draft.resolution == "unresolved"


def test_pending_second_slot_preserves_confirmed_first_assertion_and_request() -> None:
    state = _two_slot_state()
    first = resolve_conversation_context(
        "예, 첫 번째 조건이 확인되었습니다.",
        _history(state),
        current_manifest_hash="manifest-v1",
        clarification={"request_id": "request-1", "slot_id": "condition-a", "value": "yes"},
    )
    assert first.assertion_draft is not None
    request = first.state_after.clarification_request
    assert request is not None

    updated = state_with_pending_clarification(
        first.state_after,
        topic_anchor=request.topic_anchor,
        origin_turn_id="turn-2",
        ontology_manifest_hash="manifest-v1",
        query_scope=request.query_scope,
        slots=(request.slots[1],),
    )

    updated_request = updated.clarification_request
    assert updated_request is not None
    assert updated_request.request_id == "request-1"
    assert [slot.slot_id for slot in updated_request.slots] == ["condition-a", "condition-b"]
    assert [assertion.slot_id for assertion in updated.user_assertions] == ["condition-a"]

    second = resolve_conversation_context(
        "예, 두 번째 조건도 확인되었습니다.",
        _history(updated),
        current_manifest_hash="manifest-v1",
        clarification={"request_id": "request-1", "slot_id": "condition-b", "value": "yes"},
    )
    assert second.assertion_draft is not None
    assert second.assertion_draft.slot_id == "condition-b"
    assert second.pending_request is None

    repeated = state_with_pending_clarification(
        second.state_after,
        topic_anchor=request.topic_anchor,
        origin_turn_id="turn-3",
        ontology_manifest_hash="manifest-v1",
        query_scope=request.query_scope,
        slots=request.slots,
    )
    assert repeated == second.state_after


def test_independent_question_switches_topic_and_ambiguous_short_text_stays_safe() -> None:
    topic_switch = resolve_conversation_context(
        "새로운 약관의 통원 공제 기준을 알려주세요.",
        _history(_state()),
        current_manifest_hash="manifest-v1",
    )
    ambiguous = resolve_conversation_context(
        "그건 어떻게 되나요?", _history(_state()), current_manifest_hash="manifest-v1"
    )

    assert topic_switch.kind == "topic_switch"
    assert topic_switch.current_question == "새로운 약관의 통원 공제 기준을 알려주세요."
    assert topic_switch.pending_request is None
    assert ambiguous.kind == "ambiguous_continuation"
    assert ambiguous.pending_request is not None
