"""초기 로직 결점 5종에 대한 복합 Final 테스트."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from src.claim_calculation.code_sandbox import execute_calculation
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation
from src.rag.pipeline import _build_hira_fee_context, _deterministic_guard_answer
from src.retrieval.vector_store import VectorStore


def test_final_round_2_exclusion_code_hard_stops_before_llm() -> None:
    """면책 표준코드는 지급 0원으로 즉시 종료되어야 한다."""

    items = [
        ClaimItemInput(
            line_id="line_exclusion",
            input_name="도수치료",
            input_code="51040",
            claimed_amount="100000",
            quantity="1",
            user_category_hint="급여",
        )
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")
    match = {
        "std_cd": "51040",
        "std_cd_nm": "도수치료",
        "mid_category_cd_nm": "공상",
        "ins_care_type_cd_nm": "급여",
        "pay_opn_cd_nm": "면책",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=match):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "0"
    assert result.deductible == "100000"
    assert result.requires_review
    assert "면책" in result.line_results[0]["rule_summary"]


def test_final_round_2_decimal_import_is_normalized_and_executes() -> None:
    """LLM이 붙인 Decimal import는 제거 후 정상 실행되어야 한다."""

    result = execute_calculation(
        "from decimal import Decimal\n"
        "claimed_amount = Decimal('100000')\n"
        "deductible = Decimal('50000')\n"
        "payable_amount = claimed_amount - deductible\n"
    )

    assert "from decimal import Decimal" not in result["code"]
    assert str(result["variables"]["payable_amount"]) == "50000"


def test_final_round_2_fifth_generation_mri_uses_deterministic_cap() -> None:
    """5세대 MRI 통원 50만원은 50% 공제 후 건당 20만원 한도를 적용한다."""

    items = [
        ClaimItemInput(
            line_id="line_mri",
            input_name="MRI",
            input_code="HE115",
            claimed_amount="500000",
            quantity="1",
            user_category_hint="비중증비급여",
        )
    ]
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="outpatient",
        facility_grade="general_hospital",
        coverage_topic="MRI",
    )
    match = {
        "std_cd": "HE115",
        "std_cd_nm": "자기공명영상진단-복부",
        "mid_category_cd_nm": "방사선특수영상진단료",
        "ins_care_type_cd_nm": "비급여_특약3",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.lookup_by_std_cd", return_value=match):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "200000"
    assert result.deductible == "300000"
    assert result.requires_review
    assert "건당 20만원" in result.line_results[0]["rule_summary"]


def test_final_round_2_hira_row_lookup_restores_pancreas_codes(monkeypatch) -> None:
    """췌이식술 질의는 HIRA row fallback으로 Q8061/Q8062를 복원해야 한다."""

    monkeypatch.setattr(
        "src.rag.pipeline._HIRA_CHUNK_CACHE",
        [
            {
                "text": "췌이식술\nQ8061 췌이식술-부분\nQ8062 췌이식술-췌장 및 십이지장",
                "metadata": {"doc_short": "심평원", "page_start": 638, "source_file": "BZ202603053039374.pdf"},
            }
        ],
    )

    context = _build_hira_fee_context(
        "췌이식술의 수가코드와 점수를 알려줘",
        graph_context="췌장 이식수술 --HAS_GRADE--> 신1-5종 5종",
    )
    answer = _deterministic_guard_answer("췌장 이식수술의 수가코드와 점수를 알려줘", [], graph_context="췌장 이식수술")

    assert context is not None
    assert "Q8061" in context
    assert "Q8062" in context
    assert answer is not None
    assert "Q8061" in answer
    assert "Q8062" in answer


def test_final_round_2_graph_evidence_survives_id_mismatch(tmp_path) -> None:
    """GraphDB evidence chunk id가 달라도 id/doc-page fallback으로 근거를 복구해야 한다."""

    store = VectorStore(tmp_path / "chroma")
    store.upsert(
        ids=["자사_SOL건강_ch_011755", "sol_384"],
        embeddings=np.asarray([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32),
        metadatas=[
            {"doc_short": "자사_SOL건강", "page_start": 384, "page_end": 384},
            {"doc_short": "자사_SOL건강", "page_start": 384, "page_end": 389},
        ],
        documents=["SOL 건강보험 별표7 수술분류표 근거", "별표7 수술분류표 페이지 범위"],
    )

    hits_by_id = store.get_by_ids(["자사_SOL건강_v2_manual_ch_011755"])
    hits_by_page = store.get_by_doc_page("자사_SOL건강", 384, 384)

    assert len(hits_by_id) == 1
    assert hits_by_id[0].document == "SOL 건강보험 별표7 수술분류표 근거"
    assert len(hits_by_page) == 2
    assert {hit.id for hit in hits_by_page} == {"자사_SOL건강_ch_011755", "sol_384"}
