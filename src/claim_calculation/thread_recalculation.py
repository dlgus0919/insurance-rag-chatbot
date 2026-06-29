from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


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
    if not snapshots:
        return None, "이 스레드에는 기준이 되는 보험금 계산 내역이 없습니다. 먼저 보험금 계산 기능으로 계산을 저장한 뒤 다시 질문해 주세요."
    if len(snapshots) == 1:
        return snapshots[0], ""

    normalized = " ".join(query.split())
    if any(marker in normalized for marker in ("최근 계산", "마지막 계산", "직전 계산")):
        return snapshots[-1], ""

    return (
        None,
        "이 스레드에 보험금 계산 내역이 여러 건 있습니다. 어떤 계산을 기준으로 바꿀지 명확하지 않습니다. 예: '최근 계산 기준으로 비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요.'",
    )


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
