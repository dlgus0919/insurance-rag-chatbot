from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "stage2_direct_model_eval.py"
    spec = importlib.util.spec_from_file_location("stage2_direct_model_eval", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage2_direct_eval_derives_mri_expected_from_rule_table() -> None:
    module = _load_module()
    case = next(case for case in module.CLAIM_CASES if case["id"] == "claim_mri_he115_5th")

    expected = module._derive_expected_claim(case)

    assert expected["payable_amount"] == "200000"
    assert expected["deductible"] == "300000"


def test_stage2_direct_eval_normalizes_korean_money_variants() -> None:
    module = _load_module()

    assert module.contains_variant("연간 한도는 3,500,000원입니다.", ["350만원"])
    assert module.contains_variant("공제금액은 60,000원입니다.", ["6만원"])
