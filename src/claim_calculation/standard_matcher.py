"""비급여 표준모델 데이터베이스 매칭 모듈."""

from __future__ import annotations

from typing import Any, Literal
import re
from src.claim_calculation.models import StandardMatch
from src.claim_calculation.processing_policy import standard_match_constraint_for_query
from src.db import standard_codes


CareScope = Literal["benefit", "nonpay", "mixed", "unknown"]


def match_standard_code(
    input_name: str,
    input_code: str = "",
    *,
    care_scope: CareScope = "unknown",
    limit: int = 6,
) -> list[StandardMatch]:
    """청구 항목명 및 표준코드를 기반으로 비급여 표준모델을 매칭한다.

    1. input_code가 주어진 경우 exact match를 우선 시도한다.
    2. exact match가 실패하거나 input_code가 없는 경우 input_name으로 fuzzy search를 수행한다.
    3. 비급여 금액만 입력된 경우에는 급여/면책 전용 행을 후보에서 제외한다.
    4. 검색 결과가 2개 이상인 경우 모든 결과의 requires_user_disambiguation을 True로 설정한다.
    5. pay_opn_cd_nm이 "추가확인", "면책"이거나 비어있으면 requires_review를 True로 설정한다.
    """
    input_code = input_code.strip()
    input_name = input_name.strip()

    # 1. 코드 기반 exact match 시도
    if input_code:
        row = standard_codes.lookup_by_std_cd(input_code)
        if row:
            match = _row_to_standard_match(row, match_confidence="exact")
            return [match]

    # 2. 이름 기반 fuzzy search 시도
    if not input_name:
        return []

    rows = standard_codes.search_by_name(input_name)
    if not rows:
        return []

    rows = _filter_rows_for_query(input_name, rows, care_scope)
    if not rows:
        return []

    bounded_limit = max(1, min(int(limit or 6), 6))

    matches = []
    # 2개 이상인 경우 모호성 표시 활성화
    requires_disambiguation = len(rows) > 1

    for row in rows:
        confidence = "high" if len(rows) == 1 else "low"
        match = _row_to_standard_match(row, match_confidence=confidence)
        if requires_disambiguation:
            match.requires_user_disambiguation = True
        matches.append(match)

    # 정렬: 면책이나 추가확인(requires_review=True)인 항목은 뒤로 밀려나도록 정렬
    matches.sort(key=lambda x: (x.requires_review, x.std_cd_nm))
    return matches[:bounded_limit]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _row_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "std_cd",
            "std_cd_nm",
            "mid_category_cd_nm",
            "hira_care_type_cd_nm",
            "ins_care_type_cd_nm",
            "medical_class_cd_nm",
            "item_class_level1cd_nm",
            "item_class_level2cd_nm",
            "pay_opn_cd_nm",
        )
    )


def _filter_rows_for_query(
    input_name: str,
    rows: list[dict[str, Any]],
    care_scope: CareScope,
) -> list[dict[str, Any]]:
    """Reduce known broad-name false positives before disambiguation.

    Short words such as MRI/MRA often match unrelated treatment materials. Keep
    rows tied to imaging fee categories when the user asks for MRI/MRA, while
    preserving all original rows for ordinary fuzzy queries.
    """

    constraint = standard_match_constraint_for_query(input_name)
    if constraint:
        constrained_rows = [
            row for row in rows
            if any(
                keyword in _row_text(row)
                for keyword in constraint.row_required_any
            )
        ]
        if constrained_rows:
            rows = constrained_rows

    if care_scope == "nonpay":
        return [row for row in rows if _is_nonpay_row(row) and not _is_nonpay_restriction(row)]
    return rows


def _is_nonpay_row(row: dict[str, Any]) -> bool:
    return "비급여" in _normalize_text(_row_text(row))


def _is_nonpay_restriction(row: dict[str, Any]) -> bool:
    text = _normalize_text(_row_text(row))
    return (
        "면책" in text
        or "보상제외" in text
        or ("급여외" in text and "산정불가" in text)
        or ("비급여" in text and "산정불가" in text)
    )


def _row_to_standard_match(row: dict[str, Any], match_confidence: str) -> StandardMatch:
    """DB row 딕셔너리를 StandardMatch 객체로 변환한다."""
    pay_opn = row.get("pay_opn_cd_nm") or ""
    pay_opn_clean = pay_opn.strip()

    # pay_opn_cd_nm이 "추가확인", "면책"이거나 비어있는 경우
    requires_review = (pay_opn_clean == "추가확인") or ("면책" in pay_opn_clean) or (not pay_opn_clean)

    return StandardMatch(
        std_cd=row.get("std_cd") or "",
        std_cd_nm=row.get("std_cd_nm") or "",
        mid_category_cd_nm=row.get("mid_category_cd_nm") or "",
        hira_care_type_cd_nm=row.get("hira_care_type_cd_nm") or "",
        ins_care_type_cd_nm=row.get("ins_care_type_cd_nm") or "",
        medical_class_cd_nm=row.get("medical_class_cd_nm") or "",
        item_class_level1cd_nm=row.get("item_class_level1cd_nm") or "",
        item_class_level2cd_nm=row.get("item_class_level2cd_nm") or "",
        pay_opn_cd_nm=pay_opn,
        notes=row.get("notes") or "",
        match_confidence=match_confidence,
        requires_user_disambiguation=False,
        requires_review=requires_review,
    )
