# 150. GraphDB Stage 5 Evaluation Rebuild Gate Report

작성일: 2026-05-28
대상 단계: `145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md`의 Stage 5

## 1. 작업 목적

Stage 5의 목적은 Stage 1-4에서 구현한 GraphRAG 개선이 실제 GraphDB rebuild와 평가 게이트를 통과하는지 확인하는 것이다.

검증 범위:

- review path 평가셋/평가 스크립트 추가
- GraphDB rebuild
- SQLite 내 판단 노드와 rule layer 적재 확인
- GraphDB 무결성 검사
- 전체 pytest 회귀 테스트

## 2. 추가한 평가 자산

신규 파일:

- `eval/graph_review_paths.jsonl`
- `scripts/eval_graph_review_paths.py`
- `tests/test_eval_graph_review_paths.py`

평가 항목:

- 기대 review path type 포함 여부
- path status 허용 범위
- 질문/입력 기반 session assertion 생성 여부
- required evidence 노출 여부
- review action 노출 여부
- 문서 밖 의학 인과 문구 금지 여부

평가 케이스:

- 미용 목적 수술 후 합병증 면책/증빙 검토
- 당뇨/망막 레이저/합병증 특약 질의에서 의학 인과 생성 금지
- `N39.3` 진단코드 약관 검토
- 상급병실료 차액 검토
- 도수치료 5세대 실손 통원 합병증 치료 claim review

## 3. 검토 중 발견한 결점과 조치

### 3.1 첫 rebuild 결과에 판단 노드가 누락됨

증상:

- 첫 DGX rebuild 후 `PolicyClause`, `CaseExample`, `ReviewAction` 등 새 판단 노드가 SQLite에 없었다.
- `scripts/eval_graph_review_paths.py` 결과가 `3/5 PASS`로 실패했다.

원인:

- DGX 프로젝트 폴더의 `src/graph/build.py`가 로컬 최신 코드보다 뒤처져 `PolicyReviewExtractor` 호출이 빠져 있었다.

조치:

- `src/graph/build.py`를 동기화했다.
- GraphDB를 다시 rebuild했다.
- 재검증 결과 새 판단 노드와 edge가 정상 적재됐다.

## 4. DGX 검증 결과

작업 경로:

```text
/srv/shared/projects/insurance-rag-chatbot
```

### 4.1 관련 회귀 테스트

명령:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_eval_graph_review_paths.py \
  tests/test_graph_review_path_planner.py \
  tests/test_graph_review_path_retriever.py \
  tests/test_graph_policy_clause_extractor.py \
  tests/test_api_rag_service_payload.py \
  tests/test_claim_complication_review.py -q
```

결과:

```text
11 passed in 0.27s
```

### 4.2 GraphDB rebuild

명령:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_graph_index.py --rebuild --source-mode v1_v2_combined
```

결과:

```text
GraphDB build finished successfully.
```

### 4.3 GraphDB 무결성 검사

명령:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
```

핵심 결과:

```text
Detailed Integrity Check: PASS
Q1 Overall Coverage: PASS
Q2 Overall Coverage: PASS
```

manifest:

```text
build_date: 2026-05-28T16:06:03.445372
node_count: 545136
edge_count: 35835
evidence_count: 27015
alias_count: 528090
```

판단 그래프 핵심 count:

```text
PolicyClause: 3995
CaseExample: 1138
DiagnosisCode: 695
ReviewAction: 7
ComplicationConcept: 6
EvidenceRequirement: 4
```

rule layer 검증:

```text
PolicyClause with rule_types: 3995 / 3995
```

### 4.4 Review path 평가

명령:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_review_paths.jsonl \
  --output reports/graph_review_paths/eval_graph_review_paths_stage5.jsonl
```

결과:

```text
Graph review path evaluation: 5/5 passed
```

### 4.5 전체 pytest

명령:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
478 passed, 3 warnings in 11.54s
```

## 5. 결론

Stage 5 평가/리빌드 게이트는 통과했다.

현재 GraphDB는 다음 개선 사항을 실제 SQLite rebuild 산출물에 반영한다.

- 판단 개념 노드와 review path 노드/edge
- `PolicyClause.properties.rule_types`
- `PolicyClause.properties.rule_summary`
- 합병증/후유증/부작용 관련 review-oriented path
- required evidence와 review action 기반 계산 검토 연동

남은 위험:

- review path 평가셋은 아직 5개 핵심 케이스 수준이다. 운영 전에는 실손 세대별/특약별/상담사례집 기반 케이스를 더 확장해야 한다.
- rule layer는 아직 별도 node type이 아니라 `PolicyClause.properties` 기반이다. 실무자가 직접 편집/승인하는 ontology UI가 필요해지면 rule node 승격을 검토해야 한다.
