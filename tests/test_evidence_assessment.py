from __future__ import annotations

from src.parser.chunker import Chunk
from src.api.rag_service import graph_payload_has_renderable_evidence
from src.api.routes.chat import _public_graph_payload
from src.rag.conversation_context import (
    ClarificationRequest,
    ClarificationSlot,
    ConversationQueryScope,
    ConversationState,
    ResolvedConversationContext,
    UserAssertion,
)
from src.rag.evidence_assessment import (
    ApprovedDecisionProfile,
    evaluate_approved_evidence,
)


def _profile() -> ApprovedDecisionProfile:
    return ApprovedDecisionProfile.from_dict(
        {
            "profile_id": "profile-1",
            "concept_id": "test.concept",
            "approval_operation_path": "/concepts/0/properties/approved_decision_profiles/0",
            "query_terms": ["검토 대상"],
            "evidence_terms": ["직접 조항", "비급여"],
            "direct_source_chunk_ids": {"4th": ["direct-4th"]},
            "effect": "exclusion",
            "supported_summary": "직접 조항의 적용 조건이 확인됐습니다.",
            "unresolved_summary": "직접 조항은 확인됐지만 적용 조건을 더 확인해야 합니다.",
            "required_evidence": ["진단서"],
            "conditions": [
                {
                    "condition_id": "condition-a",
                    "question": "해당 조건이 확인되었나요?",
                    "allowed_values": ["yes", "no", "unknown"],
                    "required_values": ["yes"],
                    "evidence_chunk_ids": ["direct-4th"],
                }
            ],
        }
    )


def _chunk(*, direct: bool = True, own_company: bool | None = True) -> Chunk:
    return Chunk(
        id="direct-4th" if direct else "other",
        text="직접 조항에 따른 비급여 의료비 검토 문구",
        metadata={
            "policy_generation": "4th",
            "is_own_company": own_company,
            "doc_short": "약관" if own_company else "표준약관",
            "product_type": "표준약관" if own_company is False else "보험약관",
            "page_start": 12,
        },
    )


def _context(*, assertion: UserAssertion | None = None) -> ResolvedConversationContext:
    slot = ClarificationSlot(
        slot_id="condition-a",
        evidence_condition_id="condition-a",
        question="해당 조건이 확인되었나요?",
        allowed_values=("yes", "no", "unknown"),
        evidence_chunk_ids=("direct-4th",),
    )
    request = ClarificationRequest(
        schema_version=1,
        request_id="request-1",
        topic_anchor="검토 대상 보상 여부",
        origin_turn_id="turn-1",
        status="pending",
        slots=(slot,),
        ontology_manifest_hash="manifest-1",
        query_scope=ConversationQueryScope(policy_generation="4th"),
    )
    before = ConversationState(schema_version=1, clarification_request=request, user_assertions=())
    assertions = () if assertion is None else (assertion,)
    after = ConversationState(schema_version=1, clarification_request=request, user_assertions=assertions)
    return ResolvedConversationContext(
        kind="new_question",
        current_question="검토 대상 보상 여부",
        route_query="검토 대상 보상 여부",
        retrieval_query="검토 대상 보상 여부",
        topic_anchor=None,
        query_scope=request.query_scope,
        graph_clarification=None,
        state_before=before,
        state_after=after,
        assertion_draft=assertion,
        pending_request=request,
        warnings=(),
    )


def test_direct_approved_profile_yields_canonical_pending_clarification() -> None:
    result = evaluate_approved_evidence(
        "검토 대상 보상 여부",
        [_chunk()],
        [_profile()],
        policy_generation="4th",
        context=_context(),
    )

    assert result is not None
    assert result.status == "clarification_required"
    assert result.answer.startswith("직접 조항은 확인됐지만")
    assert result.selected_chunks[0].id == "direct-4th"
    assert result.payload["schema_version"] == 2
    assert result.payload["clarification"]["pending_slots"][0]["slot_id"] == "condition-a"
    assert result.payload["evidence_assessment"]["authority"] == "own"


def test_actual_evaluator_payload_has_the_schema_v2_display_contract() -> None:
    result = evaluate_approved_evidence(
        "검토 대상 보상 여부",
        [_chunk()],
        [_profile()],
        policy_generation="4th",
        context=_context(),
    )

    assert result is not None
    assert result.payload["display"]["primary_text"] == result.payload["evidence_assessment"]["summary"]
    assert graph_payload_has_renderable_evidence(result.payload) is True

    public_payload = _public_graph_payload(result.payload)
    assert public_payload is not None
    assert public_payload["display"] == result.payload["display"]
    assert public_payload["evidence_assessment"]["conditions"] == [
        {"question": "해당 조건이 확인되었나요?", "state": "unresolved"}
    ]


def test_session_assertion_changes_applicability_not_source_authority() -> None:
    assertion = UserAssertion(
        assertion_id="assertion-1",
        request_id="request-1",
        slot_id="condition-a",
        value="yes",
        resolution="confirmed",
        source_message_id=None,
        supersedes=None,
    )
    result = evaluate_approved_evidence(
        "검토 대상 보상 여부",
        [_chunk(own_company=False)],
        [_profile()],
        policy_generation="4th",
        context=_context(assertion=assertion),
    )

    assert result is not None
    assert result.status == "supported"
    assert result.answer.startswith("직접 조항의 적용 조건")
    assert result.payload["evidence_assessment"]["authority"] == "standard"
    assert result.payload["evidence_assessment"]["conditions"][0]["state"] == "satisfied"


def test_profile_requires_approved_direct_source_not_only_matching_text() -> None:
    assert (
        evaluate_approved_evidence(
            "검토 대상 보상 여부",
            [_chunk(direct=False)],
            [_profile()],
            policy_generation="4th",
            context=_context(),
        )
        is None
    )
