# 199. 미분류 비급여 Human Task 세대 공통 적용 보고

## 목적

실무자 요구에 따라 미분류 비급여 항목을 4세대와 5세대 실손 모두에서 자동 지급 산정에 포함하지 않고 Human Task 대상으로 분리한다.

## 적용 내용

- `src/claim_calculation/pipeline.py`
  - 세대 전용 5세대 판정을 제거하고, 표준모델/보상의견으로 보장 유형이 확정되지 않은 비급여를 세대 공통 Human Task로 분리한다.
  - 급여 본인부담금과 미분류 비급여가 한 라인에 함께 입력된 경우 급여분만 자동 계산하고 비급여분만 Human Task 금액으로 분리한다.
  - `line_results`에 `calculation_status`, `excluded_from_calculation`, `human_task_amount`를 내려준다.
- `frontend/js/pages/chat.js`
  - Human Task 대상 라인을 항목별 계산에서 분리해 별도 `Human Task 분류` 섹션에 표시한다.
- `tests/test_claim_calculation_pipeline.py`
  - 5세대 미분류 비급여 제외 회귀 테스트를 추가했다.
  - 4세대 미분류 비급여 제외 회귀 테스트를 추가했다.
  - 표준모델 보상의견이 명확한 비급여는 기존 계산 흐름이 유지되는지 보호 테스트를 추가했다.

## 기대 효과

- 미분류 비급여를 임시 공제율로 자동 계산해 지급예상액을 과대 산출하는 문제를 방지한다.
- 실무자가 별도 판단해야 하는 항목을 출력 단에서 명확히 분리한다.
- 4세대와 5세대 모두 같은 보수적 산정 원칙을 적용한다.

## 검증

```bash
.venv/bin/python -m pytest tests/test_api_claim_calculation.py tests/test_claim_calculation_pipeline.py -q
node --check frontend/js/pages/chat.js
```

결과:

- `tests/test_api_claim_calculation.py tests/test_claim_calculation_pipeline.py`: 43 passed, 1 warning
- `frontend/js/pages/chat.js`: syntax OK
- 샘플 진료비 계산 재실행: 총 청구 7,230,470원 / 자동 지급 2,703,216원 / 공제 1,719,054원 / Human Task 2,808,200원
