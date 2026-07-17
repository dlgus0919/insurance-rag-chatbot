"""Structured claim-calculation context shared by chat and RAG routes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence


_REFERENCE_MARKERS = (
    "그 계산",
    "위 계산",
    "방금 계산",
    "최근 계산",
    "직전 계산",
    "마지막 계산",
    "그 금액",
    "공제금액",
    "공제 금액",
    "지급금액",
    "지급 금액",
    "계산 결과",
    "예상 지급",
    "예상 공제",
)
_RECALCULATION_MARKERS = (
    "보상하지",
    "보상 제외",
    "급여 본인부담",
    "3대비급여",
    "비급여로",
    "보상한다면",
)
_PROMPT_MARKERS = re.compile(
    r"\[(?:SYSTEM|USER|ASSISTANT|최근 대화 참고|이전 대화 요약본|이 스레드의 보험금 계산)\]",
    re.IGNORECASE,
)
_ROLE_PREFIX = re.compile(r"\b(?:system|assistant|user)\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class ClaimThreadContext:
    active_snapshot: dict[str, Any] | None
    prompt_context: str
    retrieval_terms: tuple[str, ...]
    references_claim: bool


def extract_claim_snapshots(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """Read only assistant-meta claim snapshots from persisted chat messages."""

    snapshots: list[dict[str, Any]] = []
    for message in messages:
        if _value(message, "role") != "assistant":
            continue
        sources = _value(message, "sources") or []
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict) or source.get("__kind") != "assistant_meta":
                continue
            snapshot = source.get("claim_snapshot")
            if isinstance(snapshot, dict):
                snapshots.append(snapshot)
    return snapshots


def snapshot_state(snapshot: dict[str, Any]) -> str:
    """Classify both legacy v1 and persisted v2 snapshots without migration."""

    state = _clean(snapshot.get("state"), 40)
    if state in {"candidate_pending", "completed", "conditional"}:
        return state
    result = snapshot.get("result")
    candidates = result.get("candidates") if isinstance(result, dict) else None
    return "candidate_pending" if isinstance(candidates, list) and candidates else "completed"


def completed_claim_snapshots(messages: Sequence[Any]) -> list[dict[str, Any]]:
    return [snapshot for snapshot in extract_claim_snapshots(messages) if snapshot_state(snapshot) == "completed"]


def select_active_claim_snapshot(
    snapshots: Sequence[dict[str, Any]],
    _question: str = "",
) -> dict[str, Any] | None:
    """Use the newest completed calculation as the conversational authority."""

    completed = [snapshot for snapshot in snapshots if snapshot_state(snapshot) == "completed"]
    return completed[-1] if completed else None


def build_claim_thread_context(messages: Sequence[Any], question: str) -> ClaimThreadContext:
    snapshots = extract_claim_snapshots(messages)
    active_snapshot = select_active_claim_snapshot(snapshots, question)
    prompt_context, retrieval_terms = _build_prompt_context(active_snapshot, snapshots)
    return ClaimThreadContext(
        active_snapshot=active_snapshot,
        prompt_context=prompt_context,
        retrieval_terms=tuple(retrieval_terms),
        references_claim=_references_claim(question, active_snapshot),
    )


def contextualize_claim_query(question: str, context: ClaimThreadContext) -> str:
    """Add trusted calculation terms only when the current question refers to them."""

    if not context.references_claim or not context.retrieval_terms:
        return question
    terms = " / ".join(context.retrieval_terms[:8])
    return f"{question}\n[보험금 계산 문맥 검색어] {terms}"


def _build_prompt_context(
    active_snapshot: dict[str, Any] | None,
    snapshots: Sequence[dict[str, Any]],
) -> tuple[str, list[str]]:
    if active_snapshot is None:
        return "", []

    result = active_snapshot.get("result")
    if not isinstance(result, dict):
        result = {}
    input_data = active_snapshot.get("input")
    input_context = input_data.get("context") if isinstance(input_data, dict) else {}
    if not isinstance(input_context, dict):
        input_context = {}

    policy_generation = _clean(result.get("policy_generation") or input_context.get("policy_generation"), 40)
    special_status = _clean(
        result.get("special_calculation_status") or input_context.get("special_calculation_status"),
        40,
    )
    header = "[이 스레드의 활성 보험금 계산]"
    basis = " / ".join(part for part in (
        _generation_label(policy_generation),
        _special_status_label(special_status),
    ) if part)
    lines = [header]
    if basis:
        lines.append(f"- 계산 기준: {basis}")

    terms: list[str] = []
    for line in result.get("line_results") or []:
        if not isinstance(line, dict):
            continue
        name = _clean(line.get("input_name") or "항목명 없음")
        category = _clean(line.get("category") or "미분류")
        claimed = _money_text(line.get("claimed_amount"))
        deductible = _money_text(line.get("deductible"))
        payable = _money_text(line.get("payable_amount"))
        status = _clean(line.get("calculation_status") or "unknown", 40)
        lines.append(
            f"- {name} [{category}]: 청구 {claimed}원 / 공제 {deductible}원 / 지급 {payable}원 / 상태 {status}"
        )
        _append_unique(terms, name)
        _append_unique(terms, category)
        _append_unique(terms, claimed)
        _append_unique(terms, payable)

    if policy_generation:
        _append_unique(terms, policy_generation)

    completed = [snapshot for snapshot in snapshots if snapshot_state(snapshot) == "completed"]
    past = [snapshot for snapshot in completed if snapshot is not active_snapshot][-2:]
    if past:
        lines.append("- 이전 완료 계산 요약:")
        for snapshot in past:
            past_result = snapshot.get("result") if isinstance(snapshot.get("result"), dict) else {}
            claim_id = _clean(snapshot.get("claim_id") or "기록 없음", 36)
            created_at = _clean(snapshot.get("created_at") or "기록 시각 없음", 40)
            payable = _money_text(past_result.get("payable_amount"))
            lines.append(f"  - {claim_id} / {created_at} / 예상 지급 {payable}원")

    return "\n".join(lines), terms


def _references_claim(question: str, active_snapshot: dict[str, Any] | None) -> bool:
    normalized = " ".join(str(question or "").split())
    if not normalized or active_snapshot is None:
        return False
    if any(marker in normalized for marker in _REFERENCE_MARKERS):
        return True
    if any(marker in normalized for marker in _RECALCULATION_MARKERS):
        return True

    result = active_snapshot.get("result")
    if not isinstance(result, dict):
        return False
    query_money = _normalized_number_tokens(normalized)
    for line in result.get("line_results") or []:
        if not isinstance(line, dict):
            continue
        name = _clean(line.get("input_name"), 120)
        if len(name) >= 2 and name in normalized:
            return True
        for key in ("claimed_amount", "deductible", "payable_amount"):
            amount = _normalized_number(line.get(key))
            if amount and amount in query_money:
                return True
    return False


def _normalized_number_tokens(text: str) -> set[str]:
    return {token.replace(",", "") for token in re.findall(r"\d[\d,]*", text)}


def _normalized_number(value: Any) -> str:
    text = _clean(value, 60).replace(",", "").replace("원", "").strip()
    return text if text.isdigit() else ""


def _money_text(value: Any) -> str:
    text = _clean(value, 60).replace("원", "").strip()
    return text or "0"


def _generation_label(value: str) -> str:
    return {"4th": "4세대", "5th": "5세대"}.get(value, value)


def _special_status_label(value: str) -> str:
    return {
        "unknown": "산정특례 여부 모름",
        "applied": "산정특례 적용",
        "not_applied": "산정특례 미적용",
    }.get(value, value)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _clean(value: Any, max_chars: int = 120) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = _PROMPT_MARKERS.sub(" ", text)
    text = _ROLE_PREFIX.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars >= 0:
        return text[:max_chars]
    return text
