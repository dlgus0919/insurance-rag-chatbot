"""자동 문서 선택(Basis Selector) 테스트."""

from __future__ import annotations

from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext
from src.claim_calculation.basis_selector import select_basis_documents


def test_select_basis_documents_auto_default():
    """아무 키워드도 매칭되지 않을 때 비급여 표준모델만 기본 선택되는지 테스트한다."""
    items = [ClaimItemInput(line_id="1", input_name="아주 일반적인 시술")]
    context = ClaimCaseContext(situation_note="특이사항 없음")

    basis = select_basis_documents(items, context, basis_mode="auto")
    assert basis.doc_filter == ["비급여 표준모델"]


def test_select_basis_documents_auto_routing():
    """컨텍스트 키워드에 따라 적합한 문서 카테고리가 동적으로 선택되는지 테스트한다."""
    # 1. 실손의료비/도수 키워드로 약관 매칭
    items = [ClaimItemInput(line_id="1", input_name="도수치료 청구")]
    context = ClaimCaseContext(situation_note="실손보험 청구용")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "약관" in basis.doc_filter

    # 2. 수술 키워드로 실무가이드 매칭
    items = [ClaimItemInput(line_id="2", input_name="충수절제 수술")]
    context = ClaimCaseContext(situation_note="")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "실무가이드" in basis.doc_filter

    # 3. 신한/SOL건강 키워드로 자사_SOL건강 매칭
    items = [ClaimItemInput(line_id="3", input_name="처음건강 검진")]
    context = ClaimCaseContext(situation_note="신한 SOL 건강보험 관련")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "자사_SOL건강" in basis.doc_filter

    # 4. 운전자/교통사고 키워드로 자사_SOL운전자 매칭
    items = [ClaimItemInput(line_id="4", input_name="교통사고 골절")]
    context = ClaimCaseContext(situation_note="운전자 상해 특약")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "자사_SOL운전자" in basis.doc_filter

    # 5. 분쟁/민원 키워드로 상담사례집 매칭
    items = [ClaimItemInput(line_id="5", input_name="일반 도수")]
    context = ClaimCaseContext(situation_note="소비자원 분쟁 사례 확인 요망")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "상담사례집" in basis.doc_filter

    # 6. 수가/점수 키워드로 심평원 매칭
    items = [ClaimItemInput(line_id="6", input_name="상대가치점수 조회")]
    context = ClaimCaseContext(situation_note="심평원 고시 확인")
    basis = select_basis_documents(items, context, basis_mode="auto")
    assert "심평원" in basis.doc_filter


def test_select_basis_documents_manual():
    """manual 모드인 경우 사용자가 지정한 리스트가 그대로 사용되며 비급여 표준모델이 항상 강제 추가되는지 테스트한다."""
    items = [ClaimItemInput(line_id="1", input_name="도수치료")]
    context = ClaimCaseContext()

    basis = select_basis_documents(
        items, context, basis_mode="manual", selected_docs=["약관", "실무가이드"]
    )
    assert "약관" in basis.doc_filter
    assert "실무가이드" in basis.doc_filter
    assert "비급여 표준모델" in basis.doc_filter
