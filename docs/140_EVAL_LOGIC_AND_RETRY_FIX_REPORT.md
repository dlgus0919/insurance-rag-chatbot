# 140. 평가 로직 및 429 재시도 보강 보고

작성일: 2026-05-28
대상: Stage2 직접 평가 스크립트, 대형 모델 평가 스크립트, OpenAI 호환 LLM 클라이언트

## 1. 해결 대상

이번 보강은 이전에 남겨둔 두 부류의 문제를 다뤘다.

1. 실손 세대별 평가 기대값이 실제 공제 규칙과 어긋나는 문제
2. 429 및 금액 표현 차이 때문에 평가가 불안정하거나 오판정되는 문제

## 2. 적용한 수정

### 2.1 Stage2 직접 평가의 세대별 기대값 보정

수정 파일:

```text
scripts/stage2_direct_model_eval.py
```

핵심 변경:

- `claim_dosu_mx122_4th`
- `claim_dosu_mx122_5th`
- `claim_mri_he115_5th`
- `claim_nonsevere_200k_4th`
- `claim_nonsevere_200k_5th`

위 5개 케이스에 대해 하드코딩된 `payable_amount`, `deductible`를 직접 비교하지 않고, `deductible_rules.lookup_rule()` 기반으로 기대값을 파생하는 `_derive_expected_claim()`를 추가했다.

효과:

- `claim_mri_he115_5th`는 이제 5세대 3대비급여 통원 50% 공제 후 `건당 20만원 한도`를 반영해 `지급 200000 / 공제 300000`을 기대값으로 사용한다.
- 향후 규칙 테이블이 바뀌면 evaluator 기대값도 같은 기준으로 따라간다.

### 2.2 금액 표현 차이 정규화

수정 파일:

```text
scripts/eval_large_model_rag.py
scripts/stage2_direct_model_eval.py
```

핵심 변경:

- `350만원` → `3500000원`
- `6만원` → `60000원`
- `3,500,000원` → `3500000원`

형태로 정규화 후 비교하도록 수정했다.

효과:

- `350만원`과 `3,500,000원`
- `6만원`과 `60,000원`

같은 의미의 답변이 키워드 표기 차이만으로 FAIL 처리되는 문제를 줄였다.

### 2.3 OpenAI 호환 로컬 LLM 클라이언트의 429 재시도

수정 파일:

```text
src/llm/openai_compatible_client.py
```

핵심 변경:

- `generate()`, `generate_stream()`에 대해 `429/502/503/504` 재시도를 추가했다.
- `Retry-After` 헤더가 있으면 우선 사용하고, 없으면 bounded exponential backoff를 적용한다.

효과:

- 일시적인 로컬 서빙 병목으로 한 번 429가 나더라도 곧바로 실패하지 않고 재시도한다.
- 평가 스크립트가 모델 서빙 순간 부하에 덜 민감해진다.

## 3. 추가 테스트

신규 테스트:

```text
tests/test_stage2_direct_model_eval.py
```

보강 테스트:

```text
tests/test_openai_compatible_client.py
tests/test_large_model_eval.py
```

검증 내용:

- Stage2 evaluator가 MRI 5세대 기대값을 `200000 / 300000`으로 파생하는지
- `350만원`과 `3,500,000원`, `6만원`과 `60,000원`이 같은 값으로 인식되는지
- OpenAI 호환 클라이언트가 429 뒤에 정상 응답이 오면 재시도로 복구하는지
- 스트리밍 호출도 429 뒤 재시도로 복구하는지

## 4. 실행 결과

DGX에서 실행:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_openai_compatible_client.py \
  tests/test_large_model_eval.py \
  tests/test_stage2_direct_model_eval.py -q
```

결과:

```text
16 passed in 7.42s
```

통합 회귀:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_claim_code_sandbox.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_vector_store.py \
  tests/test_pipeline.py \
  tests/test_logic_final_round_2.py \
  tests/test_openai_compatible_client.py \
  tests/test_large_model_eval.py \
  tests/test_stage2_direct_model_eval.py -q
```

결과:

```text
108 passed in 8.26s
```

## 5. 결론

- 실손 세대별 계산 기대값은 이제 하드코딩 숫자가 아니라 규칙 테이블 기반으로 평가된다.
- 429는 완전히 제거된 것이 아니라, 일시적 병목에 대한 내성이 추가된 상태다.
- 평가 로직은 여전히 keyword/regex 중심이지만, 금액 표기 차이로 인한 대표적인 오판정은 줄였다.
