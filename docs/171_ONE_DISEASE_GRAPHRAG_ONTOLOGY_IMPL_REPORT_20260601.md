# 171. One Disease GraphRAG Ontology Implementation Report

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`
대상 workspace: `/srv/shared/projects/insurance-rag-chatbot`

---

## 1. 구현 요약

170번 계획에 따라 손해보험 보상 실무의 `하나의 질병` 개념을 GraphRAG ontology에 단계적으로 반영했다.

이번 구현은 의학 일반지식 그래프를 만들지 않는다. 대신 원문 약관에서 직접 확인되는 보상 판단 단위를 구조화한다.

핵심 구현:

- `하나의 질병`, `하나의 상해`, `하나의 통원`, `하나의 입원`, `하나의 질병수술`, `하나의 후유장해 지급한도`를 `ClaimUnitConcept`로 추가
- `DiseaseGroupingRule`, `DiseaseRelationCriterion`, `TreatmentEpisodeContext` 추가
- `PolicyClause -> ClaimUnitConcept -> DiseaseGroupingRule -> Criterion/Context/Evidence/ReviewAction` 경로 생성
- 질문 또는 보험금 계산 context에서 주장된 동일 질병/반복 치료/합병증/새 질병 병행 치료를 session assertion으로만 처리
- 전역 GraphDB에 질병 인과 edge를 생성하지 않음
- 보험금 계산 결과에 `graph_review_paths`, `session_assertions`를 API payload로 노출
- 프론트엔드 보험금 계산 결과에도 구조화 검토 경로 표시

---

## 2. 단계별 작업

### Phase 1. Evidence inventory

추가 파일:

- `scripts/inventory_one_disease_policy_clauses.py`
- `tests/test_one_disease_policy_inventory.py`

산출물:

- `reports/graph/one_disease_policy_clause_inventory.csv`
- `reports/graph/one_disease_policy_clause_inventory.md`

결과:

- GraphDB의 one-disease 관련 `PolicyClause` 10건 확인
- 문서별 분포:
  - `약관`: 2
  - `자사_SOL건강`: 6
  - `자사_SOL운전자`: 1
  - `표준약관`: 1

170번 계획 문서의 기존 8건 기준은 실제 inventory 결과에 맞춰 10건으로 보정했다.

### Phase 2. Schema extension

수정 파일:

- `src/graph/schema.py`

추가 NodeType:

- `ClaimUnitConcept`
- `DiseaseGroupingRule`
- `DiseaseRelationCriterion`
- `TreatmentEpisodeContext`

추가 EdgeType:

- `DEFINES_CLAIM_UNIT`
- `HAS_GROUPING_RULE`
- `HAS_RELATION_CRITERION`
- `APPLIES_TO_CLAIM_UNIT`
- `APPLIES_TO_TREATMENT_CONTEXT`
- `LIMITS_BY_CLAIM_UNIT`
- `REQUIRES_GROUPING_REVIEW`
- `REQUIRES_GROUPING_EVIDENCE`

### Phase 3. Extractor

수정 파일:

- `src/graph/extractors.py`

추가 테스트:

- `tests/test_one_disease_policy_extractor.py`

구현 내용:

- canonical claim unit, grouping rule, relation criterion, treatment context를 deterministic seed로 생성
- 원문 조항의 keyword match로만 node/edge 연결
- 새 질병 ontology 자동 생성 금지
- 조항 제목이 부정확해도 excerpt/page 기반으로 연결 가능하도록 기존 `PolicyClause` evidence를 유지

### Phase 4. Planner / Retriever

수정 파일:

- `src/graph/query_planner.py`
- `src/graph/retriever.py`

추가 테스트:

- `tests/test_one_disease_review_path.py`

구현 내용:

- `하나의 질병`, `동일 질병`, `같은 치료 목적`, `반복 치료`, `재입원`, `새로 발견된 질병` 등 질의 신호 감지
- 신규 intent:
  - `one_disease_policy_lookup`
  - `disease_grouping_review`
  - `recurrent_treatment_review`
  - `claim_unit_limit_review`
- 신규 review path:
  - `one_disease_review`
  - `disease_grouping_review`
  - `claim_unit_limit_review`
  - `same_disease_surgery_review`
  - `recurrent_treatment_review`
- 기본 status는 `review_required`
- 외부 의학 인과를 근거로 `confirmed`를 만들지 않음

### Phase 5. Claim calculation / API / UI

수정 파일:

- `src/claim_calculation/models.py`
- `src/claim_calculation/pipeline.py`
- `src/api/schemas/claim.py`
- `src/api/rag_service.py`
- `frontend/js/pages/chat.js`

추가/수정 테스트:

- `tests/test_claim_complication_review.py`
- `tests/test_api_claim_calculation.py`
- `tests/test_api_rag_service_payload.py`

구현 내용:

- `ClaimCaseContext`에 동일 질병/같은 치료 목적/반복 치료/새 질병 병행 치료 flag 추가
- 계산 파이프라인이 `GraphRetriever`의 one-disease review path를 결과 payload에 포함
- 보험금 계산 결과에서 동일 질병 여부를 자동 확정하지 않고 `requires_review=True`로 처리
- 프론트엔드 보험금 계산 화면에 `구조화 검토 경로` 표시
- 사용자가 상황 메모에 `하나의 질병`, `같은 질병`, `합병증`, `반복 치료` 등을 입력하면 프론트엔드가 context flag를 함께 전송

### Phase 6. Evaluation

추가 파일:

- `eval/one_disease_review_paths.jsonl`
- `scripts/eval_one_disease_review_paths.py`

보완 파일:

- `scripts/eval_graph_review_paths.py`

평가 케이스:

1. 같은 질병 반복 통원
2. 당뇨/망막 레이저/합병증 주장
3. 동일 질병 다중 수술비 제한
4. 전환/재개 전후 계속 치료
5. 같은 상해 후유장해 한도

결과:

- one-disease review path evaluation: `5/5 passed`
- 기존 graph review path evaluation: `19/19 passed`

---

## 3. 실제 GraphDB 재빌드 검증

명령:

```bash
.venv/bin/python scripts/build_graph_index.py --rebuild
```

결과:

- GraphDB build finished successfully.
- 신규 node count:
  - `ClaimUnitConcept`: 6
  - `DiseaseGroupingRule`: 9
  - `DiseaseRelationCriterion`: 9
  - `TreatmentEpisodeContext`: 7
- 신규 edge count:
  - `DEFINES_CLAIM_UNIT`: 131
  - `HAS_GROUPING_RULE`: 54
  - `HAS_RELATION_CRITERION`: 55
  - `APPLIES_TO_CLAIM_UNIT`: 22
  - `APPLIES_TO_TREATMENT_CONTEXT`: 39
  - `LIMITS_BY_CLAIM_UNIT`: 39
  - `REQUIRES_GROUPING_REVIEW`: 35
  - `REQUIRES_GROUPING_EVIDENCE`: 8

실제 retriever 확인:

```text
질문: 당뇨 진단 후 합병증 치료를 받았는데 하나의 질병으로 보나요?
path_type: one_disease_review
status: review_required
required_documents: 수술확인서, 진단서, 진료비 세부내역서
review_actions: 수술확인서 요청, 인간 심사 필요, 진단서 요청, 질병/상해 구분 확인
```

---

## 4. 실사용 기준 검토

실사용자가 앱에서 활용할 때 필요한 경로를 기준으로 점검했다.

- 일반 질의: `GraphRetriever`가 one-disease review path를 반환한다.
- 보험금 계산: 동일 질병 관련 context가 계산 결과 payload에 포함된다.
- 프론트엔드: 보험금 계산 결과에 `구조화 검토 경로`가 표시된다.
- API: `graph_review_paths`, `session_assertions`가 JSON 응답에 포함된다.
- 안전성: 당뇨와 망막병증 같은 질병 인과를 전역 GraphDB에 생성하지 않는다.
- 판단 보수성: 동일 질병 여부는 자동 확정하지 않고 review-required로 처리한다.

---

## 5. 보완한 결점

### 결점 1. Inventory 기준 불일치

초기 문서에는 one-disease 관련 조항을 8건으로 적었으나, 실제 inventory 결과는 10건이었다.

조치:

- `docs/170_ONE_DISEASE_GRAPHRAG_ONTOLOGY_EXPANSION_PLAN_20260601.md` 기준을 10건으로 보정했다.

### 결점 2. 전환/재개 계속 치료 케이스에서 generation review path 누락

`eval_one_disease_review_paths.py` 최초 실행 결과, `one_disease_004_conversion_recurrent_treatment`가 `generation_rule_review`를 만들지 못했다.

조치:

- recurrent/continuing treatment plan에서도 generation rule review path를 생성하도록 retriever를 보완했다.
- one-disease path가 clause에 연결된 generation rule을 payload로 전달하도록 수정했다.

### 결점 3. 직접 실행 시 기존 graph eval script import 실패

`scripts/eval_graph_review_paths.py`를 직접 실행하면 `src` import가 실패했다.

조치:

- project root를 `sys.path`에 추가했다.

### 결점 4. 전체 테스트 중 SGLang 모델 discovery 테스트가 로컬 서버 상태에 영향

SGLang 서버가 떠 있는 환경에서는 non-strict offline 모델 discovery 테스트가 endpoint served model에 끌려 실패했다.

조치:

- `OFFLINE_MODE=true`이고 strict mode가 아니면 staged/configured local candidates를 우선 반환하도록 `src/llm/factory.py`를 보완했다.

---

## 6. 검증 결과

실행 검증:

```bash
.venv/bin/python -m pytest -q
```

결과:

```text
507 passed, 3 warnings
```

추가 검증:

```bash
.venv/bin/python scripts/eval_one_disease_review_paths.py
.venv/bin/python scripts/eval_graph_review_paths.py
node --check frontend/js/pages/chat.js
git diff --check
```

결과:

- one-disease review path evaluation: `5/5 passed`
- graph review path evaluation: `19/19 passed`
- frontend JS syntax: pass
- whitespace check: pass

---

## 7. 남은 주의점

- `하나의 질병` 여부 자체는 자동 확정 대상이 아니다. 진단서, 세부내역서, 수술확인서 등 증빙 확인 후 human review가 필요하다.
- 현재 구현은 원문 조항 기반 deterministic keyword extractor다. 향후 조항 제목/조문 번호 품질을 더 정제하면 path 설명 품질이 좋아질 수 있다.
- 외부 의학 ontology를 도입하지 않는다는 제약은 유지해야 한다.
