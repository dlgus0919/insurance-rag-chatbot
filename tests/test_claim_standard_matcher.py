"""비급여 표준모델 데이터베이스 매칭 테스트."""

from __future__ import annotations

from unittest.mock import patch
import pytest

from src.claim_calculation.models import StandardMatch
from src.claim_calculation.standard_matcher import match_standard_code


def test_match_standard_code_exact():
    """표준코드가 주어졌을 때 exact match를 우선 시도하여 단건을 반환하는지 테스트한다."""
    mock_row = {
        "std_cd": "SC0001",
        "std_cd_nm": "도수치료(SC0001)",
        "mid_category_cd_nm": "물리치료",
        "ins_care_type_cd_nm": "기본",
        "medical_class_cd_nm": "의원",
        "item_class_level1cd_nm": "외래",
        "item_class_level2cd_nm": "도수치료",
        "pay_opn_cd_nm": "보상",
        "notes": "특이사항 없음",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=mock_row) as mock_lookup:
        results = match_standard_code(input_name="도수치료", input_code="SC0001")

        mock_lookup.assert_called_once_with("SC0001")
        assert len(results) == 1
        match = results[0]
        assert isinstance(match, StandardMatch)
        assert match.std_cd == "SC0001"
        assert match.match_confidence == "exact"
        assert not match.requires_user_disambiguation
        assert not match.requires_review


def test_match_standard_code_fuzzy_single():
    """이름 기반 fuzzy search에서 단 하나의 결과만 반환되었을 때 high confidence로 매칭하는지 테스트한다."""
    mock_rows = [
        {
            "std_cd": "SC0002",
            "std_cd_nm": "체외충격파치료(SC0002)",
            "mid_category_cd_nm": "물리치료",
            "pay_opn_cd_nm": "보상",
        }
    ]

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=None), \
         patch("src.db.standard_codes.search_by_name", return_value=mock_rows) as mock_search:
        results = match_standard_code(input_name="체외충격파")

        mock_search.assert_called_once_with("체외충격파")
        assert len(results) == 1
        match = results[0]
        assert match.std_cd == "SC0002"
        assert match.match_confidence == "high"
        assert not match.requires_user_disambiguation


def test_match_standard_code_disambiguation():
    """검색 결과가 2개 이상일 때 disambiguation 플래그가 True가 되는지 테스트한다."""
    mock_rows = [
        {
            "std_cd": "SC0001",
            "std_cd_nm": "도수치료 일반",
            "pay_opn_cd_nm": "보상",
        },
        {
            "std_cd": "SC0002",
            "std_cd_nm": "도수치료 특수",
            "pay_opn_cd_nm": "보상",
        }
    ]

    with patch("src.db.standard_codes.search_by_name", return_value=mock_rows):
        results = match_standard_code(input_name="도수치료")

        assert len(results) == 2
        for match in results:
            assert match.requires_user_disambiguation
            assert match.match_confidence == "low"


def test_match_standard_code_requires_review():
    """pay_opn_cd_nm이 '추가확인'이거나 비어있을 때 requires_review가 True가 되는지 테스트한다."""
    mock_row_review = {
        "std_cd": "SC0003",
        "std_cd_nm": "미용 보톡스",
        "pay_opn_cd_nm": "추가확인",
    }
    mock_row_empty = {
        "std_cd": "SC0004",
        "std_cd_nm": "알려지지 않은 시술",
        "pay_opn_cd_nm": "",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", side_effect=[mock_row_review, mock_row_empty]):
        # 첫 번째 호출: 추가확인
        res1 = match_standard_code(input_name="보톡스", input_code="SC0003")
        assert res1[0].requires_review

        # 두 번째 호출: 보상의견 공란
        res2 = match_standard_code(input_name="시술", input_code="SC0004")
        assert res2[0].requires_review
