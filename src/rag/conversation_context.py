"""Bounded, session-local state for evidence clarification turns.

This module deliberately stores only normalized slot selections.  A user's
free-form assertion is represented by its resolution type, not copied into
the persistent conversation state or promoted into ontology knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence
from uuid import uuid4


ConversationKind = Literal[
    "new_question",
    "clarification_response",
    "topic_switch",
    "ambiguous_continuation",
]
AssertionValue = Literal["yes", "no", "unknown", "asserted_alternative"]
AssertionResolution = Literal["confirmed", "unresolved"]

STATE_SCHEMA_VERSION = 1
MAX_HISTORY_MESSAGES = 40
MAX_SLOTS = 8
MAX_ASSERTIONS = 20
MAX_EVIDENCE_IDS_PER_SLOT = 8
_ALLOWED_VALUES = frozenset({"yes", "no", "unknown"})
_YES_VALUES = frozenset({"예", "네", "응", "맞아요", "맞습니다", "확인됐습니다", "확인되었습니다"})
_NO_VALUES = frozenset({"아니요", "아니", "아닙니다", "없어요", "없습니다"})
_UNKNOWN_VALUES = frozenset({"모름", "모르겠습니다", "알 수 없습니다", "미확인", "확인 전"})
_AMBIGUOUS_SHORT_VALUES = frozenset({"그건", "그것", "그거", "어떻게", "왜", "그래서"})


@dataclass(frozen=True)
class ConversationWarning:
    code: str
    message: str


@dataclass(frozen=True)
class ClarificationSlot:
    slot_id: str
    evidence_condition_id: str
    question: str
    allowed_values: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConversationQueryScope:
    route: str | None = None
    intent: str | None = None
    policy_generation: str | None = None
    doc_filter: tuple[str, ...] = ()
    index_mode: str | None = None


@dataclass(frozen=True)
class ClarificationRequest:
    schema_version: int
    request_id: str
    topic_anchor: str
    origin_turn_id: str
    status: Literal["pending", "resolved", "stale"]
    slots: tuple[ClarificationSlot, ...]
    ontology_manifest_hash: str
    query_scope: ConversationQueryScope


@dataclass(frozen=True)
class UserAssertion:
    assertion_id: str
    request_id: str
    slot_id: str
    value: AssertionValue
    resolution: AssertionResolution
    source_message_id: str | None
    supersedes: str | None


@dataclass(frozen=True)
class ConversationState:
    schema_version: int
    clarification_request: ClarificationRequest | None
    user_assertions: tuple[UserAssertion, ...]


@dataclass(frozen=True)
class ResolvedConversationContext:
    kind: ConversationKind
    current_question: str
    route_query: str
    retrieval_query: str
    topic_anchor: str | None
    query_scope: ConversationQueryScope
    graph_clarification: dict[str, list[dict[str, str]]] | None
    state_before: ConversationState
    state_after: ConversationState
    assertion_draft: UserAssertion | None
    pending_request: ClarificationRequest | None
    warnings: tuple[ConversationWarning, ...]


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _string_tuple(value: Any, field: str, *, limit: int | None = None) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{field} exceeds its limit")
    result = tuple(_require_string(item, field) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _parse_scope(value: Any) -> ConversationQueryScope:
    raw = _require_mapping(value, "query_scope")
    allowed = {"route", "intent", "policy_generation", "doc_filter", "index_mode"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError("query_scope contains unsupported fields")

    def optional(name: str) -> str | None:
        item = raw.get(name)
        if item is None:
            return None
        return _require_string(item, f"query_scope.{name}")

    doc_filter_raw = raw.get("doc_filter", [])
    return ConversationQueryScope(
        route=optional("route"),
        intent=optional("intent"),
        policy_generation=optional("policy_generation"),
        doc_filter=_string_tuple(doc_filter_raw, "query_scope.doc_filter", limit=20),
        index_mode=optional("index_mode"),
    )


def _parse_slot(value: Any) -> ClarificationSlot:
    raw = _require_mapping(value, "slot")
    required = {"slot_id", "evidence_condition_id", "question", "allowed_values", "evidence_chunk_ids"}
    if set(raw) != required:
        raise ValueError("slot fields are invalid")
    allowed_values = _string_tuple(raw["allowed_values"], "slot.allowed_values")
    if not set(allowed_values).issubset(_ALLOWED_VALUES) or not allowed_values:
        raise ValueError("slot.allowed_values are invalid")
    return ClarificationSlot(
        slot_id=_require_string(raw["slot_id"], "slot.slot_id"),
        evidence_condition_id=_require_string(raw["evidence_condition_id"], "slot.evidence_condition_id"),
        question=_require_string(raw["question"], "slot.question"),
        allowed_values=allowed_values,
        evidence_chunk_ids=_string_tuple(
            raw["evidence_chunk_ids"], "slot.evidence_chunk_ids", limit=MAX_EVIDENCE_IDS_PER_SLOT
        ),
    )


def _parse_request(value: Any) -> ClarificationRequest:
    raw = _require_mapping(value, "clarification_request")
    required = {
        "schema_version",
        "request_id",
        "topic_anchor",
        "origin_turn_id",
        "status",
        "slots",
        "ontology_manifest_hash",
        "query_scope",
    }
    if set(raw) != required or raw["schema_version"] != STATE_SCHEMA_VERSION:
        raise ValueError("clarification_request schema is invalid")
    status = raw["status"]
    if status not in {"pending", "resolved", "stale"}:
        raise ValueError("clarification_request.status is invalid")
    if not isinstance(raw["slots"], list) or len(raw["slots"]) > MAX_SLOTS:
        raise ValueError("clarification_request.slots are invalid")
    slots = tuple(_parse_slot(item) for item in raw["slots"])
    if len({slot.slot_id for slot in slots}) != len(slots):
        raise ValueError("clarification_request slots must be unique")
    return ClarificationRequest(
        schema_version=STATE_SCHEMA_VERSION,
        request_id=_require_string(raw["request_id"], "clarification_request.request_id"),
        topic_anchor=_require_string(raw["topic_anchor"], "clarification_request.topic_anchor"),
        origin_turn_id=_require_string(raw["origin_turn_id"], "clarification_request.origin_turn_id"),
        status=status,
        slots=slots,
        ontology_manifest_hash=_require_string(
            raw["ontology_manifest_hash"], "clarification_request.ontology_manifest_hash"
        ),
        query_scope=_parse_scope(raw["query_scope"]),
    )


def _parse_assertion(value: Any) -> UserAssertion:
    raw = _require_mapping(value, "assertion")
    required = {
        "assertion_id",
        "request_id",
        "slot_id",
        "value",
        "resolution",
        "source_message_id",
        "supersedes",
    }
    if set(raw) != required:
        raise ValueError("assertion fields are invalid")
    if raw["value"] not in {"yes", "no", "unknown", "asserted_alternative"}:
        raise ValueError("assertion.value is invalid")
    if raw["resolution"] not in {"confirmed", "unresolved"}:
        raise ValueError("assertion.resolution is invalid")

    def optional(name: str) -> str | None:
        item = raw[name]
        return None if item is None else _require_string(item, f"assertion.{name}")

    return UserAssertion(
        assertion_id=_require_string(raw["assertion_id"], "assertion.assertion_id"),
        request_id=_require_string(raw["request_id"], "assertion.request_id"),
        slot_id=_require_string(raw["slot_id"], "assertion.slot_id"),
        value=raw["value"],
        resolution=raw["resolution"],
        source_message_id=optional("source_message_id"),
        supersedes=optional("supersedes"),
    )


def parse_conversation_state(value: Any) -> ConversationState:
    raw = _require_mapping(value, "conversation_state")
    required = {"schema_version", "clarification_request", "user_assertions"}
    if set(raw) != required or raw["schema_version"] != STATE_SCHEMA_VERSION:
        raise ValueError("conversation_state schema is invalid")
    request = None if raw["clarification_request"] is None else _parse_request(raw["clarification_request"])
    assertions_raw = raw["user_assertions"]
    if not isinstance(assertions_raw, list) or len(assertions_raw) > MAX_ASSERTIONS:
        raise ValueError("conversation_state assertions are invalid")
    assertions = tuple(_parse_assertion(item) for item in assertions_raw)
    if len({item.assertion_id for item in assertions}) != len(assertions):
        raise ValueError("conversation_state assertion ids must be unique")
    if request is not None:
        known_slots = {slot.slot_id for slot in request.slots}
        if any(item.request_id != request.request_id or item.slot_id not in known_slots for item in assertions):
            raise ValueError("conversation_state assertion does not match its request")
    elif assertions:
        raise ValueError("conversation_state assertions require a request")
    return ConversationState(
        schema_version=STATE_SCHEMA_VERSION,
        clarification_request=request,
        user_assertions=assertions,
    )


def serialize_conversation_state(state: ConversationState) -> dict[str, Any]:
    if state.schema_version != STATE_SCHEMA_VERSION:
        raise ValueError("conversation_state schema is invalid")

    def slot_payload(slot: ClarificationSlot) -> dict[str, Any]:
        return {
            "slot_id": slot.slot_id,
            "evidence_condition_id": slot.evidence_condition_id,
            "question": slot.question,
            "allowed_values": list(slot.allowed_values),
            "evidence_chunk_ids": list(slot.evidence_chunk_ids),
        }

    request = state.clarification_request
    request_payload = None
    if request is not None:
        request_payload = {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "topic_anchor": request.topic_anchor,
            "origin_turn_id": request.origin_turn_id,
            "status": request.status,
            "slots": [slot_payload(slot) for slot in request.slots],
            "ontology_manifest_hash": request.ontology_manifest_hash,
            "query_scope": {
                "route": request.query_scope.route,
                "intent": request.query_scope.intent,
                "policy_generation": request.query_scope.policy_generation,
                "doc_filter": list(request.query_scope.doc_filter),
                "index_mode": request.query_scope.index_mode,
            },
        }
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "clarification_request": request_payload,
        "user_assertions": [
            {
                "assertion_id": assertion.assertion_id,
                "request_id": assertion.request_id,
                "slot_id": assertion.slot_id,
                "value": assertion.value,
                "resolution": assertion.resolution,
                "source_message_id": assertion.source_message_id,
                "supersedes": assertion.supersedes,
            }
            for assertion in state.user_assertions
        ],
    }
    parse_conversation_state(payload)
    return payload


def empty_conversation_state() -> ConversationState:
    return ConversationState(
        schema_version=STATE_SCHEMA_VERSION,
        clarification_request=None,
        user_assertions=(),
    )


def _assistant_state_payload(message: Mapping[str, Any]) -> Any:
    if message.get("role") != "assistant":
        return None
    sources = message.get("sources")
    if not isinstance(sources, Mapping):
        return None
    assistant_meta = sources.get("assistant_meta")
    if not isinstance(assistant_meta, Mapping):
        return None
    return assistant_meta.get("conversation_state")


def restore_conversation_state(
    history: Sequence[Mapping[str, Any]], *, current_manifest_hash: str | None
) -> tuple[ConversationState, tuple[ConversationWarning, ...]]:
    warnings: list[ConversationWarning] = []
    restored: ConversationState | None = None
    for message in reversed(history[-MAX_HISTORY_MESSAGES:]):
        payload = _assistant_state_payload(message)
        if payload is None:
            continue
        if isinstance(payload, Mapping) and payload.get("schema_version") == 0:
            continue
        try:
            state = parse_conversation_state(payload)
        except ValueError:
            warnings.append(
                ConversationWarning("MALFORMED_CONVERSATION_STATE", "이전 확인 상태를 안전하게 무시했습니다.")
            )
            continue
        if restored is not None:
            continue
        request = state.clarification_request
        if (
            request is not None
            and request.status == "pending"
            and current_manifest_hash
            and request.ontology_manifest_hash != current_manifest_hash
        ):
            stale_request = replace(request, status="stale", slots=())
            warnings.append(
                ConversationWarning("STALE_CONVERSATION_STATE", "지식 기준이 바뀌어 이전 확인 상태를 다시 확인해야 합니다.")
            )
            return replace(state, clarification_request=stale_request), tuple(warnings)
        restored = state
    return restored or empty_conversation_state(), tuple(warnings)


def _normalize_text(question: str) -> str:
    return " ".join(question.strip().lower().split())


def _is_independent_question(question: str) -> bool:
    compact = _normalize_text(question)
    if not compact:
        return False
    inquiry_ending = question.rstrip().endswith(("?", "알려주세요.", "알려주세요", "인가요?", "인가요."))
    return inquiry_ending and len(compact) >= 12 and not any(token in compact for token in _AMBIGUOUS_SHORT_VALUES)


def _infer_free_text_value(question: str) -> tuple[AssertionValue, AssertionResolution] | None:
    compact = _normalize_text(question)
    if compact in _YES_VALUES:
        return "yes", "confirmed"
    if compact in _NO_VALUES:
        return "no", "confirmed"
    if compact in _UNKNOWN_VALUES:
        return "unknown", "confirmed"
    if compact.startswith(("아니", "다른", "별도", "변경")) and len(compact) <= 80:
        return "asserted_alternative", "unresolved"
    return None


def _assertion(
    request: ClarificationRequest,
    slot: ClarificationSlot,
    value: AssertionValue,
    resolution: AssertionResolution,
) -> UserAssertion:
    return UserAssertion(
        assertion_id=f"assertion-{uuid4().hex}",
        request_id=request.request_id,
        slot_id=slot.slot_id,
        value=value,
        resolution=resolution,
        source_message_id=None,
        supersedes=None,
    )


def _state_with_assertion(state: ConversationState, assertion: UserAssertion) -> ConversationState:
    retained = tuple(
        item
        for item in state.user_assertions
        if not (item.request_id == assertion.request_id and item.slot_id == assertion.slot_id)
    )
    request = state.clarification_request
    if request is None:
        return state
    assertions = (retained + (assertion,))[-MAX_ASSERTIONS:]
    confirmed_slots = {
        item.slot_id
        for item in assertions
        if item.request_id == request.request_id and item.resolution == "confirmed"
    }
    request_status: Literal["pending", "resolved", "stale"] = (
        "resolved" if all(slot.slot_id in confirmed_slots for slot in request.slots) else "pending"
    )
    return ConversationState(
        schema_version=STATE_SCHEMA_VERSION,
        clarification_request=replace(request, status=request_status),
        user_assertions=assertions,
    )


def _scope_or_default(request: ClarificationRequest | None) -> ConversationQueryScope:
    return request.query_scope if request is not None else ConversationQueryScope()


def resolve_conversation_context(
    question: str,
    history: Sequence[Mapping[str, Any]],
    *,
    current_manifest_hash: str | None,
    clarification: Mapping[str, Any] | None = None,
) -> ResolvedConversationContext:
    normalized_question = question.strip()
    state, warnings = restore_conversation_state(history, current_manifest_hash=current_manifest_hash)
    request = state.clarification_request
    if request is None or request.status != "pending" or not request.slots:
        return ResolvedConversationContext(
            kind="new_question",
            current_question=normalized_question,
            route_query=normalized_question,
            retrieval_query=normalized_question,
            topic_anchor=None,
            query_scope=_scope_or_default(request),
            graph_clarification=None,
            state_before=state,
            state_after=state,
            assertion_draft=None,
            pending_request=None,
            warnings=warnings,
        )

    if _is_independent_question(normalized_question):
        return ResolvedConversationContext(
            kind="topic_switch",
            current_question=normalized_question,
            route_query=normalized_question,
            retrieval_query=normalized_question,
            topic_anchor=None,
            query_scope=ConversationQueryScope(),
            graph_clarification=None,
            state_before=state,
            state_after=empty_conversation_state(),
            assertion_draft=None,
            pending_request=None,
            warnings=warnings,
        )

    confirmed_slot_ids = {
        assertion.slot_id
        for assertion in state.user_assertions
        if assertion.request_id == request.request_id and assertion.resolution == "confirmed"
    }
    slot = next((item for item in request.slots if item.slot_id not in confirmed_slot_ids), None)
    if slot is None:
        return ResolvedConversationContext(
            kind="new_question",
            current_question=normalized_question,
            route_query=normalized_question,
            retrieval_query=normalized_question,
            topic_anchor=None,
            query_scope=_scope_or_default(request),
            graph_clarification=None,
            state_before=state,
            state_after=state,
            assertion_draft=None,
            pending_request=None,
            warnings=warnings,
        )
    chosen: tuple[AssertionValue, AssertionResolution] | None = None
    if clarification is not None:
        if clarification.get("request_id") != request.request_id or clarification.get("slot_id") != slot.slot_id:
            warnings = warnings + (
                ConversationWarning("INVALID_CLARIFICATION_SELECTION", "이전 확인 항목을 다시 선택해 주세요."),
            )
        else:
            raw_value = clarification.get("value")
            if isinstance(raw_value, str) and raw_value in slot.allowed_values:
                chosen = raw_value, "confirmed"
            else:
                warnings = warnings + (
                    ConversationWarning("INVALID_CLARIFICATION_SELECTION", "선택값을 확인할 수 없습니다."),
                )
    else:
        chosen = _infer_free_text_value(normalized_question)

    if chosen is None:
        return ResolvedConversationContext(
            kind="ambiguous_continuation",
            current_question=normalized_question,
            route_query=request.topic_anchor,
            retrieval_query=request.topic_anchor,
            topic_anchor=request.topic_anchor,
            query_scope=request.query_scope,
            graph_clarification=None,
            state_before=state,
            state_after=state,
            assertion_draft=None,
            pending_request=request,
            warnings=warnings,
        )

    value, resolution = chosen
    assertion = _assertion(request, slot, value, resolution)
    updated_state = _state_with_assertion(state, assertion)
    graph_clarification = {"selections": [{"group": slot.evidence_condition_id, "value": value}]}
    return ResolvedConversationContext(
        kind="clarification_response",
        current_question=normalized_question,
        route_query=request.topic_anchor,
        retrieval_query=request.topic_anchor,
        topic_anchor=request.topic_anchor,
        query_scope=request.query_scope,
        graph_clarification=graph_clarification,
        state_before=state,
        state_after=updated_state,
        assertion_draft=assertion,
        pending_request=(updated_state.clarification_request if updated_state.clarification_request and updated_state.clarification_request.status == "pending" else None),
        warnings=warnings,
    )


def create_clarification_request(
    *,
    topic_anchor: str,
    origin_turn_id: str,
    ontology_manifest_hash: str,
    query_scope: ConversationQueryScope,
    slots: Sequence[ClarificationSlot],
) -> ClarificationRequest:
    request = ClarificationRequest(
        schema_version=STATE_SCHEMA_VERSION,
        request_id=f"clarification-{uuid4().hex}",
        topic_anchor=_require_string(topic_anchor, "topic_anchor"),
        origin_turn_id=_require_string(origin_turn_id, "origin_turn_id"),
        status="pending",
        slots=tuple(slots),
        ontology_manifest_hash=_require_string(ontology_manifest_hash, "ontology_manifest_hash"),
        query_scope=query_scope,
    )
    parse_conversation_state(
        serialize_conversation_state(
            ConversationState(schema_version=STATE_SCHEMA_VERSION, clarification_request=request, user_assertions=())
        )
    )
    return request


def finalize_assertion_source(
    state: ConversationState, *, source_message_id: str | None
) -> ConversationState:
    if source_message_id is None:
        return state
    return replace(
        state,
        user_assertions=tuple(
            replace(assertion, source_message_id=source_message_id)
            if assertion.source_message_id is None
            else assertion
            for assertion in state.user_assertions
        ),
    )


def state_with_pending_clarification(
    state: ConversationState,
    *,
    topic_anchor: str,
    origin_turn_id: str,
    ontology_manifest_hash: str,
    query_scope: ConversationQueryScope,
    slots: Sequence[ClarificationSlot],
) -> ConversationState:
    """Attach a bounded pending request without changing approved knowledge."""

    normalized_slots = tuple(slots)
    if not normalized_slots or not ontology_manifest_hash:
        return state
    existing = state.clarification_request
    if (
        existing is not None
        and existing.status in {"pending", "resolved"}
        and existing.topic_anchor == topic_anchor
        and existing.ontology_manifest_hash == ontology_manifest_hash
    ):
        known_slot_ids = {slot.slot_id for slot in existing.slots}
        merged_slots = existing.slots + tuple(
            slot for slot in normalized_slots if slot.slot_id not in known_slot_ids
        )
        confirmed_slot_ids = {
            assertion.slot_id
            for assertion in state.user_assertions
            if assertion.request_id == existing.request_id and assertion.resolution == "confirmed"
        }
        status: Literal["pending", "resolved", "stale"] = (
            "resolved" if all(slot.slot_id in confirmed_slot_ids for slot in merged_slots) else "pending"
        )
        return ConversationState(
            schema_version=STATE_SCHEMA_VERSION,
            clarification_request=replace(existing, slots=merged_slots, status=status),
            user_assertions=state.user_assertions,
        )
    request = create_clarification_request(
        topic_anchor=topic_anchor,
        origin_turn_id=origin_turn_id,
        ontology_manifest_hash=ontology_manifest_hash,
        query_scope=query_scope,
        slots=normalized_slots,
    )
    return ConversationState(
        schema_version=STATE_SCHEMA_VERSION,
        clarification_request=request,
        user_assertions=(),
    )
