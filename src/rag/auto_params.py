"""Automatic Top-K and temperature selection for general RAG queries."""

from __future__ import annotations

from dataclasses import dataclass

from src.rag.search_intent import SearchIntentPlan, classify_search_intent


AUTO_MODE_OFF = "off"
AUTO_MODE_OBSERVE = "observe"
AUTO_MODE_APPLY = "apply"
SUPPORTED_AUTO_MODES = {AUTO_MODE_OFF, AUTO_MODE_OBSERVE, AUTO_MODE_APPLY}

MIN_TOP_K = 1
MAX_TOP_K = 20
DEFAULT_MAX_TEMPERATURE = 0.2

_TOP_K_BY_INTENT = {
    "exact_code_lookup": 6,
    "exact_code_compound_lookup": 8,
    "procedure_code_lookup": 6,
    "clause_or_appendix_lookup": 7,
    "clause_detail_lookup": 8,
    "coverage_judgment": 10,
    "cross_doc_compare": 12,
    "ambiguous_medical_term": 10,
    "general_explanation": 8,
}

_TEMPERATURE_BY_INTENT = {
    "exact_code_lookup": 0.0,
    "exact_code_compound_lookup": 0.0,
    "procedure_code_lookup": 0.0,
    "clause_or_appendix_lookup": 0.0,
    "clause_detail_lookup": 0.0,
    "coverage_judgment": 0.0,
    "cross_doc_compare": 0.0,
    "ambiguous_medical_term": 0.1,
    "general_explanation": 0.2,
}


@dataclass(frozen=True)
class AutoRagParams:
    """Resolved automatic parameter decision and audit payload."""

    mode: str
    requested: bool | None
    effective: bool
    manual_override: bool
    profile: str
    confidence: float
    requested_top_k: int
    suggested_top_k: int
    effective_top_k: int
    requested_temperature: float
    suggested_temperature: float
    effective_temperature: float
    reason: str
    search_intent: SearchIntentPlan | None = None

    def to_payload(self) -> dict:
        """Return a JSON-safe audit/debug representation."""

        return {
            "mode": self.mode,
            "requested": self.requested,
            "effective": self.effective,
            "manual_override": self.manual_override,
            "profile": self.profile,
            "confidence": round(float(self.confidence), 3),
            "requested_top_k": self.requested_top_k,
            "suggested_top_k": self.suggested_top_k,
            "effective_top_k": self.effective_top_k,
            "requested_temperature": round(float(self.requested_temperature), 3),
            "suggested_temperature": round(float(self.suggested_temperature), 3),
            "effective_temperature": round(float(self.effective_temperature), 3),
            "reason": self.reason,
            "search_intent": (
                self.search_intent.to_payload()
                if hasattr(self.search_intent, "to_payload")
                else None
            ),
        }


def normalize_auto_mode(mode: str | None) -> str:
    """Normalize an environment-configured automatic parameter mode."""

    normalized = (mode or AUTO_MODE_APPLY).strip().lower()
    if normalized not in SUPPORTED_AUTO_MODES:
        return AUTO_MODE_APPLY
    return normalized


def resolve_auto_rag_params(
    *,
    question: str,
    mode: str,
    filters: dict | None,
    requested_top_k: int,
    requested_temperature: float,
    auto_params: bool | None,
    config_mode: str = AUTO_MODE_APPLY,
    allow_manual_override: bool = True,
    max_temperature: float = DEFAULT_MAX_TEMPERATURE,
) -> AutoRagParams:
    """Resolve effective RAG parameters for a chat request.

    The first production version is deliberately rule-only. It applies automatic
    values only to the final general RAG route; quick-code/formal paths keep
    their existing specialized behavior.
    """

    normalized_mode = normalize_auto_mode(config_mode)
    safe_requested_top_k = _clamp_int(requested_top_k, MIN_TOP_K, MAX_TOP_K)
    safe_requested_temperature = _clamp_float(requested_temperature, 0.0, 2.0)
    safe_max_temperature = _clamp_float(max_temperature, 0.0, 2.0)

    doc_filter = _extract_doc_filter(filters)
    search_intent = classify_search_intent(question, doc_filter=doc_filter)
    profile = search_intent.intent
    suggested_top_k = _clamp_int(_TOP_K_BY_INTENT.get(profile, 8), MIN_TOP_K, MAX_TOP_K)
    suggested_temperature = min(
        _clamp_float(_TEMPERATURE_BY_INTENT.get(profile, 0.1), 0.0, 2.0),
        safe_max_temperature,
    )
    route_is_general = mode == "general"

    if not route_is_general:
        return AutoRagParams(
            mode=normalized_mode,
            requested=auto_params,
            effective=False,
            manual_override=False,
            profile=profile,
            confidence=search_intent.confidence,
            requested_top_k=safe_requested_top_k,
            suggested_top_k=suggested_top_k,
            effective_top_k=safe_requested_top_k,
            requested_temperature=safe_requested_temperature,
            suggested_temperature=suggested_temperature,
            effective_temperature=safe_requested_temperature,
            reason="자동 파라미터는 일반 질의 route에서만 적용합니다.",
            search_intent=search_intent,
        )

    if auto_params is False and allow_manual_override:
        return AutoRagParams(
            mode=normalized_mode,
            requested=auto_params,
            effective=False,
            manual_override=True,
            profile=profile,
            confidence=search_intent.confidence,
            requested_top_k=safe_requested_top_k,
            suggested_top_k=suggested_top_k,
            effective_top_k=safe_requested_top_k,
            requested_temperature=safe_requested_temperature,
            suggested_temperature=suggested_temperature,
            effective_temperature=safe_requested_temperature,
            reason="사용자가 일반 질의 자동 설정을 끄고 수동값을 요청했습니다.",
            search_intent=search_intent,
        )

    if normalized_mode == AUTO_MODE_OFF:
        return AutoRagParams(
            mode=normalized_mode,
            requested=auto_params,
            effective=False,
            manual_override=False,
            profile=profile,
            confidence=search_intent.confidence,
            requested_top_k=safe_requested_top_k,
            suggested_top_k=suggested_top_k,
            effective_top_k=safe_requested_top_k,
            requested_temperature=safe_requested_temperature,
            suggested_temperature=suggested_temperature,
            effective_temperature=safe_requested_temperature,
            reason="서버 설정이 AUTO_RAG_PARAMS_MODE=off라 수동 요청값을 유지합니다.",
            search_intent=search_intent,
        )

    if normalized_mode == AUTO_MODE_OBSERVE:
        return AutoRagParams(
            mode=normalized_mode,
            requested=auto_params,
            effective=False,
            manual_override=False,
            profile=profile,
            confidence=search_intent.confidence,
            requested_top_k=safe_requested_top_k,
            suggested_top_k=suggested_top_k,
            effective_top_k=safe_requested_top_k,
            requested_temperature=safe_requested_temperature,
            suggested_temperature=suggested_temperature,
            effective_temperature=safe_requested_temperature,
            reason="서버 설정이 observe라 자동 산출값은 기록만 하고 적용하지 않습니다.",
            search_intent=search_intent,
        )

    return AutoRagParams(
        mode=normalized_mode,
        requested=auto_params,
        effective=True,
        manual_override=False,
        profile=profile,
        confidence=search_intent.confidence,
        requested_top_k=safe_requested_top_k,
        suggested_top_k=suggested_top_k,
        effective_top_k=suggested_top_k,
        requested_temperature=safe_requested_temperature,
        suggested_temperature=suggested_temperature,
        effective_temperature=suggested_temperature,
        reason=f"{profile} 질의 profile에 맞춰 보수적인 Top-K/temperature를 적용합니다.",
        search_intent=search_intent,
    )


def _extract_doc_filter(filters: dict | None) -> list[str] | None:
    if not isinstance(filters, dict):
        return None
    raw = filters.get("doc_filter") or filters.get("doc_short")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    values = [str(item).strip() for item in raw if str(item).strip()]
    return list(dict.fromkeys(values)) or None


def _clamp_int(value: int | float, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = minimum
    return max(minimum, min(maximum, numeric))


def _clamp_float(value: int | float, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    return max(minimum, min(maximum, numeric))
