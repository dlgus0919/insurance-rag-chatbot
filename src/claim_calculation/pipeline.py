"""보험금 계산 파이프라인 통합 모듈."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from src.claim_calculation.models import (
    ClaimItemInput,
    ClaimCaseContext,
    StandardMatch,
    BasisSelection,
    CalculationPlan,
    CalculationResult,
)
from src.claim_calculation.standard_matcher import match_standard_code
from src.claim_calculation.basis_selector import select_basis_documents
from src.claim_calculation.code_sandbox import execute_calculation
from src.claim_calculation.planner import LLMPlanner, FakePlanner

logger = logging.getLogger(__name__)


def _normalize_policy_generation(value: str) -> str:
    normalized = (value or "4th").strip().lower()
    if normalized in {"5", "5th", "5세대", "fifth"}:
        return "5th"
    return "4th"


def _classify_claim_category(item: ClaimItemInput, match: StandardMatch | None) -> str:
    text = " ".join(
        [
            item.user_category_hint or "",
            item.input_name or "",
            match.ins_care_type_cd_nm if match else "",
            match.pay_opn_cd_nm if match else "",
            match.mid_category_cd_nm if match else "",
        ]
    )
    if "비중증" in text:
        return "비중증비급여"
    if "중증" in text:
        return "중증비급여"
    if "3대" in text or "도수" in text or "체외충격파" in text or "증식" in text or "주사" in text or "mri" in text.lower() or "mra" in text.lower():
        return "3대비급여"
    if "비급여" in text:
        return "비급여"
    if "급여" in text:
        return "급여"
    return "미분류"


def _is_exclusion_match(match: StandardMatch | None) -> bool:
    """Return whether the structured standard-code opinion marks the item as excluded."""

    if match is None:
        return False
    opinion = (match.pay_opn_cd_nm or "").strip()
    return "면책" in opinion or "보상제외" in opinion or opinion in {"제외", "미보상"}


def _line_deductible(
    amount: Decimal,
    category: str,
    generation: str,
    visit_type: str,
    facility_grade: str = "",
) -> tuple[Decimal, str, list[str]]:
    """deductible_rules 테이블 기반 공제금액 산출."""
    from src.claim_calculation.deductible_rules import lookup_rule

    review_reasons: list[str] = []
    rule_entry = lookup_rule(generation, category, visit_type, facility_grade)
    ratio = rule_entry.copay_ratio
    min_deductible = rule_entry.get_min_deductible(facility_grade)
    rule_desc = rule_entry.description

    # 5세대 비급여 미분류 경고
    if generation == "5th" and category == "비급여":
        review_reasons.append("5세대 비급여는 중증/비중증 구분에 따라 공제율이 달라질 수 있어 항목 분류 확인이 필요합니다.")
    elif generation == "5th" and category == "3대비급여":
        review_reasons.append("5세대의 도수치료 등 3대비급여는 비중증 비급여 또는 선택형 특약 여부에 따라 보장 여부와 공제율 확인이 필요합니다.")
    elif category == "미분류":
        if generation == "5th":
            review_reasons.append("항목의 급여/비급여/중증 여부가 불명확하여 세대별 정확 계산을 위해 영수증·세부내역서 확인이 필요합니다.")
        else:
            review_reasons.append("항목의 급여/비급여 구분이 불명확하여 영수증·세부내역서 확인이 필요합니다.")

    deductible = max(min_deductible, amount * ratio)
    if deductible > amount:
        deductible = amount
    return deductible, rule_desc, review_reasons


def _is_prescription(item: ClaimItemInput) -> bool:
    """항목이 처방약(약제비)인지 판단한다. 사용자 명시 우선, 키워드 자동 감지 보조."""
    if item.is_prescription:
        return True
    if item.user_category_hint == "처방약":
        return True
    name = (item.input_name or "").strip()
    keywords = ["처방약", "약제비", "조제료", "약국", "처방전", "약값"]
    return any(k in name for k in keywords)


def _prescription_deductible(
    amount: Decimal,
    generation: str,
    facility_grade: str = "",
) -> tuple[Decimal, str, list[str]]:
    """처방약(약제비) 전용 공제 계산."""
    from src.claim_calculation.deductible_rules import lookup_prescription_rule

    review_reasons: list[str] = []
    rx_rule = lookup_prescription_rule(generation)
    deductible = rx_rule.deductible_amount
    if deductible > amount:
        deductible = amount
    return deductible, rx_rule.description, review_reasons


def _is_health_insurance_unapplied(context: ClaimCaseContext) -> bool:
    text = " ".join([context.coverage_topic or "", context.situation_note or ""])
    return any(keyword in text for keyword in ["요양급여 미적용", "건강보험 미적용", "건강보험 적용받지 못", "급여 적용받지 못"])


def _is_upper_room_difference(item: ClaimItemInput) -> bool:
    text = " ".join([item.input_name or "", item.user_category_hint or ""])
    return "상급병실" in text or "병실료 차액" in text


def _calculate_line_items(
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    standard_matches: list[StandardMatch],
) -> tuple[Decimal, Decimal, list[dict[str, str | bool | list[str]]], list[str]]:
    from src.claim_calculation.models import parse_money, parse_quantity

    generation = _normalize_policy_generation(context.policy_generation)
    total_payable = Decimal("0")
    total_deductible = Decimal("0")
    line_results: list[dict[str, str | bool | list[str]]] = []
    review_reasons: list[str] = []

    for idx, item in enumerate(items):
        unit_amount = parse_money(item.claimed_amount)
        quantity = parse_quantity(item.quantity)
        amount = unit_amount * quantity
        match = standard_matches[idx] if idx < len(standard_matches) else None
        category = _classify_claim_category(item, match)
        line_review = False
        line_reasons: list[str] = []

        if _is_exclusion_match(match):
            deductible = amount
            payable = Decimal("0")
            opinion = match.pay_opn_cd_nm or "면책"
            code = f"코드 {match.std_cd} " if match and match.std_cd else ""
            rule = f"비급여 표준모델 {code}보상의견 '{opinion}'에 따른 지급예상액 0원"
            line_review = True
            line_reasons.append("비급여 표준모델 보상의견이 면책/보상제외로 표시되어 자동 계산 지급예상액을 0원으로 처리했습니다.")
            if match and match.requires_user_disambiguation:
                line_reasons.append("동일 항목명에 보상 후보가 함께 존재하므로 정확한 표준코드 입력 또는 증빙 확인이 필요합니다.")
        elif "제외" in item.input_name or "not_covered" in item.input_name:
            deductible = amount
            payable = Decimal("0")
            rule = "보상 제외 항목으로 입력되어 지급예상액 0원"
            line_review = True
            line_reasons.append("보상 대상 또는 면책 여부를 약관 및 치료 목적 서류로 재확인해야 합니다.")
        elif "정보부족" in item.input_name or "needs_more_info" in item.input_name:
            deductible = Decimal("0")
            payable = Decimal("0")
            rule = "계산 보류"
            line_review = True
            line_reasons.append("정보가 부족하여 진료비 영수증 또는 진료비 세부내역서의 항목 구분 확인이 필요합니다.")
        elif _is_prescription(item):
            from src.claim_calculation.deductible_rules import lookup_prescription_rule
            rx_rule = lookup_prescription_rule(generation)
            deductible = rx_rule.deductible_amount
            if deductible > amount:
                deductible = amount
            payable = amount - deductible
            # 처방약 건당 한도 적용
            if rx_rule.per_visit_limit and payable > rx_rule.per_visit_limit:
                excess = payable - rx_rule.per_visit_limit
                payable = rx_rule.per_visit_limit
                deductible = amount - payable
                line_reasons.append(f"처방약 건당 한도 {rx_rule.per_visit_limit:,.0f}원 초과분 {excess:,.0f}원은 자기부담입니다.")
            rule = rx_rule.description
            category = "처방약"
        elif _is_upper_room_difference(item):
            capped_daily_amount = min(unit_amount, Decimal("100000"))
            payable = capped_daily_amount * quantity * Decimal("0.5")
            deductible = amount - payable
            rule = "상급병실료 차액 특례: 1일 평균 10만원 한도 내 비급여 병실료의 50% 보상"
        else:
            deductible, rule, category_review = _line_deductible(amount, category, generation, context.visit_type, context.facility_grade)
            payable = amount - deductible
            line_reasons.extend(category_review)
            line_review = bool(category_review)

            # 건당 한도 적용
            from src.claim_calculation.deductible_rules import lookup_rule as _lookup_rule
            _rule_entry = _lookup_rule(generation, category, context.visit_type, context.facility_grade)
            if _rule_entry.per_visit_limit and payable > _rule_entry.per_visit_limit:
                excess = payable - _rule_entry.per_visit_limit
                payable = _rule_entry.per_visit_limit
                deductible = amount - payable
                line_reasons.append(f"건당 한도 {_rule_entry.per_visit_limit:,.0f}원 초과분 {excess:,.0f}원은 자기부담입니다.")
                line_review = True

            if _is_health_insurance_unapplied(context):
                base_after_deductible = max(Decimal("0"), amount - deductible)
                payable = base_after_deductible * Decimal("0.4")
                deductible = amount - payable
                rule = f"{rule}; 건강보험/의료급여 미적용 특례: 공제 후 금액의 40% 보상"
                line_review = True
                line_reasons.append("건강보험 또는 의료급여를 적용받지 못한 건은 약관상 40% 특례 계산 대상이므로 적용 사유 확인이 필요합니다.")

        total_payable += payable
        total_deductible += deductible
        review_reasons.extend(line_reasons)
        line_results.append(
            {
                "line_id": item.line_id,
                "input_name": item.input_name,
                "input_code": item.input_code,
                "category": category,
                "claimed_amount": f"{amount:,.0f}".replace(",", ""),
                "deductible": f"{deductible:,.0f}".replace(",", ""),
                "payable_amount": f"{payable:,.0f}".replace(",", ""),
                "policy_generation": generation,
                "rule_summary": rule,
                "requires_review": line_review,
                "review_reasons": line_reasons,
            }
        )

    return total_payable, total_deductible, line_results, review_reasons


def run_claim_calculation(
    rag_pipeline: Any,
    items: list[ClaimItemInput],
    context: ClaimCaseContext,
    basis_mode: str = "auto",
    selected_basis_docs: list[str] | None = None,
    use_fake_planner: bool = True,
    model_id: str = "gpt-5.4-mini",
    provider: str = "openai",
) -> CalculationResult:
    """사용자 청구 및 상황 정보에 기반하여 RAG 근거 검색, DB 매칭, LLM 계획 및 샌드박스 실행을 통합 수행한다."""
    # 1. 근거 문서 구성 (자동/수동)
    basis: BasisSelection = select_basis_documents(
        items=items,
        context=context,
        basis_mode=basis_mode,
        selected_docs=selected_basis_docs
    )

    # 2. 비급여 표준모델 DB 매칭
    standard_matches: list[StandardMatch] = []
    disambiguation_required = False
    disambiguation_candidates = []
    db_review_required = False
    db_review_reasons = []

    from src.claim_calculation.models import parse_money, parse_quantity

    for item in items:
        matches = match_standard_code(item.input_name, item.input_code)
        if not matches:
            # 매칭 없음 처리
            match_none = StandardMatch(
                std_cd_nm=item.input_name,
                match_confidence="none",
                requires_review=True
            )
            standard_matches.append(match_none)
            db_review_required = True
            db_review_reasons.append(f"항목 '{item.input_name}'에 매칭되는 비급여 표준모델 코드가 없습니다.")
        else:
            # 2개 이상 모호성 감지
            if len(matches) > 1:
                disambiguation_required = True
                candidate_info = ", ".join([f"{m.std_cd}({m.std_cd_nm})" for m in matches])
                db_review_reasons.append(
                    f"항목 '{item.input_name}'의 표준모델 매칭 후보가 2개 이상 존재하여 선택 모호성이 발생했습니다. "
                    f"후보군: [{candidate_info}]. 정확한 코드를 입력해주십시오."
                )
                for m in matches:
                    disambiguation_candidates.append({
                        "code": m.std_cd,
                        "name": m.std_cd_nm,
                        "mid_category": m.mid_category_cd_nm or ""
                    })

            # 첫 번째 결과를 대표 매치로 선택
            repr_match = matches[0]
            if repr_match.requires_review:
                db_review_required = True
                opn = repr_match.pay_opn_cd_nm or "공란"
                db_review_reasons.append(f"항목 '{item.input_name}'의 보상의견이 추가 확인 대상입니다. (의견: {opn})")
            standard_matches.append(repr_match)

    # 총 청구금액 합산
    total_claimed = Decimal("0")
    for item in items:
        try:
            qty = parse_quantity(item.quantity)
            claimed_unit = parse_money(item.claimed_amount)
            total_claimed += claimed_unit * qty
        except Exception as exc:
            # 파싱 에러 발생 시 외부로 버블링시켜 UI에서 방어할 수 있도록 함
            raise exc

    # 3. RAG 근거 문서 조회
    retrieved_evidences = []
    graph_result = None
    if rag_pipeline is not None and getattr(rag_pipeline, "graph_enabled", False) and rag_pipeline.graph_retriever:
        try:
            query_parts = []
            if context.situation_note:
                query_parts.append(context.situation_note)
            for item in items:
                query_parts.append(item.input_name)
            question = " ".join(query_parts)
            graph_result = rag_pipeline.graph_retriever.retrieve(question)
            for fact in graph_result.facts:
                if fact.status == "confirmed":
                    # confirmed evidence가 없는 사실은 retrieved_evidences에서 배제
                    if not fact.evidence:
                        continue
                    retrieved_evidences.append({
                        "source": "GraphDB (확정)",
                        "content": f"[CONFIRMED] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'}",
                        "page": "N/A"
                    })
                elif fact.status == "candidate":
                    retrieved_evidences.append({
                        "source": "GraphDB (검토 후보)",
                        "content": f"[CANDIDATE] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'} (이유: {fact.properties.get('matched_keyword', '')} 매칭)",
                        "page": "N/A"
                    })
        except Exception as e:
            logger.error(f"GraphDB 근거 조회 중 에러 발생: {e}")

    if rag_pipeline is not None and basis.doc_filter:
        rag_docs = [d for d in basis.doc_filter if d != "비급여 표준모델"]
        if rag_docs:
            query_parts = []
            if context.situation_note:
                query_parts.append(context.situation_note)
            for item in items:
                query_parts.append(item.input_name)
            question = " ".join(query_parts)

            try:
                # top_k는 명세 요구에 맞추어 적절한 개수(6개) 검색
                hits, _ = rag_pipeline.retrieve_hits(question, top_k=6, doc_filter=rag_docs)
                for hit in hits:
                    retrieved_evidences.append({
                        "source": hit.metadata.get("doc_short", "알수없음"),
                        "content": hit.document,
                        "page": hit.metadata.get("page_start", "?"),
                    })
            except Exception as e:
                logger.error(f"RAG 근거 조회 중 에러 발생: {e}")

    deterministic_line_results: list[dict[str, str | bool | list[str]]] = []
    deterministic_review_reasons: list[str] = []
    use_deterministic_calculation = use_fake_planner

    if use_deterministic_calculation:
        payable_val, deductible_val, deterministic_line_results, deterministic_review_reasons = _calculate_line_items(
            items=items,
            context=context,
            standard_matches=standard_matches,
        )
        sandbox_code = "# deterministic line-item calculation"
        plan = CalculationPlan(decision="calculable", formula_intent=sandbox_code)
    # 4. LLM 계산 계획 수립
    elif disambiguation_required:
        plan = CalculationPlan(
            decision="needs_more_info",
            uncertainties=db_review_reasons
        )
    else:
        planner = FakePlanner() if use_fake_planner else LLMPlanner(model_id=model_id, provider=provider)
        plan: CalculationPlan = planner.plan(items, context, retrieved_evidences)

    # 5. 계산 실행 (Python AST Sandbox)
    sandbox_error_occurred = False
    sandbox_error_msg = ""
    if not use_deterministic_calculation and plan.decision == "calculable" and plan.formula_intent:
        sandbox_code = plan.formula_intent
        try:
            exec_res = execute_calculation(sandbox_code)
            local_vars = exec_res.get("variables", {})

            # 유연한 변수명 매칭 추출
            raw_payable = local_vars.get("payable_amount") or local_vars.get("payable") or Decimal("0")
            raw_deductible = local_vars.get("deductible") or local_vars.get("deductible_amount") or Decimal("0")

            payable_val = Decimal(str(raw_payable))
            deductible_val = Decimal(str(raw_deductible))
        except Exception as e:
            sandbox_error_occurred = True
            sandbox_error_msg = f"AST 샌드박스 연산 실행 에러: {str(e)}"
            logger.error(sandbox_error_msg)
            payable_val = Decimal("0")
            deductible_val = Decimal("0")
    elif not use_deterministic_calculation:
        # 계산 불가 또는 보상 제외
        sandbox_code = ""
        sandbox_error_occurred = False
        sandbox_error_msg = ""
        payable_val = Decimal("0")
        deductible_val = Decimal("0")

    # 6. 최종 지급예상액 검증 및 검토 플래그 결정
    review_required = False
    review_reasons = []

    if deterministic_review_reasons:
        review_required = True
        review_reasons.extend(deterministic_review_reasons)

    # 결과값 정밀 검증
    if payable_val < 0:
        review_required = True
        review_reasons.append(f"지급예상액이 음수({payable_val})입니다. 0원 이상이어야 합니다.")
        payable_val = Decimal("0")

    if deductible_val < 0:
        review_required = True
        review_reasons.append(f"공제금액이 음수({deductible_val})입니다. 0원 이상이어야 합니다.")
        deductible_val = Decimal("0")

    if payable_val > total_claimed:
        review_required = True
        review_reasons.append(f"지급예상액({payable_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다.")

    if deductible_val > total_claimed:
        review_required = True
        review_reasons.append(f"공제금액({deductible_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다.")

    if payable_val + deductible_val > total_claimed:
        review_required = True
        review_reasons.append(
            f"지급예상액과 공제금액의 합({payable_val + deductible_val:,.0f}원)이 총 청구금액({total_claimed:,.0f}원)을 초과합니다."
        )

    # UI 및 결과 출력용으로 Decimal 값을 정수형 문자열 등으로 가공
    payable_str = f"{payable_val:,.0f}".replace(",", "")
    deductible_str = f"{deductible_val:,.0f}".replace(",", "")

    # Graph candidate rule 검토 플래그 강제 적용
    if graph_result:
        # candidate PAYS_BY_RATIO 만 있고 confirmed 정보가 없는 경우 검토 강제
        has_candidate_ratio = any(f.status == "candidate" and f.relation == "PAYS_BY_RATIO" for f in graph_result.facts)
        has_confirmed = any(f.status == "confirmed" for f in graph_result.facts)
        if has_candidate_ratio and not has_confirmed:
            review_required = True
            reason = "신뢰할 수 있는 확정 구조화 사실(confirmed)이 없으며, 후보 지급 비율(candidate PAYS_BY_RATIO)만 존재합니다. 지급예상액을 확정할 수 없습니다."
            if reason not in review_reasons:
                review_reasons.append(reason)

        has_graph_candidate = any(f.status == "candidate" for f in graph_result.facts)
        if has_graph_candidate:
            review_required = True
            for f in graph_result.facts:
                if f.status == "candidate":
                    reason = f"약관 규정({f.subject})과의 관계({f.relation})가 확정되지 않은 검토 후보 상태입니다. (매칭 정보: {f.object})"
                    if reason not in review_reasons:
                        review_reasons.append(reason)

    # 각 단계별 검토 플래그 병합
    if disambiguation_required:
        review_required = True
        review_reasons.extend(db_review_reasons)
    elif db_review_required:
        review_required = True
        review_reasons.extend(db_review_reasons)

    if sandbox_error_occurred:
        review_required = True
        review_reasons.append(sandbox_error_msg)

    if plan.decision == "needs_more_info":
        review_required = True
        review_reasons.append("상황 정보가 부족하여 계산을 일시 보류합니다. 추가 확인이 필요합니다.")
        for unc in plan.uncertainties:
            if unc not in review_reasons:
                review_reasons.append(unc)
    elif plan.decision == "not_covered":
        review_required = True
        review_reasons.append("해당 건은 보상 대상(면책)에 포함되지 않습니다.")
        for unc in plan.uncertainties:
            if unc not in review_reasons:
                review_reasons.append(unc)

    # applied_basis에 RAG 검색 출처 정보와 DB 매치 정보를 구성
    applied_basis = []
    # DB 매치 근거 추가
    for idx, match in enumerate(standard_matches):
        if match.std_cd:
            applied_basis.append({
                "source": f"비급여 표준모델 (코드: {match.std_cd})",
                "content": f"표준명: {match.std_cd_nm} | 분류: {repr(match.mid_category_cd_nm)} | 보상의견: {match.pay_opn_cd_nm or '없음'}"
            })
    # RAG 문서 근거 추가
    for ev in retrieved_evidences:
        applied_basis.append({
            "source": f"{ev['source']} p.{ev['page']}",
            "content": ev["content"][:200] + ("..." if len(ev["content"]) > 200 else "")
        })

    # applied_limits 구성
    _gen = _normalize_policy_generation(context.policy_generation)
    _applied_limits: dict[str, str] = {"policy_generation": _gen}
    try:
        from src.claim_calculation.deductible_rules import lookup_rule as _lr
        _sample_rule = _lr(_gen, "급여", context.visit_type or "outpatient", context.facility_grade)
        if _sample_rule.per_visit_limit:
            _applied_limits["per_visit_limit"] = str(_sample_rule.per_visit_limit)
        if _sample_rule.annual_limit:
            _applied_limits["annual_limit"] = str(_sample_rule.annual_limit)
        if _sample_rule.annual_visit_limit:
            _applied_limits["annual_visit_limit"] = str(_sample_rule.annual_visit_limit)
        _applied_limits["remaining_note"] = "단건 기준 (과거 청구 이력 미반영)"
    except Exception:
        pass

    return CalculationResult(
        claimed_amount=str(total_claimed),
        payable_amount=payable_str,
        deductible=deductible_str,
        formula_intent=sandbox_code,
        executed_code=sandbox_code,
        applied_basis=applied_basis,
        requires_review=review_required,
        review_reasons=review_reasons,
        notes="지급예상액 계산이 성공적으로 완료되었습니다." if not review_required else "추가 심사 검토가 필요합니다.",
        candidates=disambiguation_candidates,
        policy_generation=_normalize_policy_generation(context.policy_generation),
        line_results=deterministic_line_results,
        applied_limits=_applied_limits,
    )
