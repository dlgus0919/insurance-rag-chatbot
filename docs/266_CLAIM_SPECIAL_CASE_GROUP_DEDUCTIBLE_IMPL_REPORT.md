# 266. 5세대 산정특례 및 그룹 공제 계산 보완 구현 보고서

## 개요

5세대 실손 보험금 계산에서 산정특례 여부를 케이스 단위로 입력받고, 3대비급여/MRI-MRA 보완 계산과 동일 공제 그룹 합산 공제를 연결했다. 이번 구현은 산정특례 여부를 항목별로 받지 않고, 한 번의 계산 요청 전체에 적용하는 구조로 제한했다.

## 핵심 변경

- `ClaimCaseContext`와 API 요청/응답에 `special_calculation_status`를 추가했다.
- 프론트엔드 보험금 계산 입력 영역에 산정특례 여부 선택값을 추가했다.
- 5세대 3대비급여는 산정특례 상태가 불명확하면 자동 지급액에 포함하지 않고 추가 확인 대상으로 분리한다.
- 산정특례 적용 3대비급여는 승인된 중증 비급여 룰 경로로 계산한다.
- 산정특례 미적용 MRI/MRA는 전용 active rule이 없으면 자동 계산하지 않는다.
- 동일 공제 그룹 항목은 합산 금액 기준으로 1회 공제를 적용한 뒤 항목별로 배분한다.
- 계산 결과 스냅샷과 일반 질의 후속 재계산 흐름에 산정특례 상태를 저장한다.
- 5세대 산정특례/3대비급여/MRI-MRA 범위에 한정한 계산 룰 후보 추출 모드를 추가했다.

## 000번 규칙 점검

- 3대비급여/MRI-MRA 보완값은 코드에 직접 보험 지식값으로 고정하지 않고, active rule manifest와 승인 후보 흐름을 통해 반영하도록 했다.
- 그룹 합산 공제는 특정 상품 지식값이 아니라 동일 공제 단위에 1회 공제를 적용하는 계산 엔진 규칙으로 코드에 두었다.
- 산정특례 여부는 실무자가 계산 요청 단위로 명시하거나, 후속 질의에서 명확히 언급한 경우에만 반영한다.
- 불명확한 후속 질의는 임의 추정하지 않고 산정특례 적용/미적용 확인을 요청한다.

## 검증

DGX 메인 저장소 기준으로 다음 검증을 수행했다.

```bash
PYTHONPYCACHEPREFIX=/tmp/insurance-rag-pycache .venv/bin/python -m py_compile \
  src/claim_calculation/models.py \
  src/api/schemas/claim.py \
  src/api/routes/claim.py \
  src/api/routes/chat.py \
  src/api/rag_service.py \
  src/claim_calculation/deductible_rules.py \
  src/claim_calculation/pipeline.py \
  src/claim_calculation/rule_candidates.py \
  src/claim_calculation/thread_recalculation.py \
  scripts/extract_claim_rule_candidates.py \
  scripts/claim_rule_candidate_review.py
```

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py \
  tests/test_claim_rule_candidates.py \
  tests/test_claim_rule_candidate_review.py \
  tests/test_api_chat_stream.py \
  -q
```

결과:

- 문법 검증 통과
- 관련 pytest `96 passed, 1 warning`
- `scripts/extract_claim_rule_candidates.py --scope special-case-5th --limit 20 --dry-run` 정상 실행

## 남은 위험

- 5세대 MRI/MRA 산정특례 미적용 전용 rule은 후보 승인 및 apply 전까지 자동 지급 계산에 포함되지 않는다.
- 이번 작업은 결정론적 계산/후속질의/후보 추출 경로 검증까지 수행했으며, LLM 서버와 전체 앱 기동 검증은 수행하지 않았다.
