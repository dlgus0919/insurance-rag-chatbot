"""Generic, provenance-gated evidence assessment for RAG responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from src.parser.chunker import Chunk
from src.rag.conversation_context import ClarificationSlot, ResolvedConversationContext


DecisionEffect = Literal["coverage", "exclusion", "review"]


def _compact(value: str) -> str:
    return "".join(value.split()).casefold()


def _non_empty_strings(value: Any, field: str, *, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        text = item.strip()
        if text not in result:
            result.append(text)
    if len(result) < minimum:
        raise ValueError(f"{field} requires at least {minimum} values")
    return tuple(result)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ApprovedEvidenceCondition:
    condition_id: str
    question: str
    allowed_values: tuple[str, ...]
    required_values: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApprovedEvidenceCondition":
        if set(payload) != {
            "condition_id",
            "question",
            "allowed_values",
            "required_values",
            "evidence_chunk_ids",
        }:
            raise ValueError("approved evidence condition fields are invalid")
        allowed = _non_empty_strings(payload.get("allowed_values"), "allowed_values", minimum=1)
        if not set(allowed).issubset({"yes", "no", "unknown"}):
            raise ValueError("approved evidence condition allowed_values are invalid")
        required = _non_empty_strings(payload.get("required_values"), "required_values", minimum=1)
        if not set(required).issubset(set(allowed)):
            raise ValueError("approved evidence condition required_values are invalid")
        return cls(
            condition_id=_required_string(payload, "condition_id"),
            question=_required_string(payload, "question"),
            allowed_values=allowed,
            required_values=required,
            evidence_chunk_ids=_non_empty_strings(payload.get("evidence_chunk_ids"), "evidence_chunk_ids"),
        )


@dataclass(frozen=True)
class ApprovedDecisionProfile:
    profile_id: str
    concept_id: str
    approval_operation_path: str
    query_terms: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    direct_source_chunk_ids: Mapping[str, tuple[str, ...]]
    effect: DecisionEffect
    supported_summary: str
    unresolved_summary: str
    required_evidence: tuple[str, ...]
    conditions: tuple[ApprovedEvidenceCondition, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApprovedDecisionProfile":
        required = {
            "profile_id",
            "concept_id",
            "approval_operation_path",
            "query_terms",
            "evidence_terms",
            "direct_source_chunk_ids",
            "effect",
            "supported_summary",
            "unresolved_summary",
            "required_evidence",
            "conditions",
        }
        if set(payload) != required:
            raise ValueError("approved decision profile fields are invalid")
        direct_rows = payload.get("direct_source_chunk_ids")
        if not isinstance(direct_rows, Mapping) or not direct_rows:
            raise ValueError("direct_source_chunk_ids must be an object")
        direct: dict[str, tuple[str, ...]] = {}
        for generation, chunk_ids in direct_rows.items():
            if not isinstance(generation, str) or not generation.strip():
                raise ValueError("direct_source_chunk_ids keys are invalid")
            direct[generation.strip()] = _non_empty_strings(
                chunk_ids, "direct_source_chunk_ids values", minimum=1
            )
        effect = payload.get("effect")
        if effect not in {"coverage", "exclusion", "review"}:
            raise ValueError("effect is invalid")
        raw_conditions = payload.get("conditions")
        if not isinstance(raw_conditions, list) or len(raw_conditions) > 8:
            raise ValueError("conditions are invalid")
        conditions = tuple(
            ApprovedEvidenceCondition.from_dict(item)
            for item in raw_conditions
            if isinstance(item, Mapping)
        )
        if len(conditions) != len(raw_conditions) or len({item.condition_id for item in conditions}) != len(conditions):
            raise ValueError("conditions are invalid")
        return cls(
            profile_id=_required_string(payload, "profile_id"),
            concept_id=_required_string(payload, "concept_id"),
            approval_operation_path=_required_string(payload, "approval_operation_path"),
            query_terms=_non_empty_strings(payload.get("query_terms"), "query_terms", minimum=1),
            evidence_terms=_non_empty_strings(payload.get("evidence_terms"), "evidence_terms", minimum=1),
            direct_source_chunk_ids=direct,
            effect=effect,
            supported_summary=_required_string(payload, "supported_summary"),
            unresolved_summary=_required_string(payload, "unresolved_summary"),
            required_evidence=_non_empty_strings(payload.get("required_evidence"), "required_evidence"),
            conditions=conditions,
        )


@dataclass(frozen=True)
class GroundedDisplayResult:
    status: Literal["supported", "clarification_required"]
    answer: str
    payload: dict[str, Any]
    selected_chunks: tuple[Chunk, ...]


def has_schema_v2_display_contract(payload: Mapping[str, Any] | None) -> bool:
    """Return whether a payload has the canonical schema v2 display text."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") != 2:
        return False
    display = payload.get("display")
    return isinstance(display, Mapping) and isinstance(display.get("primary_text"), str) and bool(
        display["primary_text"].strip()
    )


def parse_approved_decision_profiles(rows: Iterable[Mapping[str, Any]]) -> tuple[ApprovedDecisionProfile, ...]:
    profiles: list[ApprovedDecisionProfile] = []
    for row in rows:
        profiles.append(ApprovedDecisionProfile.from_dict(row))
    return tuple(profiles)


def _profile_matches(question: str, profile: ApprovedDecisionProfile) -> bool:
    compact_question = _compact(question)
    return any(_compact(term) in compact_question for term in profile.query_terms)


def _chunk_matches_terms(chunk: Chunk, terms: Sequence[str]) -> bool:
    compact_text = _compact(chunk.text)
    return all(_compact(term) in compact_text for term in terms)


def _direct_chunks(
    chunks: Sequence[Chunk], profile: ApprovedDecisionProfile, policy_generation: str | None
) -> tuple[Chunk, ...]:
    if not policy_generation:
        return ()
    preferred_ids = set(profile.direct_source_chunk_ids.get(policy_generation, ()))
    if not preferred_ids:
        return ()
    return tuple(
        chunk
        for chunk in chunks
        if chunk.id in preferred_ids
        and str((chunk.metadata or {}).get("policy_generation") or "") == policy_generation
        and _chunk_matches_terms(chunk, profile.evidence_terms)
    )


def _authority(chunks: Sequence[Chunk]) -> tuple[str, str]:
    kinds: set[str] = set()
    for chunk in chunks:
        metadata = chunk.metadata or {}
        if metadata.get("is_own_company") is True:
            kinds.add("own")
        elif str(metadata.get("product_type") or "").strip() == "표준약관" or str(
            metadata.get("doc_short") or ""
        ).strip() == "표준약관":
            kinds.add("standard")
        else:
            kinds.add("other")
    if "own" in kinds and "standard" in kinds:
        return "mixed", "자사 약관과 표준약관의 직접 조항을 함께 확인했습니다."
    if "own" in kinds:
        return "own", "자사 약관의 직접 조항을 근거로 확인했습니다."
    if "standard" in kinds:
        return "standard", "등록된 표준약관의 직접 조항을 근거로 확인했습니다."
    return "other", "선택한 기준 문서의 직접 조항을 근거로 확인했습니다."


def _source_evidence(chunk: Chunk) -> dict[str, Any]:
    metadata = chunk.metadata or {}
    return {
        "doc_short": metadata.get("doc_short") or "문서",
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end", metadata.get("page_start")),
        "chunk_id": chunk.id,
    }


def _assertion_values(context: ResolvedConversationContext | None) -> dict[str, str]:
    if context is None:
        return {}
    return {
        assertion.slot_id: assertion.value
        for assertion in context.state_after.user_assertions
        if assertion.resolution == "confirmed"
    }


def _condition_payload(
    condition: ApprovedEvidenceCondition, assertion_values: Mapping[str, str]
) -> tuple[dict[str, Any], bool]:
    value = assertion_values.get(condition.condition_id)
    satisfied = value in condition.required_values
    if satisfied:
        state = "satisfied"
    elif value is None:
        state = "unresolved"
    else:
        state = "not_satisfied"
    return {
        "condition_id": condition.condition_id,
        "question": condition.question,
        "state": state,
        "value": value,
        "required_values": list(condition.required_values),
    }, satisfied


def evaluate_approved_evidence(
    question: str,
    chunks: Sequence[Chunk],
    profiles: Sequence[ApprovedDecisionProfile],
    *,
    policy_generation: str | None,
    context: ResolvedConversationContext | None = None,
) -> GroundedDisplayResult | None:
    """Evaluate only approved profiles with a matching direct source chunk."""

    profile = next((item for item in profiles if _profile_matches(question, item)), None)
    if profile is None:
        return None
    selected_chunks = _direct_chunks(chunks, profile, policy_generation)
    if not selected_chunks:
        return None
    values = _assertion_values(context)
    conditions: list[dict[str, Any]] = []
    unresolved_slots: list[dict[str, Any]] = []
    all_satisfied = True
    for condition in profile.conditions:
        payload, satisfied = _condition_payload(condition, values)
        conditions.append(payload)
        if not satisfied:
            all_satisfied = False
            unresolved_slots.append(
                {
                    "slot_id": condition.condition_id,
                    "evidence_condition_id": condition.condition_id,
                    "question": condition.question,
                    "allowed_values": list(condition.allowed_values),
                    "evidence_chunk_ids": list(condition.evidence_chunk_ids),
                }
            )
    authority, authority_note = _authority(selected_chunks)
    status: Literal["supported", "clarification_required"] = "supported" if all_satisfied else "clarification_required"
    summary = profile.supported_summary if all_satisfied else profile.unresolved_summary
    answer_parts = [summary, authority_note]
    if unresolved_slots:
        answer_parts.append("추가 확인: " + ", ".join(slot["question"] for slot in unresolved_slots))
    payload = {
        "schema_version": 2,
        "display": {"primary_text": summary},
        "evidence_assessment": {
            "profile_id": profile.profile_id,
            "concept_id": profile.concept_id,
            "status": status,
            "effect": profile.effect,
            "summary": summary,
            "authority": authority,
            "authority_note": authority_note,
            "conditions": conditions,
            "required_evidence": list(profile.required_evidence),
            "source_evidence": [_source_evidence(chunk) for chunk in selected_chunks],
        },
        "clarification": {"pending_slots": unresolved_slots},
    }
    return GroundedDisplayResult(
        status=status,
        answer="\n\n".join(answer_parts),
        payload=payload,
        selected_chunks=selected_chunks,
    )


def evaluate_registry_evidence(
    question: str,
    chunks: Sequence[Chunk],
    *,
    policy_generation: str | None,
    context: ResolvedConversationContext | None = None,
    registry: Any,
) -> GroundedDisplayResult | None:
    """Evaluate profiles exposed by a validated runtime ontology registry."""

    profile_payloads = getattr(registry, "approved_decision_profile_payloads", lambda: [])()
    try:
        profiles = parse_approved_decision_profiles(profile_payloads)
    except ValueError:
        return None
    return evaluate_approved_evidence(
        question,
        chunks,
        profiles,
        policy_generation=policy_generation,
        context=context,
    )


def clarification_slots(result: GroundedDisplayResult | None) -> tuple[ClarificationSlot, ...]:
    if result is None:
        return ()
    return clarification_slots_from_payload(result.payload)


def clarification_slots_from_payload(payload: Mapping[str, Any] | None) -> tuple[ClarificationSlot, ...]:
    if not isinstance(payload, Mapping):
        return ()
    clarification = payload.get("clarification")
    if not isinstance(clarification, Mapping):
        return ()
    raw_slots = clarification.get("pending_slots", [])
    if not isinstance(raw_slots, list):
        return ()
    slots: list[ClarificationSlot] = []
    for row in raw_slots:
        if not isinstance(row, Mapping):
            continue
        slots.append(
            ClarificationSlot(
                slot_id=str(row.get("slot_id") or "").strip(),
                evidence_condition_id=str(row.get("evidence_condition_id") or "").strip(),
                question=str(row.get("question") or "").strip(),
                allowed_values=tuple(str(item) for item in row.get("allowed_values", []) if str(item).strip()),
                evidence_chunk_ids=tuple(str(item) for item in row.get("evidence_chunk_ids", []) if str(item).strip()),
            )
        )
    return tuple(slot for slot in slots if slot.slot_id and slot.evidence_condition_id and slot.question)
