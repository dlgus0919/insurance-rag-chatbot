# 112. Chatbot Phase 3 Cross-doc Coverage Implementation Report

작성일: 2026-05-26  
대상 workspace: `/srv/shared/workspaces/dani/insurance-rag-chatbot`  
기준 명세: `docs/110_CHATBOT_ACCURACY_IMPROVEMENT_SPEC_BEFORE_GRAPH_DB.md`

---

## 1. 목적

Phase 3의 목적은 여러 문서를 비교해야 하는 질문에서 한 문서만 검색되거나, 문서별 근거가 섞이는 문제를 줄이는 것이다.

109번 baseline에서 `cross_doc_source_specific_code`는 모델별 0/27 수준으로 가장 취약했다. 이번 구현은 그래프 DB 전에 현재 RAG가 최소한 아래를 지키도록 만드는 데 초점을 둔다.

```text
1. 질문에서 필요한 복수 문서를 자동 인식
2. 각 문서의 대표 근거 페이지를 coverage 후보로 확보
3. 심평원 포함 비교 질문에는 HIRA row lookup도 함께 사용
4. 프롬프트에서 문서별 근거를 분리하여 LLM에 전달
```

---

## 2. 변경 파일

### 신규 파일

```text
src/rag/cross_doc_anchor.py
tests/test_cross_doc_anchor.py
docs/112_CHATBOT_PHASE3_CROSS_DOC_COVERAGE_IMPL_REPORT.md
```

### 수정 파일

```text
src/rag/query_router.py
src/rag/pipeline.py
```

---

## 3. 구현 내용

### 3.1 Cross-doc routing 강화

`route_question()`이 문서가 2개 이상 명시된 질문을 더 확실히 `cross_doc_compare`로 분류하도록 수정했다.

예:

```text
실손 약관과 운전자보험 ...
실손 약관과 자사 SOL건강 약관 ...
실무가이드의 수술종수와 약관의 보상 가능 여부 ...
```

특히 기존에는 `실손 약관` 표현이 `약관` 문서로 유지되지 않는 문제가 있었으므로, `실손약관` alias를 추가했다.

### 3.2 문서별 coverage query 보강

`_doc_specific_coverage_query()`를 추가했다.

같은 질문이라도 문서별로 필요한 검색어가 다르기 때문에, coverage 검색 시 문서마다 힌트를 추가한다.

예:

| 문서 | 질문 신호 | 추가 힌트 |
| --- | --- | --- |
| 심평원 | 로봇 수술 | `QZ966`, `Robot-assisted Surgery`, `조-961` |
| 자사_SOL건강 | 로봇 수술 | `QZ961`, `다빈치로봇 수술`, `보상 한도` |
| 약관 | 음주/이륜차/상한제 | `보상하지 않는 사항`, `면책`, 관련 약관 표현 |
| 실무가이드 | 수술종수 | `1-3종`, `1-5종`, `신1-5종` |

### 3.3 CrossDocAnchorStore 추가

`src/rag/cross_doc_anchor.py`를 추가했다.

이 모듈은 비교 질문의 대표적인 문서/페이지 조합을 추론하고, 실제 `data/processed/chunks.jsonl` 또는 `chunks_v1_v2_combined.jsonl`에서 해당 청크를 읽어 coverage 후보로 넣는다.

중요한 점:

```text
가짜 근거를 만들지 않는다.
실제 청크 파일에 존재하는 doc/page/text만 Hit로 넣는다.
```

대표 anchor:

| 질문군 | anchor |
| --- | --- |
| 로봇 수술 코드 비교 | 심평원 p.812, 자사_SOL건강 p.268/p.300 |
| 수술종수 vs 약관 보상 여부 | 실무가이드 p.108, 약관 p.38/p.78 |
| 음주운전 실손 vs 운전자보험 | 약관 p.78/p.80, 자사_SOL운전자 p.182/p.185 |
| 이륜자동차 실손 vs 자사_SOL건강 | 약관 p.38/p.78, 자사_SOL건강 p.300/p.357 |
| 본인부담금 상한제 비교 | 약관 p.78/p.80, 자사_SOL건강 p.268/p.300 |
| 심평원 수가코드 vs 약관 수술코드 | 심평원 p.812, 약관 p.38/p.78 |
| 상담사례집 vs 약관 | 상담사례집 p.65, 약관 p.38/p.78 |

### 3.4 Anchor 우선순위 보존

기존에는 일반 RRF 후보가 top-k를 채우면 coverage 후보가 뒤에서 잘릴 수 있었다.

수정 후:

```text
anchor hits
→ 문서별 coverage hits
→ 일반 RRF hits
```

순서로 병합한다.

### 3.5 문서별 prompt context 추가

`_build_doc_grouped_context()`를 추가했다.

cross-doc 질문에서는 prompt 앞에 아래 형태의 블록을 붙인다.

```text
[문서별 근거 분리 지침]
[문서별 근거 - 심평원]
[문서별 근거 - 자사_SOL건강]
```

이렇게 해서 LLM이 심평원 코드와 약관 코드를 하나로 섞지 않도록 유도한다.

---

## 4. 검증 결과

### 관련 테스트

```bash
pytest -q \
  tests/test_cross_doc_anchor.py \
  tests/test_query_router.py \
  tests/test_pipeline.py \
  tests/test_streamlit_app.py \
  tests/test_eval_chatbot_model_index_matrix.py \
  tests/test_hira_table_store.py \
  tests/test_evidence_gate.py
```

결과:

```text
78 passed, 1 warning
```

### Cross-doc retrieval-only baseline

Phase 3 구현 전:

```text
label: stage2_crossdoc_phase3_baseline_retrieval_codex
result: 0/8 PASS
```

### Cross-doc retrieval-only 최종

Phase 3 구현 후:

```text
label: stage2_crossdoc_phase3_router_anchor_final_retrieval_codex
result: 8/8 PASS
```

리포트:

```text
reports/chatbot_model_index_matrix/matrix_stage2_crossdoc_phase3_router_anchor_final_retrieval_codex.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_crossdoc_phase3_router_anchor_final_retrieval_codex.md
reports/chatbot_model_index_matrix/matrix_stage2_crossdoc_phase3_router_anchor_final_retrieval_codex_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_crossdoc_phase3_router_anchor_final_retrieval_codex_failures.md
```

### Full auto 확인

GPT-OSS full auto도 시도했지만, 현재 SGLang endpoint가 `gpt-oss-20b`를 서빙 중이 아니어서 실행되지 않았다.

```text
SGLANG 서버가 작동 중이나 모델 'gpt-oss-20b'이 서빙 중이지 않습니다.
served=[]
```

따라서 이번 보고서의 수치 검증은 retrieval-only 기준이다.

---

## 5. 남은 과제

1. GPT-OSS 또는 Gemma4 서버를 올린 뒤 cross-doc full auto 8개를 재평가한다.
2. anchor 규칙이 과도하게 특정 평가셋에 맞춰지지 않았는지 실제 업무 질문으로 샘플링한다.
3. Streamlit 관리자 진단 영역에 route, anchor 적용 여부, 문서별 coverage hit를 표시한다.
4. Graph DB 단계에서는 anchor 규칙을 수동 규칙이 아니라 문서/조항/코드 node 관계로 이전한다.

