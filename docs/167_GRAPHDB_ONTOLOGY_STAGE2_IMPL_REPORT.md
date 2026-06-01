# 167. GraphDB Ontology 2차 확장 구현 보고서

작성일: 2026-06-01  
기준 문서: `docs/165_GRAPHDB_ONTOLOGY_STAGE2_EXPANSION_PLAN.md`  
작업 범위: 문서 기반 보험 ontology 2차 rule node 확장

## 1. 구현 요약

165번 계획에 따라 기존 `PolicyClause.properties.rule_types`에 머물던 정책 rule 성격을 독립 graph node와 edge로 승격했다.

추가된 rule node type:

- `ExclusionReason`
- `BenefitLimit`
- `DeductibleRule`
- `RequiredDocument`
- `CoordinationRule`
- `RenewalOrGenerationRule`

추가된 edge type:

- `HAS_EXCLUSION_REASON`
- `HAS_BENEFIT_LIMIT`
- `HAS_DEDUCTIBLE_RULE`
- `REQUIRES_DOCUMENT`
- `HAS_COORDINATION_RULE`
- `HAS_GENERATION_RULE`
- `TRIGGERS_EXCLUSION_REASON`
- `REQUESTS_DOCUMENT`

## 2. 핵심 변경

### 2.1 Graph schema

`src/graph/schema.py`에 6개 rule node와 8개 edge를 추가했다.

기존 `PolicyClause`, `ClaimCondition`, `EvidenceRequirement`, `ReviewAction` 구조는 유지하고, 새 rule node는 병행 계층으로 붙였다.

### 2.2 PolicyReviewExtractor

`src/graph/extractors.py`에서 canonical rule set을 seed하고, 원문 조항에 실제 키워드 근거가 있을 때만 clause와 rule node를 연결하도록 확장했다.

적용 예:

- `보상하지`, `면책`, `보상 제외` -> `ExclusionReason`
- `50회`, `연간`, `한도`, `MRI/MRA`, `상급병실` -> `BenefitLimit`
- `공제`, `자기부담`, `본인 부담` -> `DeductibleRule`
- `영수증`, `세부내역서`, `진단서`, `수술확인서` -> `RequiredDocument`
- `자동차보험`, `산재보험`, `타 보험`, `이미 보상` -> `CoordinationRule`
- `4세대`, `5세대`, `갱신`, `개정` -> `RenewalOrGenerationRule`

외부 의학 지식이나 문서 밖 ontology는 추가하지 않았다.

### 2.3 GraphRetriever review path

`src/graph/retriever.py`에서 review path가 rule node category를 직접 담도록 확장했다.

추가 필드:

- `exclusion_reasons`
- `benefit_limits`
- `deductible_rules`
- `required_documents`
- `coordination_rules`
- `generation_rules`

추가 path type:

- `coordination_review`
- `generation_rule_review`

자동차보험/산재/타보험 조정은 기본적으로 `review_required`로 다루며, 세대/방문/증빙이 불명확한 경우 확정 상태로 승격하지 않도록 했다.

### 2.4 Graph context / API / UI

`src/graph/context.py`:

- LLM 프롬프트에 review path와 rule category를 별도 섹션으로 주입한다.
- `candidate`, `review_required`, `missing` 상태는 확정 판단으로 쓰지 말라는 지침을 포함한다.

`src/api/rag_service.py`:

- `graph_review_paths` payload에 rule category를 포함한다.
- 최상위 payload에도 category별 요약 필드를 추가했다.

`frontend/js/pages/chat.js`:

- 구조화 검토 경로 UI에 업무형 라벨을 추가했다.
  - 적용 가능 면책 사유
  - 적용 한도
  - 적용 공제
  - 필요 서류
  - 중복 보상 조정
  - 세대/갱신 기준

### 2.5 보험금 계산 pipeline

`src/claim_calculation/models.py`, `src/api/schemas/claim.py`, `src/claim_calculation/pipeline.py`를 확장했다.

계산 결과에 다음 필드를 추가했다.

- `exclusion_reasons`
- `benefit_limits`
- `deductible_rules`
- `required_documents`
- `coordination_rules`
- `generation_rules`

Graph rule node는 금액을 임의 계산하지 않고, 계산 설명과 review trigger로만 사용한다.

## 3. 평가/테스트 보강

### 3.1 평가 스크립트

`scripts/eval_graph_review_paths.py`에 rule category 검증을 추가했다.

지원 필드:

- `required_exclusion_reasons_any`
- `required_benefit_limits_any`
- `required_deductible_rules_any`
- `required_required_documents_any`
- `required_coordination_rules_any`
- `required_generation_rules_any`

### 3.2 평가셋

`eval/graph_review_paths.jsonl`에 다음 케이스의 rule 검증을 보강했다.

- 미용 목적 합병증 면책
- 상급병실료 차액 한도
- 5세대 도수치료 한도/공제
- MRI/MRA 한도
- 자동차보험/산재보험 중복 보상 조정

### 3.3 신규 테스트

추가:

- `tests/test_graph_policy_rule_nodes.py`

수정:

- `tests/test_graph_review_path_retriever.py`
- `tests/test_claim_complication_review.py`
- `tests/test_api_rag_service_payload.py`
- `tests/test_eval_graph_review_paths.py`

## 4. 검증 결과

LLM 서버는 새로 띄우지 않았다. 모든 검증은 fixture/mock 또는 SQLite/Chroma read-only 진단으로 수행했다.

실행한 검증:

```bash
python -m py_compile \
  src/graph/schema.py \
  src/graph/extractors.py \
  src/graph/retriever.py \
  src/graph/context.py \
  src/api/rag_service.py \
  src/claim_calculation/models.py \
  src/claim_calculation/pipeline.py \
  src/api/schemas/claim.py \
  scripts/eval_graph_review_paths.py
```

결과: `PASS`

```bash
pytest -q tests/test_graph_policy_rule_nodes.py \
  tests/test_graph_policy_clause_extractor.py \
  tests/test_graph_review_path_retriever.py \
  tests/test_graph_context.py \
  tests/test_claim_complication_review.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_eval_graph_review_paths.py \
  tests/test_api_rag_service_payload.py
```

결과: `45 passed`  
DGX 기준으로 `tests/test_api_rag_service_payload.py`, `tests/test_eval_graph_review_paths.py`까지 포함해 재검증했다.

```bash
pytest -q tests/test_graph_*.py \
  tests/test_claim_*.py \
  tests/test_eval_graph_review_paths.py \
  tests/test_api_rag_service_payload.py
```

결과: `87 passed`

```bash
node --check frontend/js/pages/chat.js
```

결과: `PASS`

```bash
git diff --check -- <변경 파일 목록>
```

결과: `PASS`

DGX GraphDB rebuild:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_graph_index.py --rebuild
```

결과:

```text
GraphDB build finished successfully.
```

재빌드 후 SQLite 검증:

```text
PRAGMA integrity_check: ok
foreign_key_check: 0 rows
graph_nodes: 545,177
graph_edges: 45,858
graph_evidence: 27,015
graph_aliases: 528,090
```

신규 ontology node 적재 확인:

```text
ExclusionReason: 9
BenefitLimit: 5
DeductibleRule: 5
RequiredDocument: 9
CoordinationRule: 3
RenewalOrGenerationRule: 4
PolicyClause: 3,995
CaseExample: 1,138
DiagnosisCode: 695
```

신규 ontology edge 적재 확인:

```text
HAS_EXCLUSION_REASON: 1,908
HAS_BENEFIT_LIMIT: 1,951
HAS_DEDUCTIBLE_RULE: 2,067
REQUIRES_DOCUMENT: 262
HAS_COORDINATION_RULE: 608
HAS_GENERATION_RULE: 1,399
REQUESTS_DOCUMENT: 3
TRIGGERS_EXCLUSION_REASON: 1
```

GraphDB hard query 검증:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py --graph data/index/graph/insurance_graph.sqlite
```

결과:

```text
Q1 Overall Coverage: PASS
Q2 Overall Coverage: PASS
Detailed Integrity Check: PASS
```

Graph review path 평가:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_review_paths.jsonl \
  --output reports/graph_review_paths/eval_graph_review_paths_stage2_ontology.jsonl
```

결과: `19/19 passed`

GraphDB-VectorStore sync 샘플 진단:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_vector_sync.py \
  --index-mode v1_v2_combined \
  --limit 500 \
  --output-json reports/graph_review_paths/graph_vector_sync_stage2_ontology.json
```

결과:

```text
sampled: 500
hit_rate: 100.00%
direct_hit: 500
missing: 0
```

## 5. 자체 검토

요구사항 대비 점검:

- 6개 신규 rule node type 추가: 완료
- 신규 edge 추가: 완료
- canonical set seed: 완료
- PolicyClause에서 evidence 기반 rule node 연결: 완료
- review path에 rule node 직접 노출: 완료
- 보험금 계산 payload에 rule category 노출: 완료
- 자동차보험/산재/타보험 조정은 자동 확정보다 review action 우선: 완료
- 4세대/5세대 및 세대 불명확 상황 검토 path 추가: 완료
- 평가셋 및 evaluator 확장: 완료
- 기존 Graph/claim 회귀 테스트: 통과
- DGX GraphDB rebuild 및 SQLite 적재 검증: 완료
- Graph review path 평가: 19/19 통과
- GraphDB-VectorStore sync 샘플 진단: 500/500 hit
- LLM 서버 신규 기동: 미수행

남은 운영 후속:

- 운영 전체 회귀 전에는 앱 기동 상태에서 실제 질의 smoke test를 별도로 수행한다.
- 전체 GraphDB-VectorStore sync를 샘플이 아닌 전체 evidence 대상으로 돌릴 경우 시간이 더 걸릴 수 있으므로 운영 점검 작업으로 분리한다.

## 6. 결론

Ontology 2차 확장은 기존 GraphRAG를 깨지 않고, 정책 rule을 독립적인 업무형 노드로 승격하는 방식으로 구현되었다.

이제 앱은 보상 담당자에게 다음 정보를 구조화해서 보여줄 수 있다.

- 왜 면책 후보인지
- 어떤 한도와 공제가 관련되는지
- 어떤 서류가 부족한지
- 자동차보험/산재/타보험 조정이 필요한지
- 4세대/5세대 기준 확인이 필요한지

금액 계산은 계속 deterministic pipeline이 담당하고, Graph rule node는 설명과 review trigger로 사용된다.
