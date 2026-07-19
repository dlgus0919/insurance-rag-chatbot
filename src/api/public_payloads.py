"""Bounded browser/export payloads for persisted chat metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


_MAX_TEXT_LENGTH = 1_000
_MAX_LIST_ITEMS = 20


def _text(value: Any, *, limit: int = _MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _scalar(value: Any) -> str | int | float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    return value


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value[:_MAX_LIST_ITEMS] if (text := _text(item))]


def _display_name(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _public_evidence(value: Any) -> list[dict[str, str | int | float]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str | int | float]] = []
    for item in value[:_MAX_LIST_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        doc_short = _display_name(item.get("doc_short") or item.get("filename") or item.get("title"))
        entry: dict[str, str | int | float] = {}
        if doc_short:
            entry["doc_short"] = doc_short
        for key in ("page_start", "page_end"):
            page = _scalar(item.get(key))
            if page is not None:
                entry[key] = page
        if entry:
            result.append(entry)
    return result


def public_sources(sources: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Return only display-safe retrieval sources, never persisted private rows."""

    result: list[dict[str, Any]] = []
    for source in sources or ():
        if not isinstance(source, Mapping) or source.get("__kind"):
            continue
        filename = _display_name(source.get("filename") or source.get("doc_short") or source.get("title"))
        entry: dict[str, Any] = {}
        if filename:
            entry["filename"] = filename
        doc_short = _text(source.get("doc_short"))
        if doc_short:
            entry["doc_short"] = doc_short
        for key in ("page", "page_end", "score"):
            value = _scalar(source.get(key))
            if value is not None:
                entry[key] = value
        snippet = _text(source.get("snippet"))
        if snippet:
            entry["snippet"] = snippet
        status = _text(source.get("status"))
        if status:
            entry["status"] = status
        if entry:
            result.append(entry)
    return result


def storage_sources(sources: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Preserve non-assistant metadata rows for internal thread reconstruction."""

    return [
        deepcopy(dict(source))
        for source in sources or ()
        if isinstance(source, Mapping) and source.get("__kind") != "assistant_meta"
    ]


def assistant_metadata(sources: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    for source in sources or ():
        if isinstance(source, Mapping) and source.get("__kind") == "assistant_meta":
            return dict(source)
    return {}


def public_warnings(warnings: Any) -> list[dict[str, str]]:
    if not isinstance(warnings, list):
        return []
    result: list[dict[str, str]] = []
    for warning in warnings[:_MAX_LIST_ITEMS]:
        if not isinstance(warning, Mapping):
            continue
        entry = {key: text for key in ("code", "message") if (text := _text(warning.get(key)))}
        if entry:
            result.append(entry)
    return result


def _public_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("clarification_questions", "required_evidence", "ambiguous_terms"):
        items = _text_list(value.get(key))
        if items:
            result[key] = items
    normalized_terms = value.get("normalized_terms")
    if isinstance(normalized_terms, Mapping):
        terms = {
            raw: normalized
            for raw, normalized in (
                (_text(key), _text(item)) for key, item in list(normalized_terms.items())[:_MAX_LIST_ITEMS]
            )
            if raw and normalized
        }
        if terms:
            result["normalized_terms"] = terms
    candidates = value.get("term_correction_candidates")
    if isinstance(candidates, list):
        safe_candidates = []
        for item in candidates[:_MAX_LIST_ITEMS]:
            if not isinstance(item, Mapping):
                continue
            raw = _text(item.get("raw"))
            normalized = _text(item.get("normalized"))
            if raw and normalized:
                safe_candidates.append({"raw": raw, "normalized": normalized})
        if safe_candidates:
            result["term_correction_candidates"] = safe_candidates
    return result


def _public_clarification(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("pending_slots"), list):
        return {"pending_slots": []}
    slots = []
    for item in value["pending_slots"][:_MAX_LIST_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        slot_id = _text(item.get("slot_id"))
        question = _text(item.get("question"))
        allowed_values = _text_list(item.get("allowed_values"))
        if slot_id and question and allowed_values:
            slots.append(
                {"slot_id": slot_id, "question": question, "allowed_values": allowed_values}
            )
    return {"pending_slots": slots}


def _public_evidence_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("status", "effect", "summary", "authority_note"):
        text = _text(value.get(key))
        if text:
            result[key] = text
    conditions = _public_conditions(value.get("conditions"))
    if conditions:
        result["conditions"] = conditions
    evidence = _public_evidence(value.get("source_evidence"))
    if evidence:
        result["source_evidence"] = evidence
    return result


def _public_conditions(value: Any) -> list[str | dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[str | dict[str, str]] = []
    for item in value[:_MAX_LIST_ITEMS]:
        if isinstance(item, Mapping):
            question = _text(item.get("question") or item.get("label"))
            if not question:
                continue
            entry = {"question": question}
            state = _text(item.get("state"))
            if state:
                entry["state"] = state
            result.append(entry)
        elif text := _text(item):
            result.append(text)
    return result


def _public_canonical_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("status_label", "summary", "authority_note"):
        text = _text(value.get(key))
        if text:
            result[key] = text
    conditions = _text_list(value.get("conditions"))
    if conditions:
        result["conditions"] = conditions
    evidence = _public_evidence(value.get("source_evidence"))
    if evidence:
        result["source_evidence"] = evidence
    return result


def _public_review_paths(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    text_keys = ("path_type", "path_type_label", "status", "status_label", "summary")
    list_keys = (
        "required_evidence",
        "review_actions",
        "exclusion_reasons",
        "benefit_limits",
        "deductible_rules",
        "required_documents",
        "coordination_rules",
        "generation_rules",
    )
    for item in value[:_MAX_LIST_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        entry = {key: text for key in text_keys if (text := _text(item.get(key)))}
        for key in list_keys:
            items = _text_list(item.get(key))
            if items:
                entry[key] = items
        if entry:
            result.append(entry)
    return result


def _public_facts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:_MAX_LIST_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        entry = {key: text for key in ("subject", "relation", "object", "status") if (text := _text(item.get(key)))}
        evidence = _public_evidence(item.get("evidence"))
        if evidence:
            entry["evidence"] = evidence
        if entry:
            result.append(entry)
    return result


def public_graph_payload(graph_payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Build a browser-safe graph payload from an explicit display allowlist."""

    if not isinstance(graph_payload, Mapping):
        return None
    result: dict[str, Any] = {}
    schema_version = graph_payload.get("schema_version")
    if isinstance(schema_version, int) and not isinstance(schema_version, bool):
        result["schema_version"] = schema_version
    display = graph_payload.get("display")
    if isinstance(display, Mapping) and (primary_text := _text(display.get("primary_text"))):
        result["display"] = {"primary_text": primary_text}
    for key, builder in (
        ("evidence_assessment", _public_evidence_assessment),
        ("canonical_decision", _public_canonical_decision),
        ("plan", _public_plan),
    ):
        entry = builder(graph_payload.get(key))
        if entry:
            result[key] = entry
    result["clarification"] = _public_clarification(graph_payload.get("clarification"))
    review_paths = _public_review_paths(graph_payload.get("graph_review_paths"))
    if review_paths:
        result["graph_review_paths"] = review_paths
    facts = _public_facts(graph_payload.get("facts"))
    if facts:
        result["facts"] = facts
    required_evidence = _text_list(graph_payload.get("required_evidence"))
    if required_evidence:
        result["required_evidence"] = required_evidence
    warnings = public_warnings(graph_payload.get("warnings"))
    if warnings:
        result["warnings"] = warnings
    return result


def public_export_metadata(sources: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    metadata = assistant_metadata(sources)
    graph_payload = public_graph_payload(metadata.get("graph_result")) or {}
    return {
        "warnings": public_warnings(metadata.get("warnings")),
        "graph_review_paths": list(graph_payload.get("graph_review_paths") or []),
    }
