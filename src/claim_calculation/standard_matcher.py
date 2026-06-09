"""비급여 표준모델 데이터베이스 매칭 모듈."""

from __future__ import annotations

from typing import Any
import re
from src.claim_calculation.models import StandardMatch
from src.db import standard_codes


def match_standard_code(input_name: str, input_code: str = "") -> list[StandardMatch]:
    """청구 항목명 및 표준코드를 기반으로 비급여 표준모델을 매칭한다.

    1. input_code가 주어진 경우 exact match를 우선 시도한다.
    2. exact match가 실패하거나 input_code가 없는 경우 input_name으로 fuzzy search를 수행한다.
    3. 검색 결과가 2개 이상인 경우 모든 결과의 requires_user_disambiguation을 True로 설정한다.
    4. pay_opn_cd_nm이 "추가확인", "면책"이거나 비어있으면 requires_review를 True로 설정한다.
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

    rows = _filter_rows_for_query(input_name, rows)
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

    # 정렬: 면책이나 추가확인(requires_review=True)인 항목은 뒤로 밀려나도록 정렬
    matches.sort(key=lambda x: (x.requires_review, x.std_cd_nm))
    return matches


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


def _filter_rows_for_query(input_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce known broad-name false positives before disambiguation.

    Short words such as MRI/MRA often match unrelated treatment materials. Keep
    rows tied to imaging fee categories when the user asks for MRI/MRA, while
    preserving all original rows for ordinary fuzzy queries.
    """

    normalized = _normalize_text(input_name)
    if normalized in {"mri", "mra", "mri검사", "mra검사", "자기공명영상", "자기공명영상진단"}:
        imaging_rows = [
            row for row in rows
            if any(
                keyword in _row_text(row)
                for keyword in (
                    "자기공명영상진단",
                    "자기공명혈관조영술",
                    "방사선특수영상진단료",
                    "비급여_특약3",
                )
            )
        ]
        if imaging_rows:
            return imaging_rows
    return rows


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
