from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.graph.normalizer import normalize_name


@dataclass(frozen=True)
class HoldReason:
    code: str
    label: str
    description: str


HOLD_REASONS: tuple[HoldReason, ...] = (
    HoldReason(
        code="evidence_mismatch",
        label="원문 근거 연결 부적절",
        description="원문 근거가 후보 개념을 뒷받침하지 않거나 다른 문맥에서 나온 경우",
    ),
    HoldReason(
        code="alias_mismatch",
        label="승인 대상 표현 부적절",
        description="승인 대상 표현이 후보 개념과 같은 보험 업무 개념을 가리키지 않는 경우",
    ),
    HoldReason(
        code="target_concept_mismatch",
        label="대상 concept 재배정 필요",
        description="표현은 유용하지만 현재 target concept이 아닌 다른 concept에 붙어야 하는 경우",
    ),
    HoldReason(
        code="sentence_fragment",
        label="문장 조각/조사 포함",
        description="표현이 독립 alias가 아니라 문장 일부, 조사 포함 조각, 미완성 구문인 경우",
    ),
    HoldReason(
        code="too_broad",
        label="표현 범위 과도",
        description="표현이 너무 넓어 여러 담보/조건/판단 로직으로 해석될 수 있는 경우",
    ),
    HoldReason(
        code="ownership_conflict",
        label="중복 후보/소유권 충돌",
        description="동일 표현이 여러 후보 concept에 붙을 수 있어 소유권 판단이 필요한 경우",
    ),
    HoldReason(
        code="needs_more_evidence",
        label="추가 근거 필요",
        description="표현은 가능성이 있지만 현재 근거만으로 승인하기 부족한 경우",
    ),
    HoldReason(
        code="policy_risk",
        label="지급/면책/감액/계산 판단 위험",
        description="검색 alias가 아니라 보험금 산정 또는 지급 판단 규칙으로 이어질 위험이 있는 경우",
    ),
    HoldReason(
        code="other",
        label="기타",
        description="위 항목으로 분류하기 어려운 보류 사유",
    ),
)

HOLD_REASON_BY_CODE = {reason.code: reason for reason in HOLD_REASONS}
ALIAS_BLOCKING_HOLD_CODES = {
    "alias_mismatch",
    "sentence_fragment",
    "too_broad",
    "ownership_conflict",
    "policy_risk",
}


def normalize_hold_reason_codes(codes: list[str] | tuple[str, ...] | None) -> list[str]:
    result: list[str] = []
    for code in codes or []:
        text = str(code or "").strip()
        if text in HOLD_REASON_BY_CODE and text not in result:
            result.append(text)
    return result


def hold_reason_labels(codes: list[str]) -> list[str]:
    return [HOLD_REASON_BY_CODE[code].label for code in normalize_hold_reason_codes(codes)]


def hold_reason_guidance_lines() -> list[str]:
    return [f"- {reason.label}: {reason.description}" for reason in HOLD_REASONS]


def build_hold_feedback_payload(
    *,
    reason_codes: list[str] | tuple[str, ...] | None,
    note: str = "",
) -> dict[str, Any]:
    codes = normalize_hold_reason_codes(list(reason_codes or []))
    payload: dict[str, Any] = {
        "hold_reason_codes": codes,
        "hold_reason_labels": hold_reason_labels(codes),
    }
    if note.strip():
        payload["note"] = " ".join(note.split())
    return payload


def held_alias_blocklist(candidates: list[Any]) -> dict[str, set[str]]:
    blocked: dict[str, set[str]] = {}
    for candidate in candidates:
        if getattr(candidate, "status", "") != "held":
            continue
        feedback = getattr(candidate, "properties", {}).get("review_feedback")
        if not isinstance(feedback, dict):
            continue
        codes = set(normalize_hold_reason_codes(feedback.get("hold_reason_codes") or []))
        if not codes.intersection(ALIAS_BLOCKING_HOLD_CODES):
            continue
        concept_id = str(getattr(candidate, "concept_id", "") or "").strip()
        for alias in getattr(candidate, "candidate_aliases", []) or []:
            normalized = normalize_name(alias)
            if normalized:
                blocked.setdefault(concept_id, set()).add(normalized)
    return blocked


def held_review_hints(candidates: list[Any]) -> dict[str, list[dict[str, Any]]]:
    hints: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if getattr(candidate, "status", "") != "held":
            continue
        feedback = getattr(candidate, "properties", {}).get("review_feedback")
        if not isinstance(feedback, dict):
            continue
        codes = normalize_hold_reason_codes(feedback.get("hold_reason_codes") or [])
        if not codes:
            continue
        concept_id = str(getattr(candidate, "concept_id", "") or "").strip()
        hints.setdefault(concept_id, []).append(
            {
                "candidate_id": getattr(candidate, "candidate_id", ""),
                "hold_reason_codes": codes,
                "hold_reason_labels": hold_reason_labels(codes),
                "note": str(feedback.get("note") or "").strip(),
            }
        )
    return hints
