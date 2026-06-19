"""보험금 계산 LLM Planner 테스트."""

from __future__ import annotations

from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.planner import LLMPlanner


class DummyLLM:
    def __init__(self) -> None:
        self.prompt = ""
        self.temperature = None

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int | None = None) -> str:
        self.prompt = prompt
        self.temperature = temperature
        return """
        {
          "decision": "calculable",
          "basis_summary": [{"source": "테스트 약관", "content": "검증된 근거"}],
          "variables": {"claimed_amount": "100000"},
          "calculation_steps": ["청구액 확인", "공제액 계산"],
          "formula_intent": "claimed_amount = Decimal('100000')\\ndeductible = Decimal('20000')\\npayable_amount = claimed_amount - deductible",
          "uncertainties": []
        }
        """


def test_llm_planner_uses_generate_interface(monkeypatch) -> None:
    """프로젝트 LLM 클라이언트 공통 인터페이스인 generate()로 계산 계획을 생성한다."""

    dummy = DummyLLM()

    def fake_build_llm(model_id: str, provider: str):
        return dummy

    monkeypatch.setattr("src.claim_calculation.planner.build_llm", fake_build_llm)

    planner = LLMPlanner(model_id="local-test", provider="vllm")
    plan = planner.plan(
        items=[
            ClaimItemInput(
                line_id="item_1",
                input_name="도수치료",
                claimed_amount="100000",
            )
        ],
        context=ClaimCaseContext(visit_type="outpatient"),
        retrieved_evidences=[
            {
                "source": "GraphDB (검토 후보)",
                "content": "[CANDIDATE] 후보 지급비율 70%",
            }
        ],
    )

    assert plan.decision == "calculable"
    assert dummy.temperature == 0.0
    assert "GraphDB (검토 후보)" in dummy.prompt
    assert "[CANDIDATE]" in dummy.prompt
    assert "확정 근거가 아닙니다" in dummy.prompt
    assert "임의로 수가코드, 지급비율, 약관 조항을 만들어 보완하지 마세요" in dummy.prompt
    assert "새 계산식이나 공제율을 만들지 말고" in dummy.prompt
