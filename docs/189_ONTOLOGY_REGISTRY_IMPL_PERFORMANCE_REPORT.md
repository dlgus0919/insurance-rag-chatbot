# 189. OntologyRegistry Manifest Schema Implementation and Performance Report

## Summary

하드코딩된 보험 개념 목록을 코드에서 분리하기 위한 1단계로 `OntologyRegistry`와 JSON manifest schema를 추가했다.

작업 버전:

- base: `v1.0.3` 이후 `master`
- work version: `ontology-registry-stage1-20260608`
- target branch: `master`

이번 구현의 우선 기준은 성능보다 확장성이다. 목표는 새 보험 상품, 개정 약관, 신규 raw PDF/XLSX가 편입될 때 Python 코드를 직접 수정하지 않고 ontology manifest 갱신으로 검색 확장과 Graph Planner 인식 범위를 함께 확장하는 것이다.

## Implemented Scope

추가 파일:

- `data/ontology/ontology_manifest.schema.json`
- `data/ontology/concepts.json`
- `src/ontology/__init__.py`
- `src/ontology/registry.py`
- `scripts/check_ontology_sync.py`
- `tests/test_ontology_registry.py`

수정 파일:

- `src/rag/pipeline.py`
- `src/graph/query_planner.py`
- `src/graph/extractors.py`

## What Changed

### Before

같은 보험 개념이 여러 코드 위치에 분산되어 있었다.

- 검색 확장: `src/rag/pipeline.py`
- Graph Planner alias/condition/topic: `src/graph/query_planner.py`
- GraphDB seed node: `src/graph/extractors.py`
- 일부 review path/계산 rule: 별도 Python set, dict, rule table

예를 들어 `이륜자동차`는 검색 확장에서는 인식되지만 Graph Planner의 구조화 조건으로는 보장되지 않아, 출처 chunk는 보이는데 `구조화 검토 경로`가 열리지 않는 불일치가 발생할 수 있었다.

### After

초기 manifest인 `data/ontology/concepts.json`이 다음 정보를 함께 가진다.

- canonical concept id
- node type
- aliases
- candidate aliases
- retrieval expansion rules
- planner coverage topics
- planner conditions
- claim unit terms
- evidence tags

런타임에서는 `OntologyRegistry`가 manifest를 한 번 읽어 다음 index를 컴파일한다.

- retrieval expansion index
- planner coverage topic alias index
- planner condition alias index
- term correction candidate index
- claim unit alias index
- GraphDB seed node source

따라서 새 개념은 manifest에 추가하면 검색 확장, Planner, Graph seed에 동시에 반영될 수 있다.

## Example

`이륜자동차` 개념은 이제 Python 분기가 아니라 manifest에 정의된다.

```json
{
  "concept_id": "cond.motorcycle_riding",
  "canonical_name": "이륜자동차 운전/탑승",
  "node_type": "ClaimCondition",
  "aliases": ["이륜자동차", "오토바이", "원동기", "스쿠터"],
  "planner": {
    "conditions": ["이륜자동차 운전/탑승"],
    "intents": ["claim_condition_lookup", "session_claim_path_review"]
  }
}
```

이 구조에서는 같은 alias가 검색 확장과 Planner 조건에 함께 쓰인다.

## Performance Check

로컬 Mac 작업공간에서 동일 질의 6개를 120,000회 호출해 기존 하드코딩 확장 함수와 새 registry 확장 함수를 비교했다.

측정 명령 요약:

```bash
python3 -c "<legacy expansion vs OntologyRegistry expansion microbenchmark>"
```

결과:

| Metric               | Legacy hardcoded expansion | OntologyRegistry expansion |
| -------------------- | -------------------------: | -------------------------: |
| Registry load        |                        N/A |                   0.276 ms |
| Total expansion time |                  77.889 ms |                 279.290 ms |
| Per-call time        |                   0.649 us |                   2.327 us |
| Added overhead       |                        N/A |             +1.678 us/call |

Graph Planner registry-backed runtime도 별도로 확인했다.

| Metric            |         Result |
| ----------------- | -------------: |
| Planner init      |       0.603 ms |
| Planner plan call | 34.766 us/call |

## Improved Points

### 1. 확장성

가장 큰 개선점이다. 새 보험 개념을 추가할 때 더 이상 검색 확장 함수와 Graph Planner alias 목록을 각각 고칠 필요가 없다.

이번 테스트에서는 임시 manifest에 `새보험 특례` concept를 추가하고, 코드 수정 없이 다음이 동시에 동작함을 확인했다.

- Planner condition 인식
- retrieval expansion
- ontology sync check 통과

### 2. 유지보수성

도메인 지식의 위치가 Python 코드에서 manifest로 이동했다. 앞으로 코드 리뷰는 `if keyword in query` 분기보다 ontology diff 중심으로 할 수 있다.

또한 `scripts/check_ontology_sync.py`를 추가해 다음 유형의 drift를 조기에 잡을 수 있게 했다.

- retrieval expansion은 있는데 planner mapping이 없는 concept
- candidate alias는 있는데 planner mapping이 없는 concept
- concept id 중복
- 빈 ontology manifest

### 3. GraphDB 재빌드 정합성

`src/graph/extractors.py`가 `OntologyRegistry` concept를 seed node로 적재하도록 연결했다. 따라서 manifest concept는 GraphDB rebuild 때도 node/alias로 들어갈 수 있다.

## Regressed or Weaker Points

### 1. 마이크로 성능은 소폭 퇴보

기존 하드코딩 확장 함수는 4개 분기만 검사했기 때문에 매우 빨랐다. registry 방식은 manifest concept와 expansion rule을 순회하므로 호출당 약 `+1.678 us` 오버헤드가 생겼다.

다만 실제 RAG 질의는 BM25/Chroma/reranker/LLM 단계에서 ms~초 단위 비용이 발생하므로, 이 오버헤드는 사용자 체감 성능에 영향을 주기 어렵다.

### 2. 초기 manifest 품질 관리 필요

확장성이 좋아진 대신 manifest 품질이 중요해졌다. 잘못된 alias나 너무 넓은 expansion term이 들어가면 검색 후보가 넓어질 수 있다.

대응책:

- ontology sync check 필수화
- concept별 test query 추가
- 관리자 진단 탭에 ontology loaded/count/sync error 표시

### 3. 보험금 계산 rule은 아직 완전 이전 전

이번 패치는 검색 확장, Graph Planner, Graph seed의 공통 registry화에 집중했다. 세대별 공제율, 한도, 면책 우선순위 등 계산 rule은 아직 완전한 data-driven `RuleRegistry`로 이전하지 않았다.

이는 다음 단계에서 `data/rules/` decision table로 분리해야 한다.

## Verification

실행한 검증:

```bash
python3 scripts/check_ontology_sync.py
pytest tests/test_ontology_registry.py tests/test_graph_review_path_planner.py tests/test_pipeline.py -q
pytest tests/test_graph_policy_rule_nodes.py tests/test_ontology_registry.py -q
python3 -m compileall -q src/ontology src/graph/query_planner.py src/rag/pipeline.py src/graph/extractors.py scripts/check_ontology_sync.py
```

결과:

- ontology sync check: PASS (`concepts=49`, `aliases=109`, `candidate_aliases=18`, `retrieval_rules=4`)
- related pytest: `56 passed`
- graph seed related pytest: `7 passed`
- compileall: PASS

## Next Steps

1. `RuleRegistry`를 추가해 `deductible_rules.py`와 계산 특례를 data-driven decision table로 이전한다.
2. 관리자 진단 탭에 ontology manifest version, concept count, alias count, sync error를 노출한다.
3. GraphDB rebuild 후 `cond.motorcycle_riding` 같은 새 manifest node가 실제 SQLite에 들어가는지 운영 DB 기준으로 검증한다.
4. raw 문서 편입 파이프라인을 `candidate -> human review -> promote -> active manifest` 구조로 확장한다.
