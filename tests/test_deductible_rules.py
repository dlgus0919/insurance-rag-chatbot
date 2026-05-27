"""deductible_rules 모듈 단위 테스트."""

from decimal import Decimal

import pytest

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

    def test_4th_3major_alias(self):
        """4세대 3대비급여는 비급여와 동일 규칙."""
        rule = lookup_rule("4th", "3대비급여", "outpatient")
        assert rule.copay_ratio == Decimal("0.3")

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
        """미지원 세대 → 4세대로 fallback."""
        rule = lookup_rule("3rd", "급여", "outpatient")
        assert rule.generation == "4th"

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
        assert rule.generation == "4th"
