"""Automatic Top-K and temperature selection for general RAG queries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.retrieval import Hit
from src.rag.search_intent import SearchIntentPlan, classify_search_intent


AUTO_MODE_OFF = "off"
AUTO_MODE_OBSERVE = "observe"
AUTO_MODE_APPLY = "apply"
SUPPORTED_AUTO_MODES = {AUTO_MODE_OFF, AUTO_MODE_OBSERVE, AUTO_MODE_APPLY}

MIN_TOP_K = 1
MAX_TOP_K = 20
DEFAULT_MAX_TEMPERATURE = 0.2
TOPK_STRATEGY_RULE = "rule"
TOPK_STRATEGY_RERANKER_THRESHOLD = "reranker_threshold"
SUPPORTED_TOPK_STRATEGIES = {TOPK_STRATEGY_RULE, TOPK_STRATEGY_RERANKER_THRESHOLD}

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

_TOP_K_LIMITS_BY_INTENT = {
    "exact_code_lookup": (4, 8),
    "exact_code_compound_lookup": (6, 10),
    "procedure_code_lookup": (4, 8),
    "clause_or_appendix_lookup": (5, 10),
    "clause_detail_lookup": (6, 10),
    "coverage_judgment": (8, 12),
    "cross_doc_compare": (10, 14),
    "ambiguous_medical_term": (8, 12),
    "general_explanation": (5, 10),
}


@dataclass(frozen=True)
class AdaptiveKDecision:
    """Post-reranker final-k decision."""

    selected_k: int
    cutoff_reason: str
    score_floor: float | None
    drop_abs: float
    drop_ratio: float
    min_k: int
    max_k: int
    candidate_count: int
    applied: bool

    def to_payload(self) -> dict:
        return {
            "selected_k": self.selected_k,
            "cutoff_reason": self.cutoff_reason,
            "score_floor": self.score_floor,
            "drop_abs": self.drop_abs,
            "drop_ratio": self.drop_ratio,
            "min_k": self.min_k,
            "max_k": self.max_k,
            "candidate_count": self.candidate_count,
            "applied": self.applied,
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
    top_k_strategy: str = TOPK_STRATEGY_RULE
    retrieval_top_k: int = 0
    min_top_k: int = MIN_TOP_K
    max_top_k: int = MAX_TOP_K
    cutoff_reason: str = "rule_only"

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
            "top_k_strategy": self.top_k_strategy,
            "retrieval_top_k": self.retrieval_top_k or self.effective_top_k,
            "min_top_k": self.min_top_k,
            "max_top_k": self.max_top_k,
            "cutoff_reason": self.cutoff_reason,
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
    top_k_strategy: str = TOPK_STRATEGY_RULE,
    temperature_policy_path: Path | str | None = None,
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
    min_top_k, max_top_k = _profile_top_k_limits(profile)
    normalized_top_k_strategy = normalize_top_k_strategy(top_k_strategy)
    temperature_policy = load_temperature_policy(temperature_policy_path)
    suggested_temperature = min(
        _clamp_float(_temperature_for_profile(profile, temperature_policy), 0.0, 2.0),
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
            top_k_strategy=normalized_top_k_strategy,
            retrieval_top_k=safe_requested_top_k,
            min_top_k=min_top_k,
            max_top_k=max_top_k,
            cutoff_reason="non_general_route",
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
            top_k_strategy=normalized_top_k_strategy,
            retrieval_top_k=safe_requested_top_k,
            min_top_k=min_top_k,
            max_top_k=max_top_k,
            cutoff_reason="manual_override",
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
            top_k_strategy=normalized_top_k_strategy,
            retrieval_top_k=safe_requested_top_k,
            min_top_k=min_top_k,
            max_top_k=max_top_k,
            cutoff_reason="mode_off",
        )

    retrieval_top_k = (
        max_top_k
        if normalized_top_k_strategy == TOPK_STRATEGY_RERANKER_THRESHOLD
        else suggested_top_k
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
            top_k_strategy=normalized_top_k_strategy,
            retrieval_top_k=safe_requested_top_k,
            min_top_k=min_top_k,
            max_top_k=max_top_k,
            cutoff_reason="mode_observe",
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
        top_k_strategy=normalized_top_k_strategy,
        retrieval_top_k=retrieval_top_k,
        min_top_k=min_top_k,
        max_top_k=max_top_k,
        cutoff_reason=(
            "post_reranker_threshold_pending"
            if normalized_top_k_strategy == TOPK_STRATEGY_RERANKER_THRESHOLD
            else "rule_only"
        ),
    )


def normalize_top_k_strategy(strategy: str | None) -> str:
    normalized = (strategy or TOPK_STRATEGY_RULE).strip().lower()
    if normalized not in SUPPORTED_TOPK_STRATEGIES:
        return TOPK_STRATEGY_RULE
    return normalized


def load_temperature_policy(path: Path | str | None) -> dict[str, Any]:
    if not path:
        return {}
    policy_path = Path(path)
    if not policy_path.exists():
        return {}
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def select_adaptive_k(
    scores: list[float],
    *,
    base_k: int,
    min_k: int,
    max_k: int,
    score_floor: float | None = None,
    drop_abs: float = 0.15,
    drop_ratio: float = 0.30,
) -> AdaptiveKDecision:
    """Select final-k from a descending reranker score curve."""

    candidate_count = len(scores)
    bounded_min = _clamp_int(min_k, MIN_TOP_K, MAX_TOP_K)
    bounded_max = max(bounded_min, _clamp_int(max_k, bounded_min, MAX_TOP_K))
    selected = _clamp_int(base_k, bounded_min, bounded_max)
    if candidate_count <= bounded_min:
        return AdaptiveKDecision(
            selected_k=min(candidate_count or bounded_min, bounded_max),
            cutoff_reason="insufficient_candidates",
            score_floor=score_floor,
            drop_abs=drop_abs,
            drop_ratio=drop_ratio,
            min_k=bounded_min,
            max_k=bounded_max,
            candidate_count=candidate_count,
            applied=False,
        )

    limit = min(candidate_count - 1, bounded_max - 1)
    for idx in range(bounded_min - 1, limit):
        current_score = float(scores[idx])
        next_score = float(scores[idx + 1])
        absolute_drop = current_score - next_score
        relative_drop = absolute_drop / max(abs(current_score), 1e-6)
        if score_floor is not None and next_score < score_floor:
            selected = idx + 1
            reason = "score_floor"
            break
        if absolute_drop >= drop_abs:
            selected = idx + 1
            reason = "drop_abs"
            break
        if relative_drop >= drop_ratio:
            selected = idx + 1
            reason = "drop_ratio"
            break
    else:
        selected = min(max(selected, bounded_min), min(candidate_count, bounded_max))
        reason = "base_or_max_k"

    selected = min(max(selected, bounded_min), min(candidate_count, bounded_max))
    return AdaptiveKDecision(
        selected_k=selected,
        cutoff_reason=reason,
        score_floor=score_floor,
        drop_abs=drop_abs,
        drop_ratio=drop_ratio,
        min_k=bounded_min,
        max_k=bounded_max,
        candidate_count=candidate_count,
        applied=True,
    )


def apply_adaptive_k_to_hits(
    hits: list[Hit],
    reranker_scores: list[Any],
    decision: AutoRagParams,
    *,
    score_floor: float | None = None,
    drop_abs: float = 0.15,
    drop_ratio: float = 0.30,
    preserve_chunk_ids: set[str] | None = None,
    preserve_doc_shorts: set[str] | None = None,
) -> tuple[list[Hit], AdaptiveKDecision]:
    """Apply post-reranker adaptive-k cutoff to already ranked hits."""

    preserve_ids = set(preserve_chunk_ids or set())
    preserve_ids.update(_first_hit_ids_by_doc(hits, preserve_doc_shorts))

    if decision.top_k_strategy != TOPK_STRATEGY_RERANKER_THRESHOLD or not decision.effective:
        no_op = AdaptiveKDecision(
            selected_k=min(len(hits), decision.effective_top_k),
            cutoff_reason=decision.cutoff_reason,
            score_floor=score_floor,
            drop_abs=drop_abs,
            drop_ratio=drop_ratio,
            min_k=decision.min_top_k,
            max_k=decision.max_top_k,
            candidate_count=len(hits),
            applied=False,
        )
        return _slice_hits_preserving_required(hits, no_op.selected_k, no_op.selected_k, preserve_ids), no_op

    score_by_id = {getattr(item, "chunk_id", ""): float(getattr(item, "score", 0.0)) for item in reranker_scores}
    scores = [score_by_id.get(hit.id, float(hit.score)) for hit in hits]
    cutoff = select_adaptive_k(
        scores,
        base_k=decision.suggested_top_k,
        min_k=decision.min_top_k,
        max_k=decision.max_top_k,
        score_floor=score_floor,
        drop_abs=drop_abs,
        drop_ratio=drop_ratio,
    )
    selected = _slice_hits_preserving_required(
        hits,
        cutoff.selected_k,
        cutoff.max_k,
        preserve_ids,
    )
    return selected, cutoff


def _first_hit_ids_by_doc(hits: list[Hit], preserve_doc_shorts: set[str] | None) -> set[str]:
    if not preserve_doc_shorts:
        return set()
    remaining = set(preserve_doc_shorts)
    selected: set[str] = set()
    for hit in hits:
        doc_short = str((hit.metadata or {}).get("doc_short") or "")
        if doc_short not in remaining:
            continue
        selected.add(hit.id)
        remaining.remove(doc_short)
        if not remaining:
            break
    return selected


def _slice_hits_preserving_required(
    hits: list[Hit],
    selected_k: int,
    max_k: int,
    preserve_chunk_ids: set[str] | None,
) -> list[Hit]:
    """Slice ranked hits while keeping required GraphDB/doc-coverage evidence when present."""

    preserve = preserve_chunk_ids or set()
    if not preserve:
        return hits[:selected_k]

    selected: list[Hit] = []
    seen: set[str] = set()
    for hit in hits[:selected_k]:
        selected.append(hit)
        seen.add(hit.id)

    for hit in hits[selected_k:]:
        if hit.id not in preserve or hit.id in seen:
            continue
        selected.append(hit)
        seen.add(hit.id)

    if len(selected) <= max_k:
        return selected

    required = [hit for hit in selected if hit.id in preserve]
    optional = [hit for hit in selected if hit.id not in preserve]
    if len(required) >= max_k:
        return required[:max_k]
    return required + optional[: max_k - len(required)]


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


def _temperature_for_profile(profile: str, policy: dict[str, Any]) -> float:
    profiles = policy.get("profiles") if isinstance(policy, dict) else None
    if isinstance(profiles, dict) and profile in profiles:
        return float(profiles[profile])
    if isinstance(policy, dict) and "default" in policy:
        return float(policy["default"])
    return _TEMPERATURE_BY_INTENT.get(profile, 0.1)


def _profile_top_k_limits(profile: str) -> tuple[int, int]:
    return _TOP_K_LIMITS_BY_INTENT.get(profile, (MIN_TOP_K, MAX_TOP_K))


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
