# 113. 챗봇 답변 정확도 개선 Phase 4/5 구현 보고서

작성일: 2026-05-26
작업 경로: `/srv/shared/workspaces/dani/insurance-rag-chatbot`

## 1. 작업 목적

110번 개발 명세서의 후속 단계로, Phase 4와 Phase 5를 구현했다.

- Phase 4: 근거가 부족한 고위험 질문은 LLM 호출 전에 안전하게 차단한다.
- Phase 5: 자동 평가와 관리자 진단 화면에서 라우팅, 인덱스 선택, 근거 검사 결과를 추적할 수 있게 만든다.

이 작업의 핵심은 “모델이 그럴듯하게 답하는 것”보다 “검색/구조화 근거가 확인된 범위에서만 답하는 것”을 우선하는 것이다.

## 2. Phase 4: Evidence Gate 강화

수정 파일:

- `src/rag/evidence_gate.py`
- `src/rag/pipeline.py`
- `tests/test_evidence_gate.py`

### 2.1 추가된 차단 조건

다음 질문 유형은 근거가 약하면 답변 생성을 막는다.

| 유형 | 의미 | 처리 |
| --- | --- | --- |
| 문서 밖 질문 | 주식, 날씨, 맛집 등 보험 문서 범위 밖 질문 | 보험 문서 근거로 답변할 수 없다고 안내 |
| 근거 없는 답변 유도 | “근거가 없어도”, “출처 없이”, “문서에 없는 신상품” 등 | 임의 생성 금지 |
| 가짜 코드 유도 | 질문에 나온 코드가 검색/구조화 근거에서 확인되지 않음 | 해당 코드를 확인하지 못했다고 안내 |
| 문서별 비교 근거 부족 | 심평원과 약관처럼 여러 문서 비교가 필요한데 일부 문서가 없음 | 비교 답변 보류 |
| 심평원 row lookup 실패 | 수가코드, 점수, 항목명 질문에서 구조화 표 결과가 없음 | 심평원 수가표 행을 확인하지 못했다고 안내 |
| 약관 보상 판단 근거 부족 | 보상/면책/지급 여부 판단에 약관 근거가 없음 | 보상 가능 여부 단정 금지 |

### 2.2 구조화 근거와 일반 청크 근거의 병합 판단

심평원 표처럼 row 단위 DB에서 찾은 근거는 일반 검색 청크와 별도로 들어온다. 따라서 evidence gate는 이제 다음 두 근거를 함께 본다.

- 일반 RAG 검색 청크
- `hira_fee_rows.sqlite` 기반 구조화 row lookup 결과

예를 들어 심평원 문서는 구조화 row lookup에서 확인되고, 자사 약관은 일반 청크에서 확인된 경우에도 “문서별 비교에 필요한 근거가 있다”고 판단할 수 있게 했다.

### 2.3 Pipeline DebugInfo 연동

`src/rag/pipeline.py`의 `DebugInfo`에 다음 필드를 추가했다.

- `route_intent`
- `route_index_mode`
- `route_doc_filter`
- `evidence_gate_ok`
- `evidence_gate_reason`

이제 파이프라인 답변 결과를 보면, 해당 질문이 어떤 의도로 라우팅되었고 근거 검사가 왜 통과/차단되었는지 추적할 수 있다.

## 3. Phase 5: 자동 평가/관리자 진단 개선

수정 파일:

- `scripts/eval_chatbot_model_index_matrix.py`
- `src/ui/streamlit_app.py`

### 3.1 자동 평가 JSONL에 라우팅/근거 검사 정보 저장

자동 평가 결과 `matrix_<label>.jsonl`의 각 케이스에 다음 필드가 추가된다.

- `route_intent`: 질문 유형 라우팅 결과
- `route_index_mode`: 실제 사용한 인덱스 모드
- `route_doc_filter`: 문서 필터
- `evidence_gate_ok`: 근거 검사 통과 여부
- `evidence_gate_reason`: 근거 검사 통과/차단 사유

이제 단순히 PASS/FAIL만 보는 것이 아니라, 실패가 검색 문제인지, 라우팅 문제인지, evidence gate 차단인지 구분할 수 있다.

### 3.2 자동 평가 Markdown 요약 추가

`matrix_<label>.md`에 “라우팅 / 근거 검사 요약” 섹션을 추가했다.

이 섹션은 다음을 보여준다.

- 라우팅 intent별 실행 수
- Evidence Gate PASS 수
- Evidence Gate FAIL-CLOSED 수
- 차단 사유별 횟수

즉, 평가 결과에서 “어떤 유형의 질문이 자주 차단되는지”와 “차단이 의도된 안전 동작인지”를 더 쉽게 볼 수 있다.

### 3.3 Streamlit 관리자 진단 화면 개선

관리자 계정에서 마지막 질문의 RAG 진단 도구를 열면 다음 정보가 추가로 표시된다.

- 라우팅 intent
- 실제 선택된 인덱스 모드
- 적용된 문서 필터
- Evidence Gate 통과/차단 여부
- Evidence Gate 사유

이 정보는 답변 정확도를 디버깅할 때 중요하다. 예를 들어 사용자가 약관 질문을 했는데 심평원 인덱스로 라우팅되었다면, 관리자 화면에서 즉시 확인할 수 있다.

## 4. 테스트 결과

### 4.1 단위/회귀 테스트

실행 명령:

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
source .venv/bin/activate
pytest -q \
  tests/test_evidence_gate.py \
  tests/test_pipeline.py \
  tests/test_streamlit_app.py \
  tests/test_eval_chatbot_model_index_matrix.py \
  tests/test_query_router.py \
  tests/test_hira_table_store.py \
  tests/test_cross_doc_anchor.py
```

결과:

```text
81 passed, 1 warning in 0.65s
```

경고는 `passlib` 내부의 Python 3.13 예정 deprecation 경고이며, 이번 구현과 직접 관련된 실패는 아니다.

### 4.2 Retrieval-only 평가 스모크

모델 생성 없이 검색/라우팅/리포트 생성만 검증했다.

실행 명령:

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
source .venv/bin/activate
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3 \
HF_MODEL_DOWNLOAD=false \
HF_HUB_OFFLINE=1 \
python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gemma4_vllm \
  --index-modes auto \
  --use-router \
  --retrieval-only \
  --no-switch \
  --limit 2 \
  --label phase45_retrieval_smoke_codex \
  --report-dir reports/eval
```

결과:

```text
[gemma4_vllm | auto] (01/2) PASS lm_001_robot_code_source_split
[gemma4_vllm | auto] (02/2) PASS lm_002_hira_esophagostomy_code_score
```

생성 파일:

- `reports/eval/matrix_phase45_retrieval_smoke_codex.jsonl`
- `reports/eval/matrix_phase45_retrieval_smoke_codex.md`
- `reports/eval/matrix_phase45_retrieval_smoke_codex_pivot.csv`
- `reports/eval/matrix_phase45_retrieval_smoke_codex_failures.md`

확인된 라우팅 필드:

| 케이스 | route_intent | route_index_mode | route_doc_filter |
| --- | --- | --- | --- |
| `lm_001_robot_code_source_split` | `cross_doc_compare` | `default` | `심평원`, `자사_SOL건강` |
| `lm_002_hira_esophagostomy_code_score` | `hira_code_lookup` | `default` | `심평원` |

`retrieval-only` 모드에서는 LLM 답변 생성 전 evidence gate가 실행되지 않으므로 `evidence_gate_ok`와 `evidence_gate_reason`은 `null`로 기록되는 것이 정상이다.

## 5. 구현 후 기대 효과

### 5.1 환각 답변 감소

문서에 없는 코드, 신상품, 특약, 보상 여부를 물었을 때 모델이 임의로 답변할 가능성을 줄였다.

### 5.2 심평원 표 답변 안정화

수가코드/점수/항목명 질문은 구조화 row lookup 근거를 우선 확인한다. 근거가 없으면 답변을 만들지 않고 안전하게 차단한다.

### 5.3 비교 질문 추적성 향상

심평원, 약관, 실무가이드, 상담사례집 등 여러 문서를 비교하는 질문에서 어떤 문서 근거가 빠졌는지 확인할 수 있다.

### 5.4 평가 리포트 해석력 향상

평가 결과가 FAIL일 때 다음처럼 원인을 나눠 볼 수 있다.

- 검색이 기대 출처를 못 찾은 문제
- 라우팅이 잘못된 문제
- 구조화 lookup이 실패한 문제
- evidence gate가 의도적으로 답변을 차단한 문제
- 모델 생성 품질 문제

## 6. 남은 확인 사항

이번 단계는 단위 테스트와 평가 스크립트 구조 검증까지 완료했다. 실제 Gemma/GPT 모델을 사용하는 전체 QA 매트릭스 재실행은 현재 모델 서버 상태에 따라 별도 실행하면 된다.

권장 다음 실행:

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
source .venv/bin/activate
python scripts/eval_chatbot_model_index_matrix.py \
  --cases data/eval/stage2_qa_cases.jsonl \
  --models gemma4_vllm \
  --index-modes auto \
  --use-router \
  --label phase45_gemma_auto
```

전체 모델/인덱스 매트릭스를 돌릴 때는 Gemma vLLM 서버와 GPT/SGLang 서버가 모두 정상 응답하는지 먼저 확인해야 한다.

## 7. 변경 파일 요약

| 파일 | 변경 내용 |
| --- | --- |
| `src/rag/evidence_gate.py` | 근거 없는 답변 유도, 심평원 lookup 실패, 문서별 비교 누락 차단 강화 |
| `src/rag/pipeline.py` | DebugInfo에 라우팅/evidence gate 필드 추가 |
| `src/ui/streamlit_app.py` | 관리자 진단 도구와 감사 로그에 라우팅/evidence gate 정보 추가 |
| `scripts/eval_chatbot_model_index_matrix.py` | 평가 JSONL/Markdown에 라우팅/evidence gate 요약 추가 |
| `tests/test_evidence_gate.py` | Phase 4 차단 조건 및 구조화 근거 테스트 추가 |
