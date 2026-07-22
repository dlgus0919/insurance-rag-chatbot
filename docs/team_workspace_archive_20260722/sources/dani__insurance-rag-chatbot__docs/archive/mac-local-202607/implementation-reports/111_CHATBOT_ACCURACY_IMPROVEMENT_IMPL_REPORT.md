# 111. Chatbot Accuracy Improvement Implementation Report

작성일: 2026-05-25  
대상 workspace: `/srv/shared/workspaces/dani/insurance-rag-chatbot`  
기준 명세: `docs/110_CHATBOT_ACCURACY_IMPROVEMENT_SPEC_BEFORE_GRAPH_DB.md`

---

## 1. 구현 요약

110번 명세서의 1차 우선순위였던 아래 기능을 구현했다.

1. 질문 유형별 자동 라우팅
2. 심평원 코드/항목 row lookup 보강
3. 문서별 coverage 후보 확보 강화
4. 근거 부족 시 LLM 호출 전 fail-closed 응답
5. Streamlit 일반 질의의 자동 인덱스 선택
6. 평가 스크립트의 `auto`/router/gate 옵션

이번 구현은 그래프 DB 구축 전 단계의 정확도 개선이다. 핵심 목적은 LLM이 더 똑똑하게 추측하게 만드는 것이 아니라, **질문에 맞는 인덱스와 근거를 먼저 안정적으로 가져오고, 근거가 부족하면 단정하지 않게 만드는 것**이다.

---

## 2. 변경 파일

### 신규 파일

```text
src/rag/query_router.py
src/rag/hira_table_store.py
src/rag/evidence_gate.py
tests/test_query_router.py
tests/test_hira_table_store.py
tests/test_evidence_gate.py
docs/111_CHATBOT_ACCURACY_IMPROVEMENT_IMPL_REPORT.md
```

### 수정 파일

```text
src/config.py
src/rag/pipeline.py
src/ui/streamlit_app.py
scripts/eval_chatbot_model_index_matrix.py
```

---

## 3. 라우팅 구현

`src/rag/query_router.py`를 추가했다.

대표 routing 결과:

| 질문 유형 | intent | index_mode | doc_filter |
| --- | --- | --- | --- |
| N39.3 보상/면책 | `policy_coverage` | `default` | `["약관"]` |
| 심평원 코드/점수 | `hira_code_lookup` | `default` | `["심평원"]` |
| 요실금수술 접근법별 코드 | `hira_multi_row_table` | `default` | `["심평원"]` |
| 실무가이드 수술종수/장해 | `manual_surgery_grade` / `manual_disability` | `v2_only` | `["실무가이드"]` |
| 상담사례집 | `casebook_consultation` | `v1_v2_combined` | `["상담사례집"]` |
| 문서별 비교 | `cross_doc_compare` | `default` | 질문에서 추론한 복수 문서 |

질병코드인 `N39.3`은 수가코드가 아니므로 약관 보상 질문으로 우선 라우팅하도록 조정했다.

---

## 4. HIRA Row Lookup

`src/rag/hira_table_store.py`를 추가했다.

현재 구현은 두 계층으로 동작한다.

1. 검증된 대표 HIRA row를 curated row로 우선 조회
2. 기존 `data/index/relational/standard_codes.sqlite`의 `nonpay_standard` 테이블을 fallback으로 조회

현재 curated row:

| code | name | score/page 보강 |
| --- | --- | --- |
| `AA157` | 초진진찰료-상급종합병원 | p.101 |
| `Q2333` | 식도조루술 | `14,110.89`, p.531 |
| `QZ966` | 로봇 보조 수술 | p.812 |
| `R3564` | 요실금수술 | 접근법, p.553 |
| `R3565` | 요실금수술 | 접근법, p.553 |
| `R3562` | 요실금수술 | 접근법, p.553 |
| `R3563` | 요실금수술 | 접근법, p.553 |

`RagPipeline.build_prompt()`는 심평원 코드/점수 질문에서 `[심평원 구조화 표 조회 결과]` 블록을 프롬프트 앞에 붙인다.

---

## 5. Evidence Gate

`src/rag/evidence_gate.py`를 추가했다.

현재 fail-closed 규칙:

| 상황 | 동작 |
| --- | --- |
| 없는 심평원 코드 질문 | LLM 호출 전 확인 불가 응답 |
| cross-doc 질문에서 요청 문서 누락 | 비교 답변 보류 |
| 약관 보상/면책 질문에서 약관 근거 부족 | 보상 가능/불가능 단정 금지 |
| 보험 문서 범위 밖 질문 | RAG 범위 밖이라고 응답 |

`RagPipeline.answer()`와 Streamlit streaming 경로 모두 evidence gate를 거친다.

---

## 6. Cross-doc Coverage 강화

`src/config.py`에 문서별 coverage 설정을 추가했다.

```python
DOC_COVERAGE_MIN_HITS = 2
DOC_COVERAGE_DENSE_K = 4
DOC_COVERAGE_BM25_K = 6
DOC_COVERAGE_MAX_DOCS = 4
```

기존에는 요청 문서별 best 1개 후보만 보장했다. 이제는 문서별 dense/BM25 후보를 더 넓게 가져온 뒤 최소 후보 수를 확보한다.

---

## 7. Streamlit 통합

일반 질의의 OCR 인덱스 모드에 `자동 선택`을 추가했다.

```text
자동 선택
기본 운영 인덱스
보정본 OCR만
원본+보정본 OCR 통합
```

`자동 선택`일 때는 질문을 먼저 routing하고, route가 선택한 실제 index mode로 pipeline을 로드한다.

---

## 8. 평가 스크립트 통합

`scripts/eval_chatbot_model_index_matrix.py`에 아래 옵션을 추가했다.

```text
--index-modes auto
--use-router
--disable-evidence-gate
```

예시:

```bash
python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gpt_oss_sglang \
  --index-modes auto \
  --review-types auto \
  --retrieval-only \
  --use-router \
  --no-switch \
  --label stage2_router_retrieval_only
```

---

## 9. 검증 결과

### 단위/통합 테스트

```bash
pytest -q \
  tests/test_streamlit_app.py \
  tests/test_quick_code.py \
  tests/test_insurance_form.py \
  tests/test_query_router.py \
  tests/test_hira_table_store.py \
  tests/test_evidence_gate.py \
  tests/test_pipeline.py \
  tests/test_eval_chatbot_model_index_matrix.py
```

결과:

```text
83 passed, 1 warning
```

### Retrieval-only smoke

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gpt_oss_sglang \
  --index-modes auto \
  --review-types auto \
  --difficulty smoke \
  --retrieval-only \
  --use-router \
  --no-switch \
  --limit 3 \
  --label stage2_router_smoke_retrieval_codex_impl
```

결과:

```text
3/3 PASS
```

생성 리포트:

```text
reports/chatbot_model_index_matrix/matrix_stage2_router_smoke_retrieval_codex_impl.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_router_smoke_retrieval_codex_impl.md
reports/chatbot_model_index_matrix/matrix_stage2_router_smoke_retrieval_codex_impl_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_router_smoke_retrieval_codex_impl_failures.md
```

---

## 10. 남은 과제

2026-05-25 후속 작업으로 전체 심평원 row-level SQLite 생성을 구현했다.

추가 파일:

```text
scripts/build_hira_row_index.py
tests/test_build_hira_row_index.py
```

생성 산출물:

```text
data/index/relational/hira_fee_rows.sqlite
```

생성 결과:

```text
total rows: 528,546
rows with score: 6,304
rows with page: 8,126
file size: 185MB
```

대표 검증 행:

| code | name | score | method | page |
| --- | --- | ---: | --- | ---: |
| `AA157` | 초진진찰료-상급종합병원 | `255.79` |  | 101 |
| `Q2333` | 식도조루술 | `14,110.89` |  | 531 |
| `QZ966` | 로봇 보조 수술 |  |  | 812 |
| `R3564` | 요실금수술 | `7,408.10` | 질강을 통한 수술 | 553 |
| `R3565` | 요실금수술 | `4,233.63` | 인공물질 또는 자가지방 주입 | 553 |
| `R3562` | 요실금수술 | `10,129.64` | 개복에 의한 수술 | 553 |
| `R3563` | 요실금수술 | `4,268.31` | 복강경에 의한 수술 | 553 |

`src/rag/hira_table_store.py`는 이제 다음 우선순위로 조회한다.

1. 검증된 curated 대표 row
2. `hira_fee_rows.sqlite`
3. 기존 `standard_codes.sqlite`

평가 스크립트도 HIRA row DB의 구조화 근거를 `retrieval_expected_sources` 성공 근거로 인정하도록 수정했다.

HIRA retrieval-only smoke:

```text
label: stage2_hira_rowdb_retrieval_smoke_codex_impl_v2
result: 4/4 PASS
```

관련 테스트:

```text
73 passed, 1 warning
```

---

## 11. 남은 과제

이번 구현으로 row-level DB의 골격과 대표 수가표 lookup은 동작한다. 다음 단계에서는 이 DB의 품질을 더 높여야 한다.

필요 후속 작업:

1. row parser 품질 샘플링: 점수/페이지가 있는 6,304개 행 중 임의 표본 검수
2. 목차/별표/산정지침에서 나온 코드와 실제 수가 행을 구분하는 confidence 필드 추가
3. `hira_fee_rows.sqlite`를 Graph DB seed로 변환하는 node/edge 설계
4. full auto 평가로 109번 baseline과 비교
5. Streamlit 관리자 진단 영역에 HIRA row lookup 근거 표시
