# 117. 보험금 계산 LLM Planner 및 Graph 상충 근거 보강 보고서

## 1. 작업 배경

GraphDB 앱 적용 후 남은 목표 중 하나는 보험금 지급예상액 계산에서 약관/표준모델/GraphDB 근거를 바탕으로 LLM이 계산용 Python 코드를 생성하고, 샌드박스에서 정량 계산하는 것이다.

검토 중 `LLMPlanner`가 프로젝트 공통 LLM 클라이언트 인터페이스와 맞지 않는 `complete()` 메서드를 호출하고 있어, Streamlit에서 `LLM Planner`를 선택하면 실제 계산 계획 생성이 실패할 수 있음을 확인했다.

## 2. 변경 내용

- `src/claim_calculation/planner.py`
  - LLM 호출을 `client.complete(prompt)`에서 `client.generate(prompt, temperature=0.0)`로 수정했다.
  - GraphDB 후보 근거(`GraphDB (검토 후보)`, `[CANDIDATE]`)만으로 보상 여부, 지급비율, 공제식, 계산식을 확정하지 말라는 프롬프트 제약을 추가했다.
  - `[MISSING]` 또는 확인불가 항목에 대해 수가코드, 지급비율, 약관 조항을 임의 생성하지 말라는 환각 방지 규칙을 추가했다.

- `tests/test_claim_planner.py`
  - 프로젝트 LLM 클라이언트의 공통 인터페이스인 `generate()`가 호출되는지 검증하는 회귀 테스트를 추가했다.
  - 후보 GraphDB 근거 사용 제한 문구가 LLM Planner 프롬프트에 포함되는지 검증했다.

- `src/graph/context.py`
  - 같은 대상/관계에 대해 GraphDB fact 값이 여러 개 존재하면 하나로 통합하지 말고 문서/근거/상태별 경우의 수를 모두 분리해 답변하도록 지시를 추가했다.
  - 복수 값이 감지되면 `GraphDB 복수 값/상충 후보` 섹션으로 프롬프트에 명시한다.

- `src/ui/chat_store.py`
  - 저장된 GraphDB evidence를 복원할 때 `source_version`을 보존하도록 보강했다.

- `tests/test_graph_context.py`
  - 같은 Graph relation에 복수 값이 있을 때 통합 금지 지침과 값 목록이 context에 포함되는지 검증하는 회귀 테스트를 추가했다.

## 3. 검증 결과

원격 DGX 환경에서 다음 명령을 실행했다.

```bash
.venv/bin/pytest tests/test_claim_planner.py tests/test_claim_calculation_pipeline.py -v
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
.venv/bin/pytest tests/test_graph_context.py tests/test_graph_query_planner.py tests/test_graph_retriever.py tests/test_streamlit_app.py tests/test_claim_planner.py tests/test_claim_calculation_pipeline.py -q
.venv/bin/pytest -q
```

결과:

```text
10 passed in 0.05s
Evaluation Summary: 5/5 cases passed.
34 passed, 1 warning in 0.33s
330 passed, 3 warnings in 2.84s
```

추가로 실제 로컬 SGLang `gpt-oss-20b`를 사용해 `LLMPlanner`가 계산 계획 JSON을 생성하고, 샌드박스가 Python 계산 코드를 실행하는 경로를 확인했다.

검증 조건:

- 청구 항목: 도수치료
- 청구액: 150,000원
- 약관 근거: 비급여 도수치료 통원 치료는 1회당 3만원과 보장대상 의료비의 30% 중 큰 금액을 공제
- Planner: `LLMPlanner(model_id="gpt-oss-20b", provider="sglang")`

결과:

```text
requires_review False
claimed 150000
payable 105000
deductible 45000
code claimed_amount = Decimal('150000')
deductible = max(Decimal('30000'), claimed_amount * Decimal('0.3'))
payable_amount = claimed_amount - deductible
reasons []
```

즉, LLM이 약관 근거를 계산식으로 변환하고, AST 샌드박스가 정량 금액을 산출하는 기본 경로가 동작함을 확인했다.

## 4. 남은 작업

- 실제 Streamlit에서 `LLM Planner`를 선택해 로컬 vLLM/SGLang 모델이 계산 계획 JSON을 안정적으로 반환하는지 수동 QA가 필요하다.
- GraphDB의 candidate 지급비율은 여전히 확정 계산식에 직접 투입하면 안 되며, UI와 결과에서 검토 필요 상태를 유지해야 한다.
- 원격 루트에 잘못 복사된 임시 파일(`context.py`, `chat_store.py`, `test_graph_context.py`)은 커밋 전 삭제해야 한다. 현재 자동 승인/사용량 제한으로 Codex가 직접 삭제하지 못했다.
