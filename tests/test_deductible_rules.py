"""deductible_rules 모듈 단위 테스트."""

import json

from decimal import Decimal

import pytest

from src.claim_calculation import deductible_rules
from src.claim_calculation.deductible_rules import (
    DeductibleRule,
    PrescriptionRule,
    lookup_rule,
    lookup_prescription_rule,
    FACILITY_CLINIC,
    FACILITY_HOSPITAL,
    FACILITY_GENERAL,
    FACILITY_TERTIARY,
)


class TestLookupRule:
    """lookup_rule 함수 테스트."""

    # --- 4세대 ---

    def test_4th_benefit_hospitalization(self):
        rule = lookup_rule("4th", "급여", "hospitalization")
        assert rule.copay_ratio == Decimal("0.2")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("0")
        assert rule.annual_limit == Decimal("50000000")

    def test_4th_benefit_outpatient_clinic(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.2")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("10000")

    def test_4th_benefit_outpatient_hospital(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.get_min_deductible(FACILITY_HOSPITAL) == Decimal("15000")

    def test_4th_benefit_outpatient_general(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.get_min_deductible(FACILITY_GENERAL) == Decimal("20000")

    def test_4th_benefit_outpatient_tertiary(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.get_min_deductible(FACILITY_TERTIARY) == Decimal("20000")

    def test_4th_nonbenefit_outpatient(self):
        rule = lookup_rule("4th", "비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.3")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("30000")
        assert rule.per_visit_limit == Decimal("250000")

    def test_4th_manual_therapy_does_not_fallback_to_general_nonpay_rule(self, tmp_path, monkeypatch):
        """4세대 도수치료군은 승인된 전용 rule 없이는 generic fallback을 쓰지 않는다."""
        manifest = tmp_path / "claim_deductible_rules.active.json"
        payload = json.loads(deductible_rules.CLAIM_RULES_PATH.read_text(encoding="utf-8"))
        payload["rules"] = [
            row
            for row in payload["rules"]
            if row.get("rule_id") != "deductible.4th.three_major_manual.outpatient"
        ]
        manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(deductible_rules, "CLAIM_RULES_PATH", manifest)
        deductible_rules._load_registry.cache_clear()
        try:
            with pytest.raises(KeyError):
                lookup_rule("4th", "3대비급여_도수", "outpatient")
        finally:
            deductible_rules._load_registry.cache_clear()

    def test_4th_manual_therapy_uses_exact_approved_rule(self, tmp_path, monkeypatch):
        manifest = tmp_path / "claim_deductible_rules.active.json"
        manifest.write_text(
            '''{
              "version": 1,
              "rules": [{
                "rule_id": "deductible.4th.three_major_manual.outpatient",
                "generation": "4th",
                "category": "3대비급여_도수",
                "visit_type": "outpatient",
                "facility_grade": "all",
                "copay_ratio": "0.3",
                "min_deductible": "30000",
                "min_deductible_by_facility": {
                  "clinic": "30000", "hospital": "30000",
                  "general_hospital": "30000", "tertiary_hospital": "30000"
                },
                "per_visit_limit": null,
                "annual_limit": "3500000",
                "annual_visit_limit": 50,
                "review_requirements": ["최초 10회 이후 증상 호전 증빙 확인 필요"],
                "description": "4세대 도수치료군 승인 테스트 rule",
                "source_doc": "약관",
                "source_page": "71-78",
                "source_clause": "제3조",
                "source_chunk_id": "약관_ch_002441",
                "approval_status": "active",
                "source_status": "source_grounded"
              }],
              "prescription_rules": [],
              "special_rules": []
            }''',
            encoding="utf-8",
        )
        monkeypatch.setattr(deductible_rules, "CLAIM_RULES_PATH", manifest)
        deductible_rules._load_registry.cache_clear()
        try:
            rule = lookup_rule("4th", "3대비급여_도수", "outpatient")
        finally:
            deductible_rules._load_registry.cache_clear()

        assert rule.copay_ratio == Decimal("0.3")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("30000")
        assert rule.per_visit_limit is None
        assert rule.annual_limit == Decimal("3500000")
        assert rule.annual_visit_limit == 50
        assert rule.review_requirements == ("최초 10회 이후 증상 호전 증빙 확인 필요",)
        assert rule.source_chunk_id == "약관_ch_002441"

    def test_4th_serious_alias(self):
        """4세대 중증비급여는 비급여와 동일 규칙."""
        rule = lookup_rule("4th", "중증비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.3")

    def test_4th_nonserious_alias(self):
        """4세대 비중증비급여는 비급여와 동일 규칙."""
        rule = lookup_rule("4th", "비중증비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.3")

    def test_4th_per_visit_limit(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.per_visit_limit == Decimal("250000")
        assert rule.annual_visit_limit == 180

    # --- 5세대 ---

    def test_5th_benefit_outpatient_clinic(self):
        rule = lookup_rule("5th", "급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.2")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("10000")
        assert rule.per_visit_limit == Decimal("200000")

    def test_5th_benefit_outpatient_hospital(self):
        rule = lookup_rule("5th", "급여", "outpatient")
        assert rule.get_min_deductible(FACILITY_HOSPITAL) == Decimal("15000")

    def test_5th_serious_outpatient(self):
        rule = lookup_rule("5th", "중증비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.3")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("30000")

    def test_5th_nonserious_outpatient(self):
        rule = lookup_rule("5th", "비중증비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.5")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("50000")

    def test_5th_3major_outpatient(self):
        rule = lookup_rule("5th", "3대비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.5")
        assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("50000")

    def test_5th_nonbenefit_unclassified(self):
        """5세대 비급여(미분류)는 비중증 기준 50%."""
        rule = lookup_rule("5th", "비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.5")

    def test_5th_hospitalization_no_min_deductible(self):
        """입원은 의료기관 등급별 최소공제 없음."""
        rule = lookup_rule("5th", "중증비급여", "hospitalization")
        assert rule.get_min_deductible(FACILITY_TERTIARY) == Decimal("0")

    # --- Fallback ---

    def test_unknown_category_fallback(self):
        """미분류 카테고리 → 해당 세대의 급여 규칙으로 fallback."""
        rule = lookup_rule("4th", "미분류", "outpatient")
        assert rule.copay_ratio == Decimal("0.2")

    def test_unknown_generation_fallback(self):
        """미지원 세대 → 최신 지원 세대로 fallback."""
        rule = lookup_rule("3rd", "급여", "outpatient")
        assert rule.generation == "5th"

    def test_empty_visit_type_defaults_outpatient(self):
        rule = lookup_rule("4th", "급여", "")
        assert rule.visit_type == "outpatient"

    def test_empty_facility_defaults_clinic(self):
        rule = lookup_rule("4th", "급여", "outpatient")
        assert rule.get_min_deductible("") == Decimal("10000")  # clinic default


class TestLookupPrescriptionRule:
    """처방약 규칙 테스트."""

    def test_4th_prescription(self):
        rule = lookup_prescription_rule("4th")
        assert rule.deductible_amount == Decimal("8000")
        assert rule.per_visit_limit == Decimal("50000")

    def test_5th_prescription(self):
        rule = lookup_prescription_rule("5th")
        assert rule.deductible_amount == Decimal("8000")
        assert rule.per_visit_limit == Decimal("50000")

    def test_unknown_gen_prescription(self):
        rule = lookup_prescription_rule("3rd")
        assert rule.generation == "5th"
