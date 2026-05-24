# Current App Test Loop 1 Report

작성일: 2026-05-23
대상 버전: `origin/master` 기준 `b688160` 이후 테스트 보강 작업본
목적: 현재 앱의 질의 기능과 보험금 계산 기능을 실무 사용 기준으로 평가하고, 1차 결함을 개선한 뒤 재검증한다.

## 1. 평가 기준

이번 루프에서는 오답을 미답변보다 더 큰 위험으로 본다. 특히 보험금 계산 기능은 실무 금액 판단에 직접 연결되므로 가장 엄격하게 평가한다.

| 영역 | 통과 기준 | 치명 결함 |
| --- | --- | --- |
| 보험금 계산 | 핵심 계산 시나리오 95% 이상 통과, 지급액/공제액/검토 플래그가 모두 정합해야 함 | 지급액 과다 산정, 후보/불확실 근거를 확정 계산으로 사용, 음수/총청구액 초과 방치 |
| 일반 RAG 질의 | smoke 95% 이상, hard/safety 85% 이상, 출처 누락 0건 목표 | 없는 코드 생성, 문서 간 코드 혼합, 약관 판단 과잉 단정 |
| 인덱스 모드 비교 | retrieval-only smoke 100%, full-answer smoke 95% 이상 | 기대 근거 누락, v1 OCR이 v2 보정 결론을 덮어씀 |
| GraphDB 보강 | 구조화 검증 스크립트 PASS, confirmed fact에는 evidence 필수 | candidate fact를 확정 근거로 사용 |

## 2. 실행한 테스트

### 2.1 자동 평가 도구 보강

- `scripts/eval_chatbot_model_index_matrix.py`를 현재 코드베이스에 편입했다.
- `--review-types`, `--difficulty` 다중값 필터를 지원하도록 보강했다.
- pivot matrix ID를 계획서 기준(`default__vllm_gemma4`, `default__sglang_gpt_oss_20b` 등)으로 안정화했다.
- `--retrieval-only`에서도 GraphDB source chunk를 병합해 현재 앱 검색 경로에 더 가깝게 평가하도록 수정했다.
- BM25와 Chroma 산출물 존재 여부를 실행 초기에 검증하도록 했다.

검증:

```bash
.venv/bin/pytest tests/test_eval_chatbot_model_index_matrix.py -q
# 10 passed
```

### 2.2 Retrieval-only Smoke Matrix

명령:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
GRAPH_ENABLED=true GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite \
.venv/bin/python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gemma4_vllm,gpt_oss_sglang \
  --index-modes default,v2_only,v1_v2_combined \
  --review-types auto \
  --difficulty smoke \
  --retrieval-only \
  --no-switch \
  --label current_loop1_smoke_retrieval \
  --top-k 8
```

결과:

- 48/48 PASS
- 산출물: `reports/chatbot_model_index_matrix/matrix_current_loop1_smoke_retrieval.*`

### 2.3 GPT-OSS Full-answer Smoke

현재 서버 상태에서 vLLM/Gemma4는 내려가 있고 SGLang/GPT-OSS만 응답했다. 모델 서버 전환은 수행하지 않고 GPT-OSS만 평가했다.

초기 결과:

- `current_loop1_smoke_gpt_oss`: 18/24 PASS
- 실패:
  - `qa2_smoke_001_hira_known_code`: AA157 답변에서 `초진 진찰료` 상위 항목명 누락
  - `qa2_smoke_005_casebook_disclosure`: 답변은 `보험금 지급 거부`로 의미상 맞지만 평가셋이 `거절/제한`만 허용

개선:

- 심평원 코드 질의에 대해 코드 행, 상위 항목 후보, 점수를 구조화 컨텍스트로 추가했다.
- 상담사례집 알릴 의무 문항의 `required_any`에 `보험금 지급 거부`, `지급되지`, `거부`를 추가해 의미상 동등한 안전 답변을 오답 처리하지 않도록 보정했다.

재검증:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
GRAPH_ENABLED=true GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite \
.venv/bin/python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gpt_oss_sglang \
  --index-modes default,v2_only,v1_v2_combined \
  --review-types auto \
  --difficulty smoke \
  --no-switch \
  --label current_loop4_smoke_gpt_oss \
  --top-k 8 \
  --max-tokens 700 \
  --temperature 0.0
```

결과:

- 24/24 PASS
- 산출물: `reports/chatbot_model_index_matrix/matrix_current_loop4_smoke_gpt_oss.*`

### 2.4 보험금 계산 집중 테스트

명령:

```bash
.venv/bin/pytest \
  tests/test_claim_calculation_pipeline.py \
  tests/test_claim_planner.py \
  tests/test_claim_code_sandbox.py \
  tests/test_claim_standard_matcher.py \
  tests/test_claim_basis_selector.py -q
```

결과:

- 23/23 PASS
- 확인한 항목:
  - 도수치료 150,000원 통원 시 지급예상액 105,000원, 공제액 45,000원
  - 금액 포맷(`150000`, `150,000`, `150,000원`) 파싱
  - 다중 표준코드 후보 보류 및 candidates 반환
  - not covered / needs more info 검토 플래그
  - 지급액/공제액 총청구액 초과 검토 플래그
  - AST sandbox 보안 회귀

### 2.5 GraphDB 무결성

명령:

```bash
.venv/bin/python scripts/check_graph_index.py
```

결과:

- Q1/Q2 hard query fixture PASS
- Detailed Integrity Check PASS

## 3. 발견한 결점과 조치

### 결점 1. 심평원 코드표 상위 항목 누락

- 원인: 검색 결과 p.101에는 `AA157 (5) 상급종합병원 255.79` 행이 직접 보이지만, 상위 항목인 `초진 진찰료`는 p.80 산정지침에 분산되어 있었다.
- 영향: 모델이 세부 분류만 항목명으로 답해 평가와 실무 의미가 모두 불완전해진다.
- 조치: RAG 프롬프트 앞에 `[구조화 데이터 — 심평원 코드 직접 근거]`를 추가하고, 코드 주변 snippet과 상위 항목 후보를 명시했다.
- 재검증: `qa2_smoke_001_hira_known_code`가 `default`, `v2_only`, `v1_v2_combined`에서 모두 PASS.

### 결점 2. 평가셋 동의어 범위 협소

- 원인: 알릴 의무 위반 불이익 문항에서 `보험금 지급 거절`, `지급 제한`만 허용하고 `보험금 지급 거부`를 허용하지 않았다.
- 영향: 의미상 올바른 답변이 실패로 기록되어 실제 품질 결함과 평가 기준 결함이 섞인다.
- 조치: `required_any`에 동등 표현을 추가했다.
- 재검증: `qa2_smoke_005_casebook_disclosure` PASS.

## 4. 미수행 및 다음 루프

- vLLM/Gemma4 full-answer 평가는 현재 endpoint가 내려가 있어 수행하지 않았다. 사용자 승인 없이 모델 전환은 하지 않았다.
- Stage 2 전체 63개 auto full-answer 평가는 아직 수행하지 않았다.
- 보험금 계산은 자동 단위/통합 테스트는 통과했지만, 실제 Streamlit UI에서 후보 선택 후 자동 재계산까지의 브라우저 smoke는 다음 루프에서 확인해야 한다.
- GraphDB 경고로 `자사_SOL건강_v2_manual_ch_011756` source chunk가 일부 Chroma 인덱스에서 누락되는 상황이 관찰되었다. 답변 실패로 이어지지는 않았지만, Graph source chunk와 Chroma chunk ID의 정합성 점검이 필요하다.

## 5. 다음 개선 후보

1. HIRA 대형 표를 SQLite/Parquet row-level lookup으로 분리해 `Q2333`, `R3564` 같은 hard table 질의를 chunk retrieval에 의존하지 않게 한다.
2. Cross-doc 질문은 문서별 최소 coverage를 더 강하게 보장하고, 심평원/약관/자사 약관 코드를 별도 슬롯으로 구성한다.
3. 질문 유형별 index routing을 도입해 약관/HIRA는 `default`, OCR 상담/실무는 `v2_only` 또는 `v1_v2_combined`를 우선 사용한다.
4. 보험금 계산 UI는 잘못된 지급액을 내는 것보다 보류하는 쪽을 우선하도록, candidate-only Graph fact와 다중 표준코드 후보의 blocking 동작을 브라우저 테스트로 고정한다.
