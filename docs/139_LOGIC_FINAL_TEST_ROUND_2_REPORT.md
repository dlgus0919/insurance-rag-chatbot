# 139. 로직 결점 Final 테스트 2차 보고

작성일: 2026-05-28
대상: 보험 문서 RAG 챗봇 로직 결점 5종
검증 환경: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`

## 1. 목적

초기 결점으로 정의된 아래 5개 항목이 현재 코드에서 재발하지 않는지 로직 전용 Final 테스트로 확인했다.

1. 면책 코드가 LLM 계산 경로에서 덮어써지는 문제
2. `from decimal import Decimal`로 sandbox가 실패하는 문제
3. 5세대 비중증 비급여/MRI 공제율과 한도 계산이 흔들리는 문제
4. HIRA 표 행 검색 실패로 `Q8061/Q8062`를 놓치는 문제
5. GraphDB evidence chunk ID와 VectorStore ID 불일치 문제

이번 2차 Final 테스트는 모델 응답 품질이 아니라 현재 백엔드 로직이 위 결점을 구조적으로 막는지 검증하는 데 초점을 맞췄다.

## 2. 추가한 Final 테스트

신규 테스트 파일:

```text
tests/test_logic_final_round_2.py
```

케이스:

1. `51040` 면책 코드 입력 시 즉시 `payable=0`, `deductible=claimed_amount`
2. `from decimal import Decimal` 포함 산식을 sandbox가 정규화 후 정상 실행
3. 5세대 MRI `HE115`, 통원 500,000원에 대해 50% 공제 후 건당 200,000원 한도 적용
4. HIRA row fallback으로 `Q8061/Q8062` 복원
5. Graph evidence id mismatch 시 `get_by_ids`/`get_by_doc_page` fallback으로 근거 복구

## 3. 실행 명령과 결과

### Final 테스트 2차 단독 실행

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_logic_final_round_2.py -q
```

결과:

```text
5 passed in 0.51s
```

### 기존 회귀 + Final 테스트 2차 통합 실행

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_claim_code_sandbox.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_vector_store.py \
  tests/test_pipeline.py \
  tests/test_logic_final_round_2.py -q
```

결과:

```text
92 passed in 1.13s
```

## 4. 판정

초기 결점 5종에 대해 현재 코드가 다음을 만족함을 확인했다.

- 면책/보상제외 코드는 LLM 계산 경로보다 먼저 hard-stop 된다.
- Decimal import 충돌은 정규화로 해소된다.
- 5세대 MRI/비중증 계열은 deterministic rule과 건당 한도가 적용된다.
- HIRA 췌이식술 row-level 근거는 fallback으로 복원된다.
- GraphDB evidence chunk id mismatch는 VectorStore fallback으로 흡수된다.

따라서 이번 목표 범위인 "로직 자체의 문제로 챗봇 답변 부정확성을 유발하는 항목"에 대해서는 현재 결점 5종이 해결 상태로 판정된다.

## 5. 범위 밖 잔여 사항

- HTTP 429 / 모델 서버 병목은 운영 문제이므로 이번 판정 범위에서 제외했다.
- 키워드 기반 자동 채점의 의미적 오판 문제는 평가 도구 한계이므로 이번 판정 범위에서 제외했다.
- MRI 5세대 기대값이 과거 평가셋과 충돌하는 문제는 로직 결함이 아니라 평가 기준 불일치로 본다.
