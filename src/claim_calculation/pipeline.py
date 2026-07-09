"""보험금 계산 파이프라인 통합 모듈."""

from __future__ import annotations

import logging
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src import config
from src.claim_calculation.models import (
    ClaimItemInput,
    ClaimCaseContext,
    StandardMatch,
    BasisSelection,
    CalculationPlan,
    CalculationResult,
    SPECIAL_CALCULATION_APPLIED,
    SPECIAL_CALCULATION_NOT_APPLIED,
    normalize_special_calculation_status,
)
from src.claim_calculation.standard_matcher import match_standard_code
from src.claim_calculation.basis_selector import select_basis_documents
from src.claim_calculation.planner import LLMPlanner, FakePlanner

logger = logging.getLogger(__name__)


def _normalize_policy_generation(value: str) -> str:
    normalized = (value or "5th").strip().lower()
    if normalized in {"4", "4th", "4세대", "fourth"}:
        return "4th"
    return "5th"


def _classify_claim_category(item: ClaimItemInput, match: StandardMatch | None) -> str:
    text = " ".join(
        [
            item.user_category_hint or "",
            item.input_name or "",
            match.ins_care_type_cd_nm if match else "",
            match.pay_opn_cd_nm if match else "",
            match.mid_category_cd_nm if match else "",
        ]
    )
    if "비중증" in text:
        return "비중증비급여"
    if "중증" in text:
        return "중증비급여"
    if "3대" in text or "도수" in text or "체외충격파" in text or "증식" in text or "주사" in text or "mri" in text.lower() or "mra" in text.lower():
        return "3대비급여"
    if "비급여" in text:
        return "비급여"
    if "급여" in text:
        return "급여"
    return "미분류"


THREE_MAJOR_BLOCK_KEYWORDS = ("도수", "체외충격파", "증식", "주사")
MRI_MRA_KEYWORDS = ("mri", "mra", "자기공명영상")


def _special_status(context: ClaimCaseContext) -> str:
    return normalize_special_calculation_status(getattr(context, "special_calculation_status", "unknown"))


def _is_mri_mra_item(item: ClaimItemInput, match: StandardMatch | None) -> bool:
    text = " ".join([item.input_name or "", item.user_category_hint or "", _standard_match_text(match)]).lower()
    return any(keyword in text for keyword in MRI_MRA_KEYWORDS)


def _is_three_major_nonpay_item(category: str, item: ClaimItemInput, match: StandardMatch | None) -> bool:
    if category == "3대비급여":
        return True
    if category in {"중증비급여", "비중증비급여"}:
        return False
    text = " ".join([item.input_name or "", item.user_category_hint or "", _standard_match_text(match)]).lower()
    return any(keyword in text for keyword in THREE_MAJOR_BLOCK_KEYWORDS) or _is_mri_mra_item(item, match)


def _fifth_generation_special_category(
    category: str,
    item: ClaimItemInput,
    match: StandardMatch | None,
    context: ClaimCaseContext,
) -> tuple[str, str]:
    if _normalize_policy_generation(context.policy_generation) != "5th":
        return category, ""
    if not _is_three_major_nonpay_item(category, item, match):
        return category, ""

    status = _special_status(context)
    if status == SPECIAL_CALCULATION_APPLIED:
        return "중증비급여", ""
    if status == SPECIAL_CALCULATION_NOT_APPLIED and _is_mri_mra_item(item, match):
        from src.claim_calculation.deductible_rules import has_exact_rule

        if not has_exact_rule("5th", "비급여자기공명영상진단", context.visit_type, context.facility_grade):
            return "비급여자기공명영상진단", "5세대 산정특례 미적용 MRI/MRA 전용 계산 rule이 아직 승인되지 않아 자동 지급 산정하지 않습니다."
        return "비급여자기공명영상진단", ""
    if status == SPECIAL_CALCULATION_NOT_APPLIED:
        return category, "산정특례 미적용 케이스에서는 도수치료, 체외충격파, 증식치료, 주사료 계열 3대비급여를 자동 지급 산정하지 않습니다."
    if _is_mri_mra_item(item, match):
        return "비급여자기공명영상진단", "5세대 MRI/MRA 계산에는 산정특례 적용 여부 확인이 필요합니다."
    return category, "5세대 3대비급여 계산에는 산정특례 적용 여부 확인이 필요합니다."


def _is_exclusion_match(match: StandardMatch | None) -> bool:
    """Return whether the structured standard-code opinion marks the item as excluded."""

    if match is None:
        return False
    opinion = (match.pay_opn_cd_nm or "").strip()
    return "면책" in opinion or "보상제외" in opinion or opinion in {"제외", "미보상"}


def _standard_match_text(match: StandardMatch | None) -> str:
    if match is None:
        return ""
    return " ".join(
        [
            match.std_cd or "",
            match.std_cd_nm or "",
            match.mid_category_cd_nm or "",
            match.hira_care_type_cd_nm or "",
            match.ins_care_type_cd_nm or "",
            match.medical_class_cd_nm or "",
            match.item_class_level1cd_nm or "",
            match.item_class_level2cd_nm or "",
            match.pay_opn_cd_nm or "",
            match.notes or "",
        ]
    )


def _is_nonpay_scope_restriction(match: StandardMatch | None) -> bool:
    """비급여표준모델 의견이 급여외/비급여 산정 제한으로 읽히는지 판정한다."""

    text = _standard_match_text(match)
    compact = "".join(text.split())
    return (
        ("급여외" in compact and "산정불가" in compact)
        or ("비급여" in compact and "산정불가" in compact)
        or ("비급여" in compact and _is_exclusion_match(match))
    )


def _has_split_amounts(item: ClaimItemInput) -> bool:
    return bool(str(item.insured_copay_amount or "").strip() or str(item.nonpay_amount or "").strip())


def _line_amount_parts(item: ClaimItemInput) -> tuple[Decimal, Decimal, Decimal, bool]:
    """청구 라인을 급여 본인부담/비급여 금액으로 분해한다.

    새 영수증형 입력이 없으면 기존 claimed_amount 단일 금액 흐름을 유지한다.
    """

    from src.claim_calculation.models import parse_money, parse_money_or_zero, parse_quantity

    quantity = parse_quantity(item.quantity)
    split_mode = _has_split_amounts(item)
    if not split_mode:
        unit_amount = parse_money(item.claimed_amount)
        amount = unit_amount * quantity
        return Decimal("0"), Decimal("0"), amount, False

    insured_copay = parse_money_or_zero(item.insured_copay_amount) * quantity
    nonpay = parse_money_or_zero(item.nonpay_amount) * quantity
    total = insured_copay + nonpay
    if total <= 0:
        raise ValueError("급여 본인부담금 또는 비급여 금액 중 하나는 0원보다 커야 합니다.")
    return insured_copay, nonpay, total, True


def _format_decimal_won(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", "")


def _nonpay_category_for_split_line(item: ClaimItemInput, match: StandardMatch | None) -> str:
    category = _classify_claim_category(item, match)
    if category in {"급여", "미분류"}:
        return "비급여"
    return category


def _is_unresolved_nonpay(category: str, match: StandardMatch | None) -> bool:
    """보장 유형이 확정되지 않은 비급여인지 판정한다.

    4/5세대 모두 비급여라는 넓은 범주만으로는 자동 산정 근거가 부족하다.
    다만 표준모델 행이 있고 보상의견이 명확한 경우에는 기존 계산 흐름을 유지한다.
    """

    if category != "비급여":
        return False
    if match and not match.requires_review and (match.pay_opn_cd_nm or match.ins_care_type_cd_nm):
        return False
    return True


def _unresolved_nonpay_human_task_reason() -> str:
    return "미분류 비급여는 보장/면책/특약 여부가 확정되지 않아 자동 지급 계산에서 제외하고 Human Task로 분류했습니다."


def _is_human_task_line(line_reasons: list[str]) -> bool:
    return any("Human Task" in reason for reason in line_reasons)


def _line_calculation_status(
    has_human_task: bool,
    insured_copay_amount: Decimal,
    payable: Decimal,
    deductible: Decimal,
) -> str:
    if not has_human_task:
        return "calculated"
    if insured_copay_amount > 0 or payable > 0 or deductible > 0:
        return "partial_human_task"
    return "human_task"


def _match_basis_summary(match: StandardMatch | None) -> str:
    if match is None:
        return ""
    parts = []
    if match.hira_care_type_cd_nm:
        parts.append(f"HIRA구분: {match.hira_care_type_cd_nm}")
    if match.ins_care_type_cd_nm:
        parts.append(f"보험구분: {match.ins_care_type_cd_nm}")
    if match.medical_class_cd_nm:
        parts.append(f"의료분류: {match.medical_class_cd_nm}")
    if match.item_class_level1cd_nm:
        parts.append(f"항목1: {match.item_class_level1cd_nm}")
    if match.item_class_level2cd_nm:
        parts.append(f"항목2: {match.item_class_level2cd_nm}")
    if match.pay_opn_cd_nm:
        parts.append(f"보상의견: {match.pay_opn_cd_nm}")
    return " | ".join(parts)


def _is_evidence_requirement_satisfied(requirement: str, provided_tags: list[str]) -> bool:
    normalized_requirement = "".join((requirement or "").split())
    if not normalized_requirement:
        return True
    for tag in provided_tags or []:
        normalized_tag = "".join((tag or "").split())
        if normalized_tag and (normalized_requirement in normalized_tag or normalized_tag in normalized_requirement):
            return True
    return False


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _is_confirmed_exclusion_step(step: Any) -> bool:
    if getattr(step, "status", "") != "confirmed":
        return False
    if getattr(step, "relation", "") == "HAS_DECISION" and getattr(step, "object", "") == "면책":
        return True
    notes = str(getattr(step, "notes", "") or "")
    return getattr(step, "relation", "") == "RELATES_TO_COMPLICATION" and notes.startswith("exclusion")


def _line_deductible(
    amount: Decimal,
    category: str,
    generation: str,
    visit_type: str,
    facility_grade: str = "",
) -> tuple[Decimal, str, list[str]]:
    """deductible_rules 테이블 기반 공제금액 산출."""
    from src.claim_calculation.deductible_rules import lookup_rule

    review_reasons: list[str] = []
    rule_entry = lookup_rule(generation, category, visit_type, facility_grade)
    ratio = rule_entry.copay_ratio
    min_deductible = rule_entry.get_min_deductible(facility_grade)
    rule_desc = rule_entry.description

    # 5세대 비급여 미분류 경고
    if generation == "5th" and category == "비급여":
        review_reasons.append("5세대 비급여는 중증/비중증 구분에 따라 공제율이 달라질 수 있어 항목 분류 확인이 필요합니다.")
    elif generation == "5th" and category == "3대비급여":
        review_reasons.append("5세대의 도수치료 등 3대비급여는 비중증 비급여 또는 선택형 특약 여부에 따라 보장 여부와 공제율 확인이 필요합니다.")
    elif category == "미분류":
        if generation == "5th":
            review_reasons.append("항목의 급여/비급여/중증 여부가 불명확하여 세대별 정확 계산을 위해 영수증·세부내역서 확인이 필요합니다.")
        else:
            review_reasons.append("항목의 급여/비급여 구분이 불명확하여 영수증·세부내역서 확인이 필요합니다.")

    deductible = max(min_deductible, amount * ratio)
    if deductible > amount:
        deductible = amount
    return deductible, rule_desc, review_reasons


def _is_prescription(item: ClaimItemInput) -> bool:
    """항목이 처방약(약제비)인지 판단한다. 사용자 명시 우선, 키워드 자동 감지 보조."""
    if item.is_prescription:
        return True
    if item.user_category_hint == "처방약":
        return True
    name = (item.input_name or "").strip()
    keywords = ["처방약", "약제비", "조제료", "약국", "처방전", "약값"]
    return any(k in name for k in keywords)


def _prescription_deductible(
    amount: Decimal,
    generation: str,
    facility_grade: str = "",
) -> tuple[Decimal, str, list[str]]:
    """처방약(약제비) 전용 공제 계산."""
    from src.claim_calculation.deductible_rules import lookup_prescription_rule

    review_reasons: list[str] = []
    rx_rule = lookup_prescription_rule(generation)
    deductible = rx_rule.deductible_amount
    if deductible > amount:
        deductible = amount
    return deductible, rx_rule.description, review_reasons


def _apply_standard_deductible(
    amount: Decimal,
    category: str,
    generation: str,
    context: ClaimCaseContext,
) -> tuple[Decimal, Decimal, str, list[str]]:
    """세대/입원통원/의료기관 기준 공제와 건당 한도를 적용한다."""

    deductible, rule, review_reasons = _line_deductible(
        amount,
        category,
        generation,
        context.visit_type,
        context.facility_grade,
    )
    payable = amount - deductible

    from src.claim_calculation.deductible_rules import lookup_rule as _lookup_rule

    rule_entry = _lookup_rule(generation, category, context.visit_type, context.facility_grade)
    if rule_entry.per_visit_limit and payable > rule_entry.per_visit_limit:
        excess = payable - rule_entry.per_visit_limit
        payable = rule_entry.per_visit_limit
        deductible = amount - payable
        review_reasons.append(f"건당 한도 {rule_entry.per_visit_limit:,.0f}원 초과분 {excess:,.0f}원은 자기부담입니다.")

    return payable, deductible, rule, review_reasons


def _is_health_insurance_unapplied(context: ClaimCaseContext) -> bool:
    text = " ".join([context.coverage_topic or "", context.situation_note or ""])
    return any(keyword in text for keyword in ["요양급여 미적용", "건강보험 미적용", "건강보험 적용받지 못", "급여 적용받지 못"])


def _is_upper_room_difference(item: ClaimItemInput) -> bool:
    text = " ".join([item.input_name or "", item.user_category_hint or ""])
    return "상급병실" in text or "병실료 차액" in text


def _has_coordination_signal(context: ClaimCaseContext) -> bool:
    text = " ".join(
        [
            context.coverage_topic or "",
            context.situation_note or "",
            context.diagnosis_name or "",
            context.accident_type or "",
        ]
    )
    return any(keyword in text for keyword in config.CLAIM_COORDINATION_SIGNAL_KEYWORDS)


def _deductible_group_for_category(category: str) -> str:
    if category == "급여":
        return "benefit_group"
    if category == "비급여자기공명영상진단":
        return "mri_mra_group"
    if category == "3대비급여":
        return "three_major_nonpay_group"
    if category in {"비급여", "비중증비급여", "중증비급여"}:
        return "general_nonpay_group"
    return ""


def _line_is_group_eligible(line: dict[str, str | bool | list[str]]) -> bool:
    if not line.get("deductible_group"):
        return False
    if line.get("excluded_from_calculation") is True:
        return False
    if line.get("calculation_status") in {"human_task", "partial_human_task"}:
        return False
    return Decimal(str(line.get("claimed_amount") or "0")) > 0


def _deductible_group_key(
    line: dict[str, str | bool | list[str]],
    context: ClaimCaseContext,
) -> tuple[str, str, str, str, str, str]:
    return (
        str(line.get("policy_generation") or ""),
        context.visit_type or "",
        context.facility_grade or "",
        _special_status(context),
        str(line.get("category") or ""),
        str(line.get("deductible_group") or ""),
    )


def _allocate_won(total: Decimal, amounts: list[Decimal]) -> list[Decimal]:
    if not amounts:
        return []
    amount_sum = sum(amounts, Decimal("0"))
    if amount_sum <= 0:
        return [Decimal("0") for _ in amounts]
    allocated: list[Decimal] = []
    running = Decimal("0")
    for amount in amounts[:-1]:
        part = (total * amount / amount_sum).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        allocated.append(part)
        running += part
    allocated.append(total - running)
    return allocated


def _apply_grouped_deductibles(
    line_results: list[dict[str, str | bool | list[str]]],
    context: ClaimCaseContext,
) -> tuple[Decimal, Decimal, list[str]]:
    # 보험 지식값이 아니라 같은 공제 단위는 합산 후 1회 공제한다는 계산 엔진 규칙이다.
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, str | bool | list[str]]]] = {}
    for line in line_results:
        if _line_is_group_eligible(line):
            groups.setdefault(_deductible_group_key(line, context), []).append(line)

    review_reasons: list[str] = []
    generation = _normalize_policy_generation(context.policy_generation)
    for group_lines in groups.values():
        if len(group_lines) < 2:
            continue
        category = str(group_lines[0].get("category") or "미분류")
        group_amounts = [Decimal(str(line.get("claimed_amount") or "0")) for line in group_lines]
        group_amount = sum(group_amounts, Decimal("0"))
        group_payable, group_deductible, group_rule, group_review = _apply_standard_deductible(
            group_amount,
            category,
            generation,
            context,
        )
        payable_parts = _allocate_won(group_payable, group_amounts)
        deductible_parts = _allocate_won(group_deductible, group_amounts)
        for line, payable, deductible in zip(group_lines, payable_parts, deductible_parts):
            line["payable_amount"] = _format_decimal_won(payable)
            line["deductible"] = _format_decimal_won(deductible)
            line["rule_summary"] = f"{line.get('rule_summary')}; 동일 공제 그룹 합산 적용: {group_rule}"
            line_reasons = list(line.get("review_reasons") or [])
            line_reasons.extend(reason for reason in group_review if reason not in line_reasons)
            line["review_reasons"] = line_reasons
            if group_review:
                line["requires_review"] = True
        review_reasons.extend(reason for reason in group_review if reason not in review_reasons)

    total_payable = sum(
        Decimal(str(line.get("payable_amount") or "0"))
        for line in line_results
        if line.get("excluded_from_calculation") is not True
    )
    total_deductible = sum(
        Decimal(str(line.get("deductible") or "0"))
        for line in line_results
        if line.get("excluded_from_calculation") is not True
    )
    return total_payable, total_deductible, review_reasons


def _calculate_line_items(
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    standard_matches: list[StandardMatch],
) -> tuple[Decimal, Decimal, list[dict[str, str | bool | list[str]]], list[str]]:
    from src.claim_calculation.models import parse_quantity

    generation = _normalize_policy_generation(context.policy_generation)
    total_payable = Decimal("0")
    total_deductible = Decimal("0")
    line_results: list[dict[str, str | bool | list[str]]] = []
    review_reasons: list[str] = []

    for idx, item in enumerate(items):
        quantity = parse_quantity(item.quantity)
        insured_copay_amount, nonpay_amount, amount, split_mode = _line_amount_parts(item)
        unit_amount = amount / quantity
        match = standard_matches[idx] if idx < len(standard_matches) else None
        category = _classify_claim_category(item, match)
        line_review = False
        line_reasons: list[str] = []

        if _is_upper_room_difference(item):
            from src.claim_calculation.deductible_rules import lookup_special_rule
            special_rule = lookup_special_rule("upper_room_difference")
            if special_rule.daily_limit is None or special_rule.payout_ratio is None:
                raise ValueError("upper_room_difference special rule requires daily_limit and payout_ratio")
            capped_daily_amount = min(unit_amount, special_rule.daily_limit)
            payable = capped_daily_amount * quantity * special_rule.payout_ratio
            deductible = amount - payable
            rule = special_rule.description
        elif _is_ambiguous_match(match):
            deductible = Decimal("0")
            payable = Decimal("0")
            rule = "표준모델 후보 모호성으로 계산 보류"
            line_review = True
            line_reasons.append("동일 항목명에 복수 표준모델 후보가 있어 임의 후보로 보험금을 산출하지 않았습니다. 정확한 수가/표준코드를 입력해야 합니다.")
        elif split_mode:
            payable = Decimal("0")
            deductible = Decimal("0")
            rule_parts: list[str] = []
            category_parts: list[str] = []

            if insured_copay_amount > 0:
                insured_payable, insured_deductible, insured_rule, insured_review = _apply_standard_deductible(
                    insured_copay_amount,
                    "급여",
                    generation,
                    context,
                )
                payable += insured_payable
                deductible += insured_deductible
                category_parts.append("급여")
                rule_parts.append(f"급여 본인부담금: {insured_rule}")
                line_reasons.extend(insured_review)
                if insured_review:
                    line_review = True

            if nonpay_amount > 0:
                nonpay_category = _nonpay_category_for_split_line(item, match)
                category_parts.append(nonpay_category)
                nonpay_category, special_block_reason = _fifth_generation_special_category(
                    nonpay_category,
                    item,
                    match,
                    context,
                )
                category_parts[-1] = nonpay_category
                if special_block_reason:
                    rule_parts.append("비급여 금액: 산정특례 상태 확인 필요로 자동 산정 제외")
                    line_review = True
                    line_reasons.append(special_block_reason)
                elif _is_nonpay_scope_restriction(match):
                    nonpay_deductible = nonpay_amount
                    deductible += nonpay_deductible
                    opinion = match.pay_opn_cd_nm if match else "산정불가"
                    code = f"코드 {match.std_cd} " if match and match.std_cd else ""
                    rule_parts.append(f"비급여 금액: 비급여 표준모델 {code}보상의견 '{opinion}'에 따라 지급예상액 0원")
                    line_review = True
                    line_reasons.append(
                        "비급여표준모델의 급여외/비급여 산정 제한 의견을 비급여 금액에 적용했습니다. 급여 본인부담금은 별도 급여 실손 규칙으로 계산했습니다."
                    )
                elif _is_unresolved_nonpay(nonpay_category, match):
                    rule_parts.append("비급여 금액: 미분류 비급여 Human Task 분류로 자동 산정 제외")
                    line_review = True
                    line_reasons.append(_unresolved_nonpay_human_task_reason())
                else:
                    nonpay_payable, nonpay_deductible, nonpay_rule, nonpay_review = _apply_standard_deductible(
                        nonpay_amount,
                        nonpay_category,
                        generation,
                        context,
                    )
                    payable += nonpay_payable
                    deductible += nonpay_deductible
                    rule_parts.append(f"비급여 금액: {nonpay_rule}")
                    line_reasons.extend(nonpay_review)
                    if nonpay_review:
                        line_review = True

            if not category_parts:
                category_parts.append("미분류")
            category = "+".join(dict.fromkeys(category_parts))
            table_basis = _match_basis_summary(match)
            rule = "; ".join(rule_parts) if rule_parts else "급여/비급여 분리 입력 계산"
            if table_basis:
                rule = f"{rule}; 표준모델 행 정보({table_basis})"
            if nonpay_amount > 0 and _is_human_task_line(line_reasons):
                category = category.replace("비급여", "미분류 비급여")
        elif _is_exclusion_match(match):
            deductible = amount
            payable = Decimal("0")
            opinion = match.pay_opn_cd_nm or "면책"
            code = f"코드 {match.std_cd} " if match and match.std_cd else ""
            rule = f"비급여 표준모델 {code}보상의견 '{opinion}'에 따른 지급예상액 0원"
            line_review = True
            line_reasons.append("비급여 표준모델 보상의견이 면책/보상제외로 표시되어 자동 계산 지급예상액을 0원으로 처리했습니다.")
            if match and match.requires_user_disambiguation:
                line_reasons.append("동일 항목명에 보상 후보가 함께 존재하므로 정확한 표준코드 입력 또는 증빙 확인이 필요합니다.")
        elif "제외" in item.input_name or "not_covered" in item.input_name:
            deductible = amount
            payable = Decimal("0")
            rule = "보상 제외 항목으로 입력되어 지급예상액 0원"
            line_review = True
            line_reasons.append("보상 대상 또는 면책 여부를 약관 및 치료 목적 서류로 재확인해야 합니다.")
        elif "정보부족" in item.input_name or "needs_more_info" in item.input_name:
            deductible = Decimal("0")
            payable = Decimal("0")
            rule = "계산 보류"
            line_review = True
            line_reasons.append("정보가 부족하여 진료비 영수증 또는 진료비 세부내역서의 항목 구분 확인이 필요합니다.")
        elif _is_prescription(item):
            from src.claim_calculation.deductible_rules import lookup_prescription_rule
            rx_rule = lookup_prescription_rule(generation)
            deductible = rx_rule.deductible_amount
            if deductible > amount:
                deductible = amount
            payable = amount - deductible
            # 처방약 건당 한도 적용
            if rx_rule.per_visit_limit and payable > rx_rule.per_visit_limit:
                excess = payable - rx_rule.per_visit_limit
                payable = rx_rule.per_visit_limit
                deductible = amount - payable
                line_reasons.append(f"처방약 건당 한도 {rx_rule.per_visit_limit:,.0f}원 초과분 {excess:,.0f}원은 자기부담입니다.")
            rule = rx_rule.description
            category = "처방약"
        else:
            category, special_block_reason = _fifth_generation_special_category(category, item, match, context)
            if special_block_reason:
                deductible = Decimal("0")
                payable = Decimal("0")
                rule = "산정특례 상태 확인 필요로 자동 산정 제외"
                line_review = True
                line_reasons.append(special_block_reason)
                total_payable += payable
                total_deductible += deductible
                review_reasons.extend(line_reasons)
                line_results.append(
                    {
                        "line_id": item.line_id,
                        "input_name": item.input_name,
                        "input_code": item.input_code,
                        "category": category,
                        "claimed_amount": _format_decimal_won(amount),
                        "insured_copay_amount": _format_decimal_won(insured_copay_amount),
                        "nonpay_amount": _format_decimal_won(nonpay_amount),
                        "deductible": _format_decimal_won(deductible),
                        "payable_amount": _format_decimal_won(payable),
                        "policy_generation": generation,
                        "rule_summary": rule,
                        "extra_info": item.extra_info,
                        "requires_review": line_review,
                        "review_reasons": line_reasons,
                        "calculation_status": "human_task",
                        "excluded_from_calculation": True,
                        "human_task_amount": _format_decimal_won(amount),
                        "deductible_group": "",
                    }
                )
                continue
            if _is_unresolved_nonpay(category, match):
                deductible = Decimal("0")
                payable = Decimal("0")
                rule = "미분류 비급여 Human Task 분류로 자동 산정 제외"
                category = "미분류 비급여"
                line_review = True
                line_reasons.append(_unresolved_nonpay_human_task_reason())
                total_payable += payable
                total_deductible += deductible
                review_reasons.extend(line_reasons)
                line_results.append(
                    {
                        "line_id": item.line_id,
                        "input_name": item.input_name,
                        "input_code": item.input_code,
                        "category": category,
                        "claimed_amount": _format_decimal_won(amount),
                        "insured_copay_amount": _format_decimal_won(insured_copay_amount),
                        "nonpay_amount": _format_decimal_won(nonpay_amount),
                        "deductible": _format_decimal_won(deductible),
                        "payable_amount": _format_decimal_won(payable),
                        "policy_generation": generation,
                        "rule_summary": rule,
                        "extra_info": item.extra_info,
                        "requires_review": line_review,
                        "review_reasons": line_reasons,
                        "calculation_status": "human_task",
                        "excluded_from_calculation": True,
                        "human_task_amount": _format_decimal_won(amount),
                        "deductible_group": "",
                    }
                )
                continue
            deductible, rule, category_review = _line_deductible(amount, category, generation, context.visit_type, context.facility_grade)
            payable = amount - deductible
            line_reasons.extend(category_review)
            line_review = bool(category_review)

            # 건당 한도 적용
            from src.claim_calculation.deductible_rules import lookup_rule as _lookup_rule
            _rule_entry = _lookup_rule(generation, category, context.visit_type, context.facility_grade)
            if _rule_entry.per_visit_limit and payable > _rule_entry.per_visit_limit:
                excess = payable - _rule_entry.per_visit_limit
                payable = _rule_entry.per_visit_limit
                deductible = amount - payable
                line_reasons.append(f"건당 한도 {_rule_entry.per_visit_limit:,.0f}원 초과분 {excess:,.0f}원은 자기부담입니다.")
                line_review = True

            if _is_health_insurance_unapplied(context):
                from src.claim_calculation.deductible_rules import lookup_special_rule
                special_rule = lookup_special_rule("health_insurance_unapplied")
                if special_rule.payout_ratio is None:
                    raise ValueError("health_insurance_unapplied special rule requires payout_ratio")
                base_after_deductible = max(Decimal("0"), amount - deductible)
                payable = base_after_deductible * special_rule.payout_ratio
                deductible = amount - payable
                rule = f"{rule}; {special_rule.description}"
                line_review = True
                line_reasons.append(f"{special_rule.description} 적용 사유 확인이 필요합니다.")

        has_human_task = _is_human_task_line(line_reasons)
        calculation_status = _line_calculation_status(
            has_human_task,
            insured_copay_amount,
            payable,
            deductible,
        )
        human_task_amount = nonpay_amount if has_human_task and nonpay_amount > 0 else (amount if calculation_status == "human_task" else Decimal("0"))

        total_payable += payable
        total_deductible += deductible
        review_reasons.extend(line_reasons)
        line_results.append(
            {
                "line_id": item.line_id,
                "input_name": item.input_name,
                "input_code": item.input_code,
                "category": category,
                "claimed_amount": _format_decimal_won(amount),
                "insured_copay_amount": _format_decimal_won(insured_copay_amount),
                "nonpay_amount": _format_decimal_won(nonpay_amount),
                "deductible": _format_decimal_won(deductible),
                "payable_amount": _format_decimal_won(payable),
                "policy_generation": generation,
                "rule_summary": rule,
                "extra_info": item.extra_info,
                "requires_review": line_review,
                "review_reasons": line_reasons,
                "calculation_status": calculation_status,
                "excluded_from_calculation": calculation_status == "human_task",
                "human_task_amount": _format_decimal_won(human_task_amount),
                "deductible_group": "" if calculation_status == "human_task" else _deductible_group_for_category(category),
            }
        )

    grouped_payable, grouped_deductible, grouped_reviews = _apply_grouped_deductibles(line_results, context)
    review_reasons.extend(reason for reason in grouped_reviews if reason not in review_reasons)
    return grouped_payable, grouped_deductible, line_results, review_reasons


def _has_exclusion_match(standard_matches: list[StandardMatch]) -> bool:
    """표준모델 DB가 면책/보상제외로 판정한 행이 있는지 확인한다."""

    return any(_is_exclusion_match(match) for match in standard_matches)


def _is_ambiguous_match(match: StandardMatch | None) -> bool:
    """복수 후보로 인해 산출을 보류해야 하는 표준모델 매칭인지 확인한다."""

    return bool(match and match.requires_user_disambiguation and not match.std_cd)


def _should_trust_deterministic_baseline(
    standard_matches: list[StandardMatch],
    disambiguation_required: bool,
) -> bool:
    """계산 파이프라인의 최종값을 결정론 규칙으로 보호해야 하는지 판정한다."""

    if disambiguation_required:
        return False
    if not standard_matches:
        return False
    return all(not _is_ambiguous_match(match) for match in standard_matches)


def _build_deterministic_formula_code(claimed: Decimal, deductible: Decimal, payable: Decimal) -> str:
    """결정론 fallback이 적용된 경우에도 감사 가능한 계산 코드를 남긴다."""

    return (
        f"claimed_amount = Decimal('{claimed}')\n"
        f"deductible = Decimal('{deductible}')\n"
        f"payable_amount = Decimal('{payable}')"
    )


def run_claim_calculation(
    rag_pipeline: Any,
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    basis_mode: str = "auto",
    selected_basis_docs: list[str] | None = None,
    use_fake_planner: bool = True,
    model_id: str = "gpt-5.4-mini",
    provider: str = "openai",
) -> CalculationResult:
    """사용자 청구 및 상황 정보에 기반하여 RAG 근거 검색, DB 매칭, LLM 계획 및 샌드박스 실행을 통합 수행한다."""
    # 1. 근거 문서 구성 (자동/수동)
    basis: BasisSelection = select_basis_documents(
        items=items,
        context=context,
        basis_mode=basis_mode,
        selected_docs=selected_basis_docs
    )

    # 2. 비급여 표준모델 DB 매칭
    standard_matches: list[StandardMatch] = []
    disambiguation_required = False
    disambiguation_candidates = []
    db_review_required = False
    db_review_reasons = []

    for item in items:
        matches = match_standard_code(item.input_name, item.input_code)
        if not matches:
            # 매칭 없음 처리
            match_none = StandardMatch(
                std_cd_nm=item.input_name,
                match_confidence="none",
                requires_review=True
            )
            standard_matches.append(match_none)
            db_review_required = True
            db_review_reasons.append(f"항목 '{item.input_name}'에 매칭되는 비급여 표준모델 코드가 없습니다.")
        else:
            # 2개 이상 모호성 감지
            if len(matches) > 1 and not item.input_code.strip():
                disambiguation_required = True
                db_review_required = True
                candidate_info = ", ".join([f"{m.std_cd}({m.std_cd_nm})" for m in matches])
                db_review_reasons.append(
                    f"항목 '{item.input_name}'의 표준모델 매칭 후보가 2개 이상 존재하여 선택 모호성이 발생했습니다. "
                    f"후보군: [{candidate_info}]. 정확한 코드를 입력해주십시오."
                )
                for m in matches:
                    disambiguation_candidates.append({
                        "code": m.std_cd,
                        "name": m.std_cd_nm,
                        "mid_category": m.mid_category_cd_nm or ""
                    })
                standard_matches.append(
                    StandardMatch(
                        std_cd="",
                        std_cd_nm=item.input_name,
                        pay_opn_cd_nm="후보 모호",
                        match_confidence="ambiguous",
                        requires_user_disambiguation=True,
                        requires_review=True,
                    )
                )
                continue

            # 첫 번째 결과를 대표 매치로 선택
            repr_match = matches[0]
            if repr_match.requires_review:
                db_review_required = True
                opn = repr_match.pay_opn_cd_nm or "공란"
                db_review_reasons.append(f"항목 '{item.input_name}'의 보상의견이 추가 확인 대상입니다. (의견: {opn})")
            standard_matches.append(repr_match)

    # 총 청구금액 합산
    total_claimed = Decimal("0")
    for item in items:
        try:
            _, _, line_total, _ = _line_amount_parts(item)
            total_claimed += line_total
        except Exception as exc:
            # 파싱 에러 발생 시 외부로 버블링시켜 UI에서 방어할 수 있도록 함
            raise exc

    # 3. RAG 근거 문서 조회
    retrieved_evidences = []
    graph_result = None
    if rag_pipeline is not None and getattr(rag_pipeline, "graph_enabled", False) and rag_pipeline.graph_retriever:
        try:
            query_parts = []
            if context.situation_note:
                query_parts.append(context.situation_note)
            if context.diagnosis_code:
                query_parts.append(context.diagnosis_code)
            if context.diagnosis_name:
                query_parts.append(context.diagnosis_name)
            if context.coverage_topic:
                query_parts.append(context.coverage_topic)
            if context.complication_asserted:
                query_parts.append("합병증")
            if context.same_disease_claimed:
                query_parts.append("하나의 질병")
            if context.treatment_purpose:
                query_parts.append(context.treatment_purpose)
            if context.policy_generation:
                query_parts.append(context.policy_generation)
            if context.visit_type:
                query_parts.append("통원" if context.visit_type == "outpatient" else "입원")
            if context.facility_type:
                query_parts.append(context.facility_type)
            for tag in context.evidence_tags:
                query_parts.append(tag)
            for item in items:
                query_parts.append(item.input_name)
            question = " ".join(query_parts)
            graph_result = rag_pipeline.graph_retriever.retrieve(question)
            for fact in graph_result.facts:
                if fact.status == "confirmed":
                    # confirmed evidence가 없는 사실은 retrieved_evidences에서 배제
                    if not fact.evidence:
                        continue
                    retrieved_evidences.append({
                        "source": "GraphDB (확정)",
                        "content": f"[CONFIRMED] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'}",
                        "page": "N/A"
                    })
                elif fact.status == "candidate":
                    retrieved_evidences.append({
                        "source": "GraphDB (검토 후보)",
                        "content": f"[CANDIDATE] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'} (이유: {fact.properties.get('matched_keyword', '')} 매칭)",
                        "page": "N/A"
                    })
            for path in getattr(graph_result, "review_paths", []) or []:
                retrieved_evidences.append({
                    "source": f"GraphDB ReviewPath ({path.status})",
                    "content": f"{path.path_type}: {path.summary}",
                    "page": "N/A",
                    "display_in_applied_basis": False,
                })
        except Exception as e:
            logger.error(f"GraphDB 근거 조회 중 에러 발생: {e}")

    if rag_pipeline is not None and basis.doc_filter:
        rag_docs = [d for d in basis.doc_filter if d != "비급여 표준모델"]
        if rag_docs:
            query_parts = []
            if context.situation_note:
                query_parts.append(context.situation_note)
            for item in items:
                query_parts.append(item.input_name)
            question = " ".join(query_parts)

            try:
                # top_k는 명세 요구에 맞추어 적절한 개수(6개) 검색
                hits, _ = rag_pipeline.retrieve_hits(question, top_k=6, doc_filter=rag_docs)
                for hit in hits:
                    retrieved_evidences.append({
                        "source": hit.metadata.get("doc_short", "알수없음"),
                        "content": hit.document,
                        "page": hit.metadata.get("page_start", "?"),
                    })
            except Exception as e:
                logger.error(f"RAG 근거 조회 중 에러 발생: {e}")

    (
        baseline_payable_val,
        baseline_deductible_val,
        baseline_line_results,
        baseline_review_reasons,
    ) = _calculate_line_items(
        items=items,
        context=context,
        standard_matches=standard_matches,
    )
    deterministic_line_results: list[dict[str, str | bool | list[str]]] = []
    deterministic_review_reasons: list[str] = []
    has_exclusion = any(
        _is_exclusion_match(match) and (idx >= len(items) or not _has_split_amounts(items[idx]))
        for idx, match in enumerate(standard_matches)
    )
    has_split_scope_restriction = any(
        idx < len(items)
        and _has_split_amounts(items[idx])
        and (_is_exclusion_match(match) or _is_nonpay_scope_restriction(match))
        for idx, match in enumerate(standard_matches)
    )
    if use_fake_planner or has_exclusion or has_split_scope_restriction:
        payable_val = baseline_payable_val
        deductible_val = baseline_deductible_val
        deterministic_line_results = baseline_line_results
        deterministic_review_reasons = baseline_review_reasons
        sandbox_code = _build_deterministic_formula_code(total_claimed, deductible_val, payable_val)
        if has_exclusion:
            plan = CalculationPlan(
                decision="not_covered",
                formula_intent=sandbox_code,
                uncertainties=baseline_review_reasons,
            )
        else:
            plan = CalculationPlan(decision="calculable", formula_intent=sandbox_code)
    # 4. LLM 계산 계획 수립
    elif disambiguation_required:
        plan = CalculationPlan(
            decision="needs_more_info",
            uncertainties=db_review_reasons
        )
        payable_val = Decimal("0")
        deductible_val = Decimal("0")
        sandbox_code = ""
    else:
        planner = FakePlanner() if use_fake_planner else LLMPlanner(model_id=model_id, provider=provider)
        plan: CalculationPlan = planner.plan(items, context, retrieved_evidences)
        payable_val = baseline_payable_val
        deductible_val = baseline_deductible_val
        deterministic_line_results = baseline_line_results
        deterministic_review_reasons.extend(baseline_review_reasons)
        sandbox_code = _build_deterministic_formula_code(total_claimed, deductible_val, payable_val)
        if plan.formula_intent:
            deterministic_review_reasons.append(
                "LLM 산식은 최종 계산 권한이 아니므로 실행하지 않고 approved rule layer의 결정론 계산값을 적용했습니다."
            )
        if plan.decision == "not_covered":
            deterministic_review_reasons.append(
                "LLM 단독 면책 판단은 최종 권한이 아니므로 검토 필요 상태로 전환하고 approved rule layer 계산값을 유지했습니다."
            )
            plan = CalculationPlan(
                decision="needs_more_info",
                basis_summary=plan.basis_summary,
                variables=plan.variables,
                calculation_steps=plan.calculation_steps,
                formula_intent=plan.formula_intent,
                uncertainties=plan.uncertainties,
            )

    # 5. LLM formula_intent는 실행하지 않는다. 최종값은 approved rule layer 결과만 사용한다.
    sandbox_error_occurred = False
    sandbox_error_msg = ""

    # 6. 최종 지급예상액 검증 및 검토 플래그 결정
    review_required = False
    review_reasons = []
    missing_evidence: list[str] = []
    structured_review_actions: list[str] = []
    exclusion_reasons: list[str] = []
    benefit_limits: list[str] = []
    deductible_rules: list[str] = []
    required_documents: list[str] = []
    coordination_rules: list[str] = []
    generation_rules: list[str] = []
    confirmed_exclusion_path_found = False
    graph_review_paths_payload: list[dict[str, Any]] = []
    session_assertions_payload: list[dict[str, Any]] = []

    if deterministic_review_reasons:
        review_required = True
        review_reasons.extend(deterministic_review_reasons)

    # 결과값 정밀 검증
    if payable_val < 0:
        review_required = True
        review_reasons.append(f"지급예상액이 음수({payable_val})입니다. 0원 이상이어야 합니다.")
        payable_val = Decimal("0")

    if deductible_val < 0:
        review_required = True
        review_reasons.append(f"공제금액이 음수({deductible_val})입니다. 0원 이상이어야 합니다.")
        deductible_val = Decimal("0")

    if payable_val > total_claimed:
        review_required = True
        review_reasons.append(f"지급예상액({payable_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다.")

    if deductible_val > total_claimed:
        review_required = True
        review_reasons.append(f"공제금액({deductible_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다.")

    if payable_val + deductible_val > total_claimed:
        review_required = True
        review_reasons.append(
            f"지급예상액과 공제금액의 합({payable_val + deductible_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다."
        )

    # UI 및 결과 출력용으로 Decimal 값을 정수형 문자열 등으로 가공
    payable_str = f"{payable_val:,.0f}".replace(",", "")
    deductible_str = f"{deductible_val:,.0f}".replace(",", "")

    # Graph candidate rule 검토 플래그 강제 적용
    if graph_result:
        review_paths = getattr(graph_result, "review_paths", []) or []
        graph_review_paths_payload = [asdict(path) for path in review_paths]
        session_assertions_payload = [asdict(assertion) for assertion in getattr(graph_result, "session_assertions", []) or []]
        coordination_requested = _has_coordination_signal(context)
        if context.complication_asserted and review_paths:
            review_required = True
            reason = "합병증/후유증/부작용 상황이 주장되어 구조화 검토 경로와 추가 서류 확인이 필요합니다."
            if reason not in review_reasons:
                review_reasons.append(reason)

        for path in review_paths:
            if path.status in {"candidate", "review_required", "missing"}:
                review_required = True
            if path.required_evidence:
                review_required = True
                missing_requirements = [
                    req
                    for req in path.required_evidence
                    if not _is_evidence_requirement_satisfied(req, context.evidence_tags or [])
                ]
                if missing_requirements:
                    for req in missing_requirements:
                        _append_unique(missing_evidence, req)
                    reason = f"검토 경로상 추가 증빙이 요구됩니다: {', '.join(missing_requirements)}"
                    if reason not in review_reasons:
                        review_reasons.append(reason)
            for action in path.review_actions:
                _append_unique(structured_review_actions, action)
                reason = f"권장 검토 조치: {action}"
                if reason not in review_reasons:
                    review_reasons.append(reason)

            for item in getattr(path, "exclusion_reasons", []) or []:
                _append_unique(exclusion_reasons, item)
            for item in getattr(path, "benefit_limits", []) or []:
                _append_unique(benefit_limits, item)
            for item in getattr(path, "deductible_rules", []) or []:
                _append_unique(deductible_rules, item)
            for item in getattr(path, "required_documents", []) or []:
                _append_unique(required_documents, item)
                if not _is_evidence_requirement_satisfied(item, context.evidence_tags or []):
                    _append_unique(missing_evidence, item)
                    review_required = True
            for item in getattr(path, "coordination_rules", []) or []:
                if not coordination_requested:
                    continue
                _append_unique(coordination_rules, item)
                review_required = True
                reason = f"중복 보상 조정 검토가 필요합니다: {item}"
                if reason not in review_reasons:
                    review_reasons.append(reason)
            for item in getattr(path, "generation_rules", []) or []:
                _append_unique(generation_rules, item)

            has_confirmed_exclusion = any(_is_confirmed_exclusion_step(step) for step in path.steps)
            if has_confirmed_exclusion:
                confirmed_exclusion_path_found = True
                payable_val = Decimal("0")
                deductible_val = total_claimed
                payable_str = "0"
                deductible_str = f"{total_claimed:,.0f}".replace(",", "")
                review_required = True
                reason = "문서 기반 검토 경로에서 면책 판단 조항이 직접 연결되어 지급예상액을 0원으로 보수 처리했습니다."
                if reason not in review_reasons:
                    review_reasons.append(reason)

        # candidate PAYS_BY_RATIO 만 있고 confirmed 정보가 없는 경우 검토 강제
        has_candidate_ratio = any(f.status == "candidate" and f.relation == "PAYS_BY_RATIO" for f in graph_result.facts)
        has_confirmed = any(f.status == "confirmed" for f in graph_result.facts)
        if has_candidate_ratio and not has_confirmed:
            review_required = True
            reason = "신뢰할 수 있는 확정 구조화 사실(confirmed)이 없으며, 후보 지급 비율(candidate PAYS_BY_RATIO)만 존재합니다. 지급예상액을 확정할 수 없습니다."
            if reason not in review_reasons:
                review_reasons.append(reason)

        has_graph_candidate = any(f.status == "candidate" for f in graph_result.facts)
        if has_graph_candidate:
            review_required = True
            for f in graph_result.facts:
                if f.status == "candidate":
                    reason = f"약관 규정({f.subject})과의 관계({f.relation})가 확정되지 않은 검토 후보 상태입니다. (매칭 정보: {f.object})"
                    if reason not in review_reasons:
                        review_reasons.append(reason)

    # 각 단계별 검토 플래그 병합
    if disambiguation_required:
        review_required = True
        review_reasons.extend(db_review_reasons)
    elif db_review_required:
        review_required = True
        review_reasons.extend(db_review_reasons)

    if sandbox_error_occurred:
        review_required = True
        review_reasons.append(sandbox_error_msg)

    if plan.decision == "needs_more_info":
        review_required = True
        review_reasons.append("상황 정보가 부족하여 계산을 일시 보류합니다. 추가 확인이 필요합니다.")
        for unc in plan.uncertainties:
            if unc not in review_reasons:
                review_reasons.append(unc)
    elif plan.decision == "not_covered":
        review_required = True
        review_reasons.append("해당 건은 보상 대상(면책)에 포함되지 않습니다.")
        for unc in plan.uncertainties:
            if unc not in review_reasons:
                review_reasons.append(unc)

    # applied_basis에 RAG 검색 출처 정보와 DB 매치 정보를 구성
    applied_basis = []
    # DB 매치 근거 추가
    for idx, match in enumerate(standard_matches):
        if match.std_cd:
            table_basis = _match_basis_summary(match)
            extra = f" | {table_basis}" if table_basis else ""
            basis = {
                "source": f"비급여 표준모델 (코드: {match.std_cd})",
                "content": f"표준명: {match.std_cd_nm} | 분류: {repr(match.mid_category_cd_nm)} | 보상의견: {match.pay_opn_cd_nm or '없음'}{extra}"
            }
            line_result = deterministic_line_results[idx] if idx < len(deterministic_line_results) else {}
            if getattr(match, "requires_review", False) or line_result.get("requires_review") or line_result.get("calculation_status") in {"human_task", "partial_human_task"} or line_result.get("excluded_from_calculation"):
                basis["review_status"] = "review_required"
            applied_basis.append(basis)
    # RAG 문서 근거 추가
    for ev in retrieved_evidences:
        if not ev.get("display_in_applied_basis", True):
            continue
        applied_basis.append({
            "source": f"{ev['source']} p.{ev['page']}",
            "content": ev["content"][:200] + ("..." if len(ev["content"]) > 200 else "")
        })

    # applied_limits 구성
    _gen = _normalize_policy_generation(context.policy_generation)
    _applied_limits: dict[str, str] = {"policy_generation": _gen}
    try:
        from src.claim_calculation.deductible_rules import lookup_rule as _lr
        _sample_rule = _lr(_gen, "급여", context.visit_type or "outpatient", context.facility_grade)
        if _sample_rule.per_visit_limit:
            _applied_limits["per_visit_limit"] = str(_sample_rule.per_visit_limit)
        if _sample_rule.annual_limit:
            _applied_limits["annual_limit"] = str(_sample_rule.annual_limit)
        if _sample_rule.annual_visit_limit:
            _applied_limits["annual_visit_limit"] = str(_sample_rule.annual_visit_limit)
        _applied_limits["remaining_note"] = "단건 기준 (과거 청구 이력 미반영)"
    except Exception:
        pass

    calculation_status = "auto_calculated"
    if confirmed_exclusion_path_found or plan.decision == "not_covered":
        calculation_status = "not_covered"
    elif disambiguation_required or plan.decision == "needs_more_info":
        calculation_status = "blocked_missing_info"
    elif review_required:
        calculation_status = "estimated_review_required"

    notes_by_status = {
        "auto_calculated": "지급예상액 계산이 성공적으로 완료되었습니다.",
        "estimated_review_required": "추가 심사 검토가 필요합니다.",
        "blocked_missing_info": "필수 정보 또는 표준코드 선택이 부족하여 자동 계산을 보류했습니다.",
        "not_covered": "면책/보상제외 판단 근거가 확인되어 지급예상액을 0원으로 보수 처리했습니다.",
    }

    return CalculationResult(
        claimed_amount=str(total_claimed),
        payable_amount=payable_str,
        deductible=deductible_str,
        formula_intent=sandbox_code,
        executed_code=sandbox_code,
        applied_basis=applied_basis,
        requires_review=review_required,
        review_reasons=review_reasons,
        notes=notes_by_status[calculation_status],
        candidates=disambiguation_candidates,
        policy_generation=_normalize_policy_generation(context.policy_generation),
        special_calculation_status=_special_status(context),
        line_results=deterministic_line_results,
        applied_limits=_applied_limits,
        calculation_status=calculation_status,
        missing_evidence=missing_evidence,
        review_actions=structured_review_actions,
        exclusion_reasons=exclusion_reasons,
        benefit_limits=benefit_limits,
        deductible_rules=deductible_rules,
        required_documents=required_documents,
        coordination_rules=coordination_rules,
        generation_rules=generation_rules,
        graph_review_paths=graph_review_paths_payload,
        session_assertions=session_assertions_payload,
    )
