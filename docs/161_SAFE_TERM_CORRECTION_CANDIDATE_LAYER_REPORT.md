# 161. Safe Term Correction Candidate Layer Report

작성일: 2026-05-31
대상 단계: `156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`의 P3 후속 구현
작업 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 목적

사용자 질의에 포함된 혼용/축약/음차 표현을 바로 확정 정규화하지 않고, **보정 후보와 확인 질문**으로 노출하는 안전 레이어를 추가했다.

예:

```text
엠알아이 비용도 실비로 청구 가능한가요?
```

처리:

- `실비 -> 실손`은 기존 문서 기반 alias로 확정 정규화
- `엠알아이 -> MRI`는 자동 확정하지 않고 `term_correction_candidates`에 보정 후보로만 저장
- 사용자/담당자에게 `"엠알아이" 표현이 "MRI"을 의미하는지 확인해 주세요.` 질문 생성

## 2. 설계 원칙

- LLM이나 fuzzy matching 후보를 곧바로 보상 판단 전제로 사용하지 않는다.
- 확정 가능한 dictionary alias는 `normalized_terms`에만 저장한다.
- 미확정 후보는 `term_correction_candidates`에 저장하고, `clarification_questions`를 반드시 함께 생성한다.
- Graph context에는 “확인 전에는 보상 판단 전제로 삼지 말라”는 지침을 명시한다.
- API/UI/관리자 진단에는 후보를 노출하되, 확정 정규화와 분리해 보여준다.

이번 단계에서는 실제 LLM 호출을 넣지 않았다. 운영 안정성과 재현성을 위해 우선 deterministic safe candidate rule을 적용했고, 향후 LLM은 같은 payload schema에 후보를 제안하는 역할로만 연결할 수 있다.

## 3. 변경 내용

### 3.1 Planner 확장

`GraphQueryPlan` 추가 필드:

```python
term_correction_candidates: list[dict[str, Any]]
```

후보 예시:

```json
{
  "raw": "엠알아이",
  "normalized": "MRI",
  "confidence": 0.72,
  "source": "safe_candidate_rule",
  "reason": "문서 기반 canonical 용어와 유사하지만 자동 확정하지 않는 사용자 입력 표현입니다."
}
```

초기 후보 rule:

- `엠알아이` -> `MRI`
- `엠알에이` -> `MRA`
- `자기공명` -> `자기공명영상진단`
- `도수/충격파` -> `도수치료 또는 체외충격파치료`
- `체충파` -> `체외충격파치료`
- `병실차액` -> `상급병실료 차액`
- `건보 안됨` -> `건강보험 미적용`
- `특약 확인` -> `특약 가입 여부 확인`

### 3.2 Graph context 확장

`build_graph_context()`가 `term_correction_candidates`를 prompt context에 포함한다.

중요 지침:

```text
아래 항목은 자동 확정된 정규화가 아닙니다.
사용자가 의도한 용어인지 확인 질문으로 먼저 제시하고,
확인 전에는 보상 판단의 전제로 삼지 마십시오.
```

### 3.3 API / UI / Admin 진단 연결

API payload:

- `graph_result.plan.term_correction_candidates`
- RAG diagnostics의 `term_correction_candidates`

사용자 채팅 UI:

- `추가 확인 필요` 블록에 `입력 용어 보정 후보` 추가

관리자 RAG 검색 진단:

- `질의 이해/명확화` 패널에 `보정 후보` 추가

### 3.4 평가셋 보강

`eval/graph_review_paths.jsonl`에 1개 케이스 추가:

```text
grp_019_unconfirmed_mri_term_candidate
질문: 엠알아이 비용도 실비로 청구 가능한가요?
```

검증 항목:

- `실비 -> 실손` 확정 정규화
- `엠알아이 -> MRI`는 미확정 보정 후보
- `용어 보정 후보`, `실손 세대`, `방문 구분` 모호 조건 생성
- `엠알아이`, `실손 세대`, `입원/통원` 확인 질문 생성

## 4. 변경 파일

- `src/graph/query_planner.py`
- `src/graph/context.py`
- `src/api/rag_service.py`
- `src/api/routes/chat.py`
- `frontend/js/pages/chat.js`
- `frontend/js/pages/admin.js`
- `scripts/eval_graph_review_paths.py`
- `eval/graph_review_paths.jsonl`
- `tests/test_graph_review_path_planner.py`
- `tests/test_graph_context.py`
- `tests/test_api_rag_service_payload.py`
- `tests/test_api_chat_stream.py`
- `tests/test_api_admin.py`
- `docs/161_SAFE_TERM_CORRECTION_CANDIDATE_LAYER_REPORT.md`

## 5. 검증 결과

관련 테스트:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_graph_review_path_planner.py \
  tests/test_graph_context.py \
  tests/test_api_rag_service_payload.py \
  tests/test_api_chat_stream.py \
  tests/test_api_admin.py \
  tests/test_eval_graph_review_paths.py -q
```

결과:

```text
22 passed, 1 warning
```

Graph review path 평가:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_review_paths.jsonl \
  --output reports/graph_review_paths/eval_graph_review_paths_term_candidates_20260531.jsonl
```

결과:

```text
Graph review path evaluation: 19/19 passed
```

문법 검증:

```bash
node --check frontend/js/pages/chat.js
node --check frontend/js/pages/admin.js
.venv/bin/python -m py_compile \
  src/graph/query_planner.py \
  src/graph/context.py \
  src/api/rag_service.py \
  src/api/routes/chat.py \
  scripts/eval_graph_review_paths.py
```

결과:

```text
pass
```

## 6. Self-review

점검 결과:

- 후보 표현은 `coverage_topics`에 자동 주입하지 않는다.
- 후보 표현은 반드시 확인 질문을 생성한다.
- prompt context와 UI 모두에서 확정 정규화와 미확정 보정 후보를 분리한다.
- 기존 Graph review path 평가셋은 19/19로 통과했다.
- 기존 candidate Graph fact가 확정 답변 재료로 노출되지 않도록 context redaction 테스트도 함께 통과했다.

남은 작업:

- 실제 LLM을 연결할 경우에도 동일 schema에 후보만 넣고, dictionary/Graph alias/retrieval hit 검증 전에는 적용하지 않는 guard가 필요하다.
- 보정 후보를 사용자가 클릭해 확정하는 UI control은 아직 없다.
- 후보 확정 후 재질의 또는 검색 재실행 흐름은 다음 단계에서 구현할 수 있다.
