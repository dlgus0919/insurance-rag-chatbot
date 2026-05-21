"""자동 문서 선택 (Basis Selector) 모듈."""

from __future__ import annotations

from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext, BasisSelection


def select_basis_documents(
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    basis_mode: str = "auto",
    selected_docs: list[str] | None = None
) -> BasisSelection:
    """계산에 필요한 근거 문서들을 자동 또는 사용자 선택에 따라 구성한다.

    basis_mode가 "auto"인 경우:
      1. 비급여 표준모델: 항상 포함
      2. context와 item 텍스트 내 키워드를 분석하여 약관, 자사_SOL건강, 자사_SOL운전자, 실무가이드, 상담사례집, 심평원 문서를 동적으로 추가한다.
    basis_mode가 "manual"인 경우:
      selected_docs 리스트를 그대로 사용하되, 비급여 표준모델을 항상 포함한다.
    """
    if basis_mode != "auto":
        docs = list(selected_docs) if selected_docs is not None else []
        if "비급여 표준모델" not in docs:
            docs.append("비급여 표준모델")
        return BasisSelection(
            doc_filter=docs,
            selection_reason="사용자 지정 근거 문서 선택"
        )

    # auto 모드 분석
    docs = ["비급여 표준모델"]
    reasons = ["비급여 표준모델 (기본 적용)"]

    # 분석 대상 텍스트 결합 (소문자화 및 공백 제거로 매칭 효율성 향상)
    texts_to_analyze = []
    if context.situation_note:
        texts_to_analyze.append(context.situation_note)
    if context.coverage_topic:
        texts_to_analyze.append(context.coverage_topic)
    if context.diagnosis_name:
        texts_to_analyze.append(context.diagnosis_name)
    for item in items:
        texts_to_analyze.append(item.input_name)
        if item.user_category_hint:
            texts_to_analyze.append(item.user_category_hint)

    combined_text = " ".join(texts_to_analyze).lower()

    # 1. 약관 (실손보험 관련 키워드)
    ins_keywords = ["실손", "비급여", "급여", "의료비", "약관", "도수", "주사", "자기부담", "통원", "입원"]
    if any(k in combined_text for k in ins_keywords) or context.visit_type:
        docs.append("약관")
        reasons.append("약관 (실손/의료비 관련 키워드 감지)")

    # 2. 자사 SOL건강 약관
    sol_health_keywords = ["신한", "sol건강", "처음건강", "건강보험"]
    if any(k in combined_text for k in sol_health_keywords):
        docs.append("자사_SOL건강")
        reasons.append("자사_SOL건강 (자사 건강보험 관련 키워드 감지)")

    # 3. 자사 SOL운전자 약관
    sol_drive_keywords = ["운전자", "교통", "자동차", "운전", "사고"]
    if any(k in combined_text for k in sol_drive_keywords) or context.accident_type == "accident":
        docs.append("자사_SOL운전자")
        reasons.append("자사_SOL운전자 (운전자/사고 관련 키워드 감지)")

    # 4. 실무가이드 (수술종수, 장해율 등)
    guide_keywords = ["수술", "장해", "장애", "가이드", "실무", "종수", "지급기준", "도수치료 제한"]
    if any(k in combined_text for k in guide_keywords):
        docs.append("실무가이드")
        reasons.append("실무가이드 (수술/장해/지급한도 관련 키워드 감지)")

    # 5. 상담사례집 (분쟁, 사례)
    case_keywords = ["사례", "상담", "분쟁", "민원", "판례", "소비자"]
    if any(k in combined_text for k in case_keywords):
        docs.append("상담사례집")
        reasons.append("상담사례집 (사례/분쟁/민원 관련 키워드 감지)")

    # 6. 심평원 (수가코드 등)
    hira_keywords = ["수가", "행위", "점수", "심평원", "hira", "코드"]
    if any(k in combined_text for k in hira_keywords):
        docs.append("심평원")
        reasons.append("심평원 (비급여 수가/점수/심평원 관련 키워드 감지)")

    return BasisSelection(
        doc_filter=docs,
        selection_reason=", ".join(reasons)
    )
