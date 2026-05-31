"""LLM 기반 계산계획 수립 (Planner) 모듈."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext, CalculationPlan
from src.claim_calculation.code_sandbox import normalize_calculation_code
from src.llm.factory import build_llm

logger = logging.getLogger(__name__)


class LLMPlanner:
    """실제 LLM을 호출하여 계산 계획을 수립하는 플래너."""

    def __init__(self, model_id: str = "gpt-5.4-mini", provider: str = "openai"):
        self.model_id = model_id
        self.provider = provider
        # build_llm은 lazy하게 필요할 때 호출할 수도 있음.

    def plan(
        self,
        items: list[ClaimItemInput],
        context: ClaimCaseContext,
        retrieved_evidences: list[dict[str, Any]]
    ) -> CalculationPlan:
        """LLM을 호출하여 입력 사례와 RAG 근거를 바탕으로 계산 계획 JSON을 생성한다."""
        client = build_llm(self.model_id, self.provider)
        prompt = self._build_prompt(items, context, retrieved_evidences)

        try:
            # Project LLM clients expose the shared generate() interface.
            response_text = client.generate(prompt, temperature=0.0)
            plan_data = self._parse_and_validate_json(response_text)
            return self._map_to_plan(plan_data)
        except Exception as e:
            logger.error(f"LLM 계획 수립 중 에러 발생: {e}")
            # Fallback 계산 계획 생성
            return CalculationPlan(
                decision="needs_more_info",
                uncertainties=[f"LLM 계획 생성 실패 또는 JSON 파싱 오류: {str(e)}"]
            )

    def _build_prompt(
        self,
        items: list[ClaimItemInput],
        context: ClaimCaseContext,
        evidences: list[dict[str, Any]]
    ) -> str:
        # LLM에게 JSON만을 정확히 반환하도록 유도하는 프롬프트
        items_summary = []
        for it in items:
            items_summary.append(
                f"- 항목: {it.input_name} (코드: {it.input_code or '없음'}), 청구액: {it.claimed_amount}원, 수량: {it.quantity}, 카테고리힌트: {it.user_category_hint or '없음'}"
            )
        items_str = "\n".join(items_summary)

        evidence_str = ""
        for i, ev in enumerate(evidences):
            evidence_str += f"[{i+1}] 출처: {ev.get('source', '알수없음')}\n내용: {ev.get('content', '')}\n\n"

        prompt = f"""
당신은 보험금 지급액 계산 전문가입니다.
아래의 [청구 정보]와 약관 및 표준모델 등 [근거 문서] 내용을 참고하여, 지급예상액 계산 계획을 수립하세요.

[청구 정보]
- 사고/보상 맥락:
  * 치료일: {context.treatment_date}
  * 방문형태: {context.visit_type} (hospitalization: 입원, outpatient: 통원)
  * 진단: {context.diagnosis_name} (코드: {context.diagnosis_code})
  * 사고유형: {context.accident_type}
  * 상황 메모: {context.situation_note}
- 청구 항목 목록:
{items_str}

	[근거 문서]
	{evidence_str}

	[작성 규칙]
	1. 반드시 아래 스키마에 맞는 JSON 데이터 하나만을 출력하세요. 마크다운 코드 블록(예: ```json 등)이나 기타 부연 설명 텍스트를 절대 포함하지 말고, 순수 JSON 텍스트 하나만 출력하세요.
	2. 'formula_intent' 필드에는 보안 Python AST 샌드박스에서 Decimal 연산으로 바로 실행될 수 있는 유효한 Python 코드 조각을 작성해야 합니다.
	   - 반드시 'claimed_amount', 'deductible', 'payable_amount' 변수가 최종적으로 할당되도록 하세요.
	   - 내장 함수는 max, min, abs만 사용할 수 있고, 수치는 Decimal('값')으로 감싸야 합니다. (예: Decimal('150000') * Decimal('0.2'))
	   - import 문은 작성하지 마세요. Decimal, max, min, abs는 샌드박스 실행 환경에 이미 제공됩니다.
	   - 사용자가 입력한 청구액은 이 MVP 계산에서 해당 항목의 보장대상/청구 의료비로 사용합니다. 약관에 "보장대상 의료비", "청구금액", "비급여 의료비" 같은 표현이 나오면 별도 금액이 명시되지 않는 한 입력 청구액(`claimed_amount`)에 대응시켜 계산하세요.
	   - 수량/횟수가 1보다 크면 항목별 청구액과 수량을 곱한 총액을 `claimed_amount`로 사용하세요.
	   - 예시:
	     claimed_amount = Decimal('150000')
	     deductible = max(Decimal('30000'), claimed_amount * Decimal('0.2'))
	     payable_amount = claimed_amount - deductible
	3. 근거 출처가 "GraphDB (검토 후보)"이거나 내용에 "[CANDIDATE]"가 포함된 정보는 확정 근거가 아닙니다. 이 정보만으로 보상 여부, 지급비율, 공제식, 계산식을 확정하지 말고 decision을 "needs_more_info"로 두거나 uncertainties에 사용자/심사자 확인 필요 사유를 적으세요.
	4. 근거 내용에 "[MISSING]" 또는 "확인불가"가 포함된 항목은 임의로 수가코드, 지급비율, 약관 조항을 만들어 보완하지 마세요.

JSON Schema:
{{
  "decision": "calculable" | "needs_more_info" | "not_covered",
  "basis_summary": [
    {{
      "source": "근거 출처명",
      "content": "적용 사유 또는 약관 문구 요약"
    }}
  ],
  "variables": {{
    "변수명": "값 (Decimal 생성에 들어갈 문자열)"
  }},
  "calculation_steps": [
    "단계별 한글 설명"
  ],
  "formula_intent": "Python 실행 코드 조각",
  "uncertainties": [
    "계산 시 불확실한 요소나 확인이 필요한 내용 목록"
  ]
}}
"""
        return prompt

    def _parse_and_validate_json(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        # ```json 이나 ```가 포함되어 있으면 그것을 제거
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)

        # 1. decision enum 검증
        decision = data.get("decision")
        if decision not in ("calculable", "needs_more_info", "not_covered"):
            raise ValueError(f"올바르지 않은 decision 값입니다: {decision}")

        # 2. basis_summary 타입 검증
        basis_summary = data.get("basis_summary", [])
        if not isinstance(basis_summary, list):
            raise ValueError("basis_summary는 리스트 형태여야 합니다.")
        for idx, item in enumerate(basis_summary):
            if not isinstance(item, dict):
                raise ValueError(f"basis_summary[{idx}]는 딕셔너리 형태여야 합니다.")
            if "source" not in item or "content" not in item:
                raise ValueError(f"basis_summary[{idx}]에 'source' 또는 'content' 키가 누락되었습니다.")
            if not isinstance(item["source"], str) or not isinstance(item["content"], str):
                raise ValueError(f"basis_summary[{idx}]의 'source'와 'content'는 문자열이어야 합니다.")

        # 3. calculation_steps 타입 검증
        calculation_steps = data.get("calculation_steps", [])
        if not isinstance(calculation_steps, list):
            raise ValueError("calculation_steps는 리스트 형태여야 합니다.")
        for idx, step in enumerate(calculation_steps):
            if not isinstance(step, str):
                raise ValueError(f"calculation_steps[{idx}]는 문자열이어야 합니다.")

        # 4. uncertainties 타입 검증
        uncertainties = data.get("uncertainties", [])
        if not isinstance(uncertainties, list):
            raise ValueError("uncertainties는 리스트 형태여야 합니다.")
        for idx, unc in enumerate(uncertainties):
            if not isinstance(unc, str):
                raise ValueError(f"uncertainties[{idx}]는 문자열이어야 합니다.")

        # 5. formula_intent 검증
        formula_intent = data.get("formula_intent")
        if formula_intent is not None and not isinstance(formula_intent, str):
            raise ValueError("formula_intent는 문자열 형태여야 합니다.")

        # 6. decision = calculable 이면 formula_intent 필수
        if decision == "calculable":
            if not formula_intent or not formula_intent.strip():
                raise ValueError("decision이 'calculable'일 때는 formula_intent가 비어있을 수 없습니다.")

            # formula_intent가 있을 경우, 'claimed_amount', 'deductible', 'payable_amount' 변수가 할당되는지 AST 분석
            import ast
            formula_intent = normalize_calculation_code(formula_intent)
            data["formula_intent"] = formula_intent
            try:
                tree = ast.parse(formula_intent)
            except SyntaxError as e:
                raise ValueError(f"formula_intent 파이썬 코드 문법 오류: {str(e)}")

            assigned_vars = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assigned_vars.add(target.id)
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        assigned_vars.add(node.target.id)

            required_vars = {"claimed_amount", "deductible", "payable_amount"}
            missing_vars = required_vars - assigned_vars
            if missing_vars:
                raise ValueError(f"formula_intent에서 필수 변수가 할당되지 않았습니다: {missing_vars}")

        return data

    def _map_to_plan(self, data: dict[str, Any]) -> CalculationPlan:
        return CalculationPlan(
            decision=data.get("decision", "needs_more_info"),
            basis_summary=data.get("basis_summary", []),
            variables=data.get("variables", {}),
            calculation_steps=data.get("calculation_steps", []),
            formula_intent=data.get("formula_intent", ""),
            uncertainties=data.get("uncertainties", [])
        )


class FakePlanner:
    """테스트 및 LLM 부재 환경을 위한 결정론적 모의 플래너."""

    def plan(
        self,
        items: list[ClaimItemInput],
        context: ClaimCaseContext,
        retrieved_evidences: list[dict[str, Any]]
    ) -> CalculationPlan:
        """입력 조건에 부합하는 미리 정의된 계산 계획을 리턴한다."""
        if not items:
            return CalculationPlan(decision="needs_more_info", uncertainties=["청구 항목이 없습니다."])

        first_item = items[0]
        name = first_item.input_name
        claimed_val = first_item.claimed_amount

        from src.claim_calculation.models import parse_money
        claimed_decimal = parse_money(claimed_val)
        claimed_clean_str = str(claimed_decimal)

        # 1. 보상 제외 시나리오 테스트 대응 (예: '도수치료 제외')
        if "제외" in name or "not_covered" in name:
            return CalculationPlan(
                decision="not_covered",
                basis_summary=[
                    {"source": "약관 면책조항", "content": "치료 목적이 아닌 단순 미용 또는 보상 제외 대상 항목입니다."}
                ],
                variables={
                    "claimed_amount": claimed_clean_str,
                    "deductible": claimed_clean_str,
                    "payable_amount": "0"
                },
                calculation_steps=[
                    "1. 청구 항목이 보상 제외 대상으로 확인되었습니다.",
                    "2. 지급예상액은 0원입니다."
                ],
                formula_intent=(
                    f"claimed_amount = Decimal('{claimed_clean_str}')\n"
                    f"deductible = Decimal('{claimed_clean_str}')\n"
                    f"payable_amount = Decimal('0')"
                ),
                uncertainties=["비치료성 시술 여부를 서류상 재확인해야 합니다."]
            )

        # 2. 정보 부족 시나리오
        if "정보부족" in name or "needs_more_info" in name:
            return CalculationPlan(
                decision="needs_more_info",
                uncertainties=["진단서 혹은 영수증 세부 내역서 확인이 필요하여 계산을 보류합니다."]
            )

        # 3. 도수치료 표준 계산 시나리오 (150,000원 청구 시 3만원/30% 중 큰 금액 공제 적용하여 105,000원 지급예상액 산출)
        if "도수" in name or "도수치료" in name:
            return CalculationPlan(
                decision="calculable",
                basis_summary=[
                    {"source": "실손의료비 약관(4세대)", "content": "비급여 도수치료는 1회당 3만원과 보장대상 금액의 30% 중 큰 금액을 공제합니다."}
                ],
                variables={
                    "claimed_amount": claimed_clean_str,
                    "deductible_min": "30000",
                    "co_ratio": "0.3"
                },
                calculation_steps=[
                    f"1. 청구금액 {claimed_val}원 감지.",
                    "2. 자기부담금 산출: max(30,000원, 청구금액 * 30%)",
                    f"3. max(30,000, {claimed_decimal * Decimal('0.3'):.0f}) 적용"
                ],
                formula_intent=(
                    f"claimed_amount = Decimal('{claimed_clean_str}')\n"
                    f"deductible = max(Decimal('30000'), claimed_amount * Decimal('0.3'))\n"
                    f"payable_amount = claimed_amount - deductible"
                ),
                uncertainties=["도수치료는 통산 50회 한도 내에서 지급됩니다."]
            )

        # 4. 기본 일반 계산 시나리오 (자기부담금 20% 적용)
        return CalculationPlan(
            decision="calculable",
            basis_summary=[
                {"source": "실손의료비 기본 약관", "content": "비급여 항목에 대해 자기부담금 20%를 적용합니다."}
            ],
            variables={
                "claimed_amount": claimed_clean_str,
                "co_ratio": "0.2"
            },
            calculation_steps=[
                f"1. 청구금액 {claimed_val}원 확인.",
                "2. 20% 자기부담비율 적용."
            ],
            formula_intent=(
                f"claimed_amount = Decimal('{claimed_clean_str}')\n"
                f"deductible = claimed_amount * Decimal('0.2')\n"
                f"payable_amount = claimed_amount - deductible"
            ),
            uncertainties=[]
        )
