from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.claim_calculation.models import (
    SPECIAL_CALCULATION_APPLIED,
    SPECIAL_CALCULATION_NOT_APPLIED,
)
from src.claim_calculation.thread_context import snapshot_state


_GENERIC_CATEGORY_TARGETS = {"비급여", "3대비급여", "급여", "급여 본인부담"}


@dataclass(frozen=True)
class RecalculationIntent:
    action: str
    target_text: str
    needs_clarification: bool = False


def detect_recalculation_intent(query: str) -> RecalculationIntent | None:
    text = " ".join(query.split())
    target_text = _target_before_marker(text)
    if not target_text:
        return None

    if "보상하지 않는다면" in text or "보상 제외" in text:
        return RecalculationIntent(action="not_covered", target_text=target_text)
    if "급여 본인부담" in text:
        return RecalculationIntent(action="as_insured_copay", target_text=target_text)
    if "3대비급여" in text:
        return RecalculationIntent(action="as_three_major_nonpay", target_text=target_text)
    if "비급여로" in text and target_text != "비급여":
        return RecalculationIntent(action="as_nonpay", target_text=target_text)
    if "보상한다면" in text:
        return RecalculationIntent(
            action="covered_unspecified",
            target_text=target_text,
            needs_clarification=True,
        )

    return None


def special_status_from_query(query: str) -> str | None:
    text = " ".join(query.split())
    if "산정특례" not in text:
        return None
    if "미적용" in text or "적용하지" in text or "아니" in text:
        return SPECIAL_CALCULATION_NOT_APPLIED
    if "적용" in text:
        return SPECIAL_CALCULATION_APPLIED
    return None


def apply_special_status_override(payload_data: dict, special_status: str | None) -> dict:
    if not special_status:
        return payload_data
    payload = dict(payload_data)
    context = dict(payload.get("context") or {})
    context["special_calculation_status"] = special_status
    payload["context"] = context
    return payload


def needs_special_calculation_clarification(snapshot: dict, intent: RecalculationIntent, target_line: dict) -> bool:
    if intent.action != "as_three_major_nonpay":
        return False
    result = snapshot.get("result") or {}
    if result.get("policy_generation") != "5th":
        return False
    snapshot_status = str(result.get("special_calculation_status") or "unknown")
    if snapshot_status in {SPECIAL_CALCULATION_APPLIED, SPECIAL_CALCULATION_NOT_APPLIED}:
        return False
    text = " ".join([str(target_line.get("input_name") or ""), str(target_line.get("category") or "")]).lower()
    return any(keyword in text for keyword in ("도수", "체외충격파", "증식", "주사", "mri", "mra", "자기공명영상")) or intent.action == "as_three_major_nonpay"


def find_target_line(snapshot: dict, target_text: str) -> dict | None:
    matches = find_target_lines(snapshot, target_text)
    return matches[0] if len(matches) == 1 else None


def find_target_lines(snapshot: dict, target_text: str) -> list[dict]:
    target = target_text.strip()
    if not target:
        return []
    if target in _GENERIC_CATEGORY_TARGETS:
        return []

    lines = _snapshot_lines(snapshot)
    exact = [line for line in lines if str(line.get("input_name") or "") == target]
    if exact:
        return _unique_lines(exact)

    substring = [
        line
        for line in lines
        if (name := str(line.get("input_name") or ""))
        and (target in name or name in target)
    ]
    if substring:
        return _unique_lines(substring)

    category = [line for line in lines if str(line.get("category") or "") == target]
    return _unique_lines(category)


def select_claim_snapshot(snapshots: list[dict], query: str) -> tuple[dict | None, str]:
    completed = [snapshot for snapshot in snapshots if snapshot_state(snapshot) == "completed"]
    if not completed:
        return None, "이 스레드에는 기준이 되는 보험금 계산 내역이 없습니다. 먼저 보험금 계산 기능으로 계산을 저장한 뒤 다시 질문해 주세요."
    normalized = " ".join(query.split())

    explicit = _select_explicit_snapshot(completed, normalized)
    if explicit is not None:
        return explicit, ""
    if any(marker in normalized for marker in ("최근 계산", "마지막 계산", "직전 계산", "방금 계산")):
        return completed[-1], ""

    intent = detect_recalculation_intent(normalized)
    if intent is not None:
        latest = completed[-1]
        matching = [snapshot for snapshot in completed if find_target_lines(snapshot, intent.target_text)]
        if len(matching) > 1 and _matching_target_results_differ(matching, intent.target_text):
            return (
                None,
                "요청한 항목의 결과가 서로 다른 여러 계산에 있습니다. 기준이 될 계산을 '최근 계산', '첫 번째 계산'처럼 지정해 다시 질문해 주세요.",
            )
        if find_target_lines(latest, intent.target_text):
            return latest, ""
        if len(matching) == 1:
            return matching[0], ""
        if len(matching) > 1:
            return matching[-1], ""
    return completed[-1], ""


def _select_explicit_snapshot(snapshots: list[dict], query: str) -> dict | None:
    for snapshot in snapshots:
        claim_id = str(snapshot.get("claim_id") or "").strip()
        if claim_id and claim_id in query:
            return snapshot
    ordinal_markers = (
        (0, ("첫 번째 계산", "첫번째 계산", "1번째 계산", "1번 계산")),
        (1, ("두 번째 계산", "두번째 계산", "2번째 계산", "2번 계산")),
        (2, ("세 번째 계산", "세번째 계산", "3번째 계산", "3번 계산")),
    )
    for index, markers in ordinal_markers:
        if any(marker in query for marker in markers):
            return snapshots[index] if index < len(snapshots) else None
    return None


def build_recalculation_payload(snapshot: dict, intent: RecalculationIntent, target_line: dict) -> dict:
    if intent.action in {"not_covered", "covered_unspecified"}:
        raise ValueError(f"재계산 payload로 직접 변환할 수 없는 의도입니다: {intent.action}")

    input_payload = snapshot.get("input") or {}
    items = [item for item in input_payload.get("items") or [] if isinstance(item, dict)]
    context = dict(input_payload.get("context") or {})
    target_line_id = str(target_line.get("line_id") or "")
    target_name = str(target_line.get("input_name") or "")

    rebuilt_items = []
    for index, item in enumerate(items):
        rebuilt = _safe_item_payload(item, index)
        is_target = (
            target_line_id
            and str(item.get("line_id") or "") == target_line_id
        ) or (
            target_name
            and str(item.get("input_name") or "") == target_name
        )
        if is_target:
            amount = _target_amount(target_line, item)
            rebuilt.update(_category_override(intent.action, amount))
        rebuilt_items.append(rebuilt)

    if not rebuilt_items:
        for index, line in enumerate(_snapshot_lines(snapshot)):
            rebuilt = _line_to_item_payload(line, index)
            if line is target_line:
                amount = _target_amount(target_line, {})
                rebuilt.update(_category_override(intent.action, amount))
            rebuilt_items.append(rebuilt)

    return {"items": rebuilt_items, "context": context}


def line_payable_amount(line: dict) -> Decimal:
    return _money(line.get("payable_amount"))


def snapshot_payable_amount(snapshot: dict) -> Decimal:
    result = snapshot.get("result") or {}
    return _money(result.get("payable_amount"))


def money_text(value: Decimal) -> str:
    return f"{int(value):,}"


def _snapshot_lines(snapshot: dict) -> list[dict]:
    result = snapshot.get("result") or {}
    return [line for line in result.get("line_results") or [] if isinstance(line, dict)]


def _unique_lines(lines: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for line in lines:
        key = (str(line.get("line_id") or ""), str(line.get("input_name") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _matching_target_results_differ(snapshots: list[dict], target_text: str) -> bool:
    signatures = {
        tuple(
            sorted(
                (
                    str(line.get("input_name") or ""),
                    str(line.get("category") or ""),
                    str(line.get("claimed_amount") or ""),
                    str(line.get("deductible") or ""),
                    str(line.get("payable_amount") or ""),
                    str(line.get("human_task_amount") or ""),
                    str(line.get("calculation_status") or ""),
                )
                for line in find_target_lines(snapshot, target_text)
            )
        )
        for snapshot in snapshots
    }
    return len(signatures) > 1


def _safe_item_payload(item: dict, index: int) -> dict:
    return {
        "line_id": str(item.get("line_id") or f"line-{index + 1}"),
        "input_name": str(item.get("input_name") or f"항목 {index + 1}"),
        "input_code": str(item.get("input_code") or ""),
        "claimed_amount": str(item.get("claimed_amount") or "0"),
        "insured_copay_amount": str(item.get("insured_copay_amount") or "0"),
        "nonpay_amount": str(item.get("nonpay_amount") or "0"),
        "quantity": str(item.get("quantity") or "1"),
        "user_category_hint": str(item.get("user_category_hint") or ""),
        "extra_info": "",
    }


def _line_to_item_payload(line: dict, index: int) -> dict:
    return {
        "line_id": str(line.get("line_id") or f"line-{index + 1}"),
        "input_name": str(line.get("input_name") or f"항목 {index + 1}"),
        "input_code": str(line.get("input_code") or ""),
        "claimed_amount": str(line.get("claimed_amount") or "0"),
        "insured_copay_amount": str(line.get("insured_copay_amount") or "0"),
        "nonpay_amount": str(line.get("nonpay_amount") or "0"),
        "quantity": "1",
        "user_category_hint": str(line.get("category") or ""),
        "extra_info": "",
    }


def _target_amount(line: dict, item: dict) -> str:
    for key in ("claimed_amount", "human_task_amount", "nonpay_amount", "insured_copay_amount"):
        value = line.get(key)
        if _money(value) > 0:
            return str(value)
    for key in ("claimed_amount", "nonpay_amount", "insured_copay_amount"):
        value = item.get(key)
        if _money(value) > 0:
            return str(value)
    return "0"


def _category_override(action: str, amount: str) -> dict:
    if action == "as_insured_copay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": amount,
            "nonpay_amount": "0",
            "user_category_hint": "급여 본인부담",
        }
    if action == "as_three_major_nonpay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": "0",
            "nonpay_amount": amount,
            "user_category_hint": "3대비급여",
        }
    if action == "as_nonpay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": "0",
            "nonpay_amount": amount,
            "user_category_hint": "비급여",
        }
    return {}


def _money(value: Any) -> Decimal:
    text = str(value or "").replace(",", "").replace("원", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _target_before_marker(text: str) -> str:
    condition_markers = [
        "보상하지",
        "보상 제외",
        "급여 본인부담",
        "3대비급여",
        "비급여로",
        "보상한다면",
    ]
    condition_start = min(
        [text.find(marker) for marker in condition_markers if marker in text] or [len(text)]
    )
    specific_markers = ["항목을", "항목은"]
    for marker in specific_markers:
        index = text.rfind(marker, 0, condition_start)
        if index != -1:
            return text[:index].strip()

    target_markers = ["을", "를", "가", "이", "은", "는"]
    matches = [
        (index, -len(marker), marker)
        for marker in target_markers
        if (index := text.rfind(marker, 0, condition_start)) != -1
    ]
    if matches:
        index, _, _ = max(matches)
        return text[:index].strip()
    return ""
