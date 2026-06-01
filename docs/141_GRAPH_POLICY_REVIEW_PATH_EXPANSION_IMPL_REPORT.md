# 141. Graph Policy Review Path Expansion Implementation Report

작성일: 2026-05-28
대상 프로젝트: `insurance-rag-chatbot`

## 1. 구현 범위

`141_GRAPH_POLICY_REVIEW_PATH_EXPANSION_SPEC v2`에 따라 GraphRAG를 수술/수가/별표 중심 구조에서 문서 기반 보상 판단 그래프 + 세션 검토 경로 구조로 확장했다.

핵심 구현 범위:

- GraphDB 스키마에 판단 개념 노드/엣지 추가
- processed `chunks.jsonl` 기반 정책 조항/사례/조건/증빙/검토 조치 추출기 추가
- 플래너에 진단코드/합병증/조건/증빙/세대/입원통원 시그널 추가
- 리트리버에 `review path` 조립 로직 추가
- 보험금 계산 파이프라인에 합병증 review path 연동
- API/UI payload에 review path, session assertion, required evidence 노출

## 2. 변경 파일

- `src/graph/schema.py`
- `src/graph/extractors.py`
- `src/graph/build.py`
- `src/graph/query_planner.py`
- `src/graph/retriever.py`
- `src/graph/context.py`
- `src/claim_calculation/models.py`
- `src/claim_calculation/pipeline.py`
- `src/api/rag_service.py`
- `src/ui/chat_store.py`
- `src/ui/streamlit_app.py`
- `tests/test_graph_policy_clause_extractor.py`
- `tests/test_graph_case_example_extractor.py`
- `tests/test_graph_review_path_planner.py`
- `tests/test_graph_review_path_retriever.py`
- `tests/test_claim_complication_review.py`

## 3. 핵심 변경 내용

### 3.1 Graph 스키마 확장

추가 노드 타입:

- `PolicyClause`
- `CaseExample`
- `ClaimCondition`
- `DecisionConcept`
- `EvidenceRequirement`
- `DiagnosisCode`
- `ComplicationConcept`
- `PolicyGeneration`
- `VisitContext`
- `FacilityContext`
- `ReviewAction`

추가 엣지 타입:

- `HAS_TOPIC`
- `APPLIES_WHEN`
- `HAS_DECISION`
- `REQUIRES_EVIDENCE`
- `RELATES_TO_DIAGNOSIS`
- `RELATES_TO_COMPLICATION`
- `APPLIES_TO_GENERATION`
- `APPLIES_TO_VISIT`
- `APPLIES_TO_FACILITY`
- `HAS_REVIEW_ACTION`
- `SIMILAR_CASE_FOR`

명시적으로 의학 인과 엣지는 추가하지 않았다.

### 3.2 문서 기반 판단 그래프 추출기 추가

`PolicyReviewExtractor`를 추가했다.

동작:

- 약관/표준약관/자사 약관/상담사례집/실무가이드/심평원 chunk 중 검토 가치가 있는 텍스트만 선택
- `PolicyClause`, `CaseExample` 노드 생성
- canonical set 기반으로 `ComplicationConcept`, `ClaimCondition`, `DecisionConcept`, `EvidenceRequirement`, `ReviewAction` 연결
- 문서에 직접 등장한 `DiagnosisCode`만 생성/연결
- `CoverageItem` 확장 토픽(`실손`, `합병증 치료`, `미용 목적 치료`, `상급병실료 차액`, `건강보험 미적용 특례`) 연결

### 3.3 Planner / Retriever 확장

`GraphQueryPlan` 확장 필드:

- `diagnosis_codes`
- `coverage_topics`
- `conditions`
- `complication_asserted`
- `treatment_purpose`
- `evidence_tags`
- `policy_generation`
- `visit_type`
- `facility_type`

신규 intent:

- `complication_policy_lookup`
- `diagnosis_policy_lookup`
- `claim_condition_lookup`
- `case_example_lookup`
- `session_claim_path_review`

`GraphRetriever` 확장:

- `SessionAssertion`
- `GraphPathStep`
- `GraphReviewPath`
- 문서 기반 검토 경로 수집
- `required_evidence`, `review_actions`, `source_chunk_ids` 집계

### 3.4 보험금 계산 파이프라인 연동

`ClaimCaseContext`에 다음 필드를 추가했다.

- `complication_asserted`
- `treatment_purpose`
- `evidence_tags`
- `facility_type`
- `facility_grade`

추가 규칙:

- 합병증/후유증/부작용 상황이면 Graph review path를 강제로 조회
- review path가 요구하는 증빙이 없으면 `review_required=True`
- review path에 면책 성격의 확정 조항이 직접 연결되면 보수적으로 `payable=0`, `deductible=claimed` 처리
- review action을 계산 결과의 `review_reasons`로 반영

### 3.5 API / UI 반영

API payload에 추가:

- `graph_review_paths`
- `session_assertions`
- `required_evidence`
- `review_actions`

Streamlit 렌더링 보강:

- 기존 구조화 근거 위에 `구조화 검토 경로` 섹션 추가

## 4. 검증

### 4.1 문법/임포트 검증

실행:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex_pycache \
/Users/june_kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m py_compile \
  src/graph/schema.py \
  src/graph/extractors.py \
  src/graph/build.py \
  src/graph/query_planner.py \
  src/graph/retriever.py \
  src/graph/context.py \
  src/claim_calculation/models.py \
  src/claim_calculation/pipeline.py \
  src/api/rag_service.py \
  src/ui/chat_store.py \
  src/ui/streamlit_app.py \
  tests/test_graph_policy_clause_extractor.py \
  tests/test_graph_case_example_extractor.py \
  tests/test_graph_review_path_planner.py \
  tests/test_graph_review_path_retriever.py \
  tests/test_claim_complication_review.py
```

결과:

- 통과

### 4.2 핵심 import 검증

실행:

```bash
PYTHONPATH=. /Users/june_kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -c "from src.graph.extractors import PolicyReviewExtractor; from src.graph.query_planner import GraphQueryPlanner; from src.graph.retriever import GraphRetriever; from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput; print('imports ok')"
```

결과:

- `imports ok`

### 4.3 수동 런타임 시나리오 검증

검증 1: 합병증 질의 -> review path 생성

- 더미 약관 chunk: `미용 목적 수술 후 합병증 치료는 보상하지 않는다`
- 결과: `complication_review` path 생성, `세부내역서`, `진단서` 요구 확인

검증 2: 합병증 claim calculation 연동

- `complication_asserted=True`
- 더미 약관 chunk에 면책 성격 조항 연결
- 결과:
  - `payable_amount = 0`
  - `deductible = 100000`
  - `requires_review = True`

검증 3: 진단코드 review path 생성

- 더미 약관 chunk에 `N39.3` 직접 기재
- 결과:
  - `diagnosis_review` path 생성
  - `required_evidence = ['세부내역서', '진단서']`

## 5. 남은 제약 / 위험

- 현재 로컬 워크스페이스에는 `pytest` 실행 환경이 없어, 신규 pytest 파일 전체 실행은 수행하지 못했다.
- `PolicyReviewExtractor`는 v1에서 chunk 기반 heuristic extractor다. 조문/사례 분리 granularity는 문서별 OCR/section 품질에 영향을 받는다.
- 합병증 review path는 의학 인과가 아니라 문서 기반 검토 경로다. 질환-합병증 일반지식은 여전히 도입하지 않았다.
- 면책 보수 처리 로직은 `review path`에서 직접 exclusion polarity를 찾은 경우에만 적용한다.

## 6. 자기 점검

- [x] 구현이 명세 범위 안에서만 확장되었는가
- [x] 의학 일반지식/외부 ontology를 도입하지 않았는가
- [x] 세션 주장 사실을 전역 GraphDB에 저장하지 않았는가
- [x] 문법/임포트/핵심 시나리오 검증을 수행했는가
- [x] 임시 디버그 코드/출력물을 저장소에 남기지 않았는가
