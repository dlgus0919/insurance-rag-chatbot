"""비급여 표준모델 데이터베이스 매칭 모듈."""

from __future__ import annotations

from typing import Any
from src.claim_calculation.models import StandardMatch
from src.db import standard_codes


def match_standard_code(input_name: str, input_code: str = "") -> list[StandardMatch]:
    """청구 항목명 및 표준코드를 기반으로 비급여 표준모델을 매칭한다.

    1. input_code가 주어진 경우 exact match를 우선 시도한다.
    2. exact match가 실패하거나 input_code가 없는 경우 input_name으로 fuzzy search를 수행한다.
    3. 검색 결과가 2개 이상인 경우 모든 결과의 requires_user_disambiguation을 True로 설정한다.
    4. pay_opn_cd_nm이 "추가확인"이거나 비어있으면 requires_review를 True로 설정한다.
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

    matches = []
    # 2개 이상인 경우 모호성 표시 활성화
    requires_disambiguation = len(rows) > 1

    for row in rows:
        confidence = "high" if len(rows) == 1 else "low"
        match = _row_to_standard_match(row, match_confidence=confidence)
        if requires_disambiguation:
            match.requires_user_disambiguation = True
        matches.append(match)

    return matches


def _row_to_standard_match(row: dict[str, Any], match_confidence: str) -> StandardMatch:
    """DB row 딕셔너리를 StandardMatch 객체로 변환한다."""
    pay_opn = row.get("pay_opn_cd_nm") or ""
    pay_opn_clean = pay_opn.strip()

    # pay_opn_cd_nm이 "추가확인"이거나 비어있는 경우
    requires_review = (pay_opn_clean == "추가확인") or (not pay_opn_clean)

    return StandardMatch(
        std_cd=row.get("std_cd") or "",
        std_cd_nm=row.get("std_cd_nm") or "",
        mid_category_cd_nm=row.get("mid_category_cd_nm") or "",
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
