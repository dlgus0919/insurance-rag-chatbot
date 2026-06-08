# 188. Insurance Ontology-Centered Hardcoding Refactor Priority Report

## Summary

현재 앱은 FastAPI 기반 Hybrid RAG, SQLite GraphDB, deterministic 보험금 계산 파이프라인을 결합해 실사용 가능한 1.0.x 형태까지 도달했다. 다만 보험 ontology 구축이라는 장기 목표를 기준으로 보면, 일부 핵심 판단 로직이 여전히 Python 코드 안의 keyword list, alias dict, special guard, rule table에 분산되어 있다.

이 구조의 본질적 문제는 단순히 "하드코딩이 있다"가 아니다. 더 큰 문제는 동일한 도메인 지식이 검색 확장, Graph Planner, Graph extractor, Graph retriever, 보험금 계산, UI 표시 정책에 서로 다른 형태로 복제되어 있다는 점이다. 이 때문에 특정 용어는 검색에서는 인식되지만 Graph review path에서는 인식되지 않거나, GraphDB에 node가 있어도 planner가 해당 path를 열지 못하는 불일치가 발생할 수 있다.

따라서 Graph Planner 자체를 더 복잡하게 만들기 전에, 먼저 domain knowledge를 코드에서 분리해 ontology manifest와 rule registry로 일원화해야 한다.

## Current Problem Situation

현재 문제는 "몇몇 키워드가 코드에 적혀 있다" 수준이 아니다. 실제 앱의 핵심 판단 흐름에서 같은 보험 개념이 여러 위치에 서로 다른 방식으로 저장되어 있고, 이 목록들이 자동으로 동기화되지 않는다는 점이 문제다.

예를 들어 `이륜자동차` 질의는 검색 단계에서 별도 확장어가 붙는다. 검색 파이프라인은 `이륜자동차`, `오토바이`, `원동기`, `스쿠터`를 보면 `이륜자동차 부담보 특별약관`, `보험금을 지급하지 않는 사유`, `알릴 의무`, `통지` 같은 단어를 강제로 추가한다. 이 덕분에 관련 문서 chunk는 검색될 수 있다.

그러나 Graph Planner는 같은 질의를 반드시 같은 개념으로 인식하지 않는다. Planner 쪽의 coverage topic, condition, alias 목록은 별도 Python list/dict로 관리되기 때문이다. 따라서 검색 결과에는 관련 근거가 있는데도 `ClaimCondition`, `ReviewAction`, `ExclusionReason`, `coordination_review` 같은 구조화 검토 경로가 열리지 않을 수 있다. 사용자는 출처 링크는 보지만, 우리가 의도했던 "구조화 검토 경로"와 "권장 검토 조치"는 보지 못한다.

이 패턴은 `이륜자동차`에만 국한되지 않는다.

- 검색 확장어는 `src/rag/pipeline.py`에 있고, Graph Planner alias는 `src/graph/query_planner.py`에 있다.
- GraphDB seed ontology는 `src/graph/extractors.py`의 dict에 있고, runtime path 표시 정책은 `src/graph/retriever.py`의 set/map에 있다.
- 보험금 계산의 세대별 공제, 상급병실료 차액, 건강보험 미적용 특례는 계산 파이프라인과 rule table에 따로 있다.
- 문서 필터, OCR index routing, strict evidence mode도 별도 키워드 목록으로 판단한다.

즉 현재 구조에서는 새 보험 개념을 하나 추가하려면 "검색 확장", "Planner 인식", "GraphDB seed", "review path 표시", "보험금 계산", "UI 표시" 중 어디까지 고쳐야 하는지 매번 사람이 추적해야 한다. 하나라도 빠지면 검색은 되는데 구조화 근거가 안 보이거나, GraphDB에는 node가 있는데 답변에는 쓰이지 않거나, 계산은 되는데 근거 경로가 설명되지 않는 결함이 생긴다.

보험 ontology 구축 관점에서 이는 가장 먼저 해결해야 할 구조적 부채다. ontology는 코드 곳곳의 보조 목록이 아니라, 검색과 판단과 계산을 함께 구동하는 중심 지식 체계가 되어야 한다.

## Why This Matters for Insurance Ontology

보험 ontology의 목적은 단순히 "검색어를 더 잘 찾는 것"이 아니다. 보상 실무에서 반복적으로 등장하는 개념, 조건, 예외, 면책, 한도, 증빙, 심사 조치를 하나의 구조화된 지식 체계로 관리하는 것이다.

현재처럼 코드 안에 특정 용어를 직접 넣는 방식은 단기적으로는 빠르게 문제를 고칠 수 있다. 예를 들어 `이륜자동차` 질의가 검색에서 잘 잡히지 않으면 검색 확장 함수에 `이륜자동차 부담보 특별약관`, `알릴 의무`, `통지` 같은 단어를 붙이면 된다. 그러나 이 방식은 검색만 보강하고 Graph Planner, GraphDB seed node, review path, UI 표시 정책에는 같은 지식이 자동으로 전달되지 않는다.

그 결과 다음과 같은 불일치가 생긴다.

- 검색 단계는 특정 용어를 알고 있지만 Graph Planner는 모른다.
- GraphDB에는 관련 node가 있어도 Planner intent가 열리지 않아 review path가 생성되지 않는다.
- 보험금 계산은 특정 조건을 코드 분기로 처리하지만, 답변 근거 path에는 같은 조건이 드러나지 않는다.
- 새 약관, 새 특약, 새 예외 조항을 추가할 때 Python 코드 여러 곳을 동시에 고쳐야 한다.

따라서 궁극적으로는 "하드코딩을 없애자"가 아니라, "도메인 지식의 위치를 코드에서 ontology/rule registry로 옮기자"가 핵심 방향이다.

## Key Conclusion from Code Inventory

앞선 코드 조사 결과, 하드코딩은 한 파일의 문제가 아니라 다음 런타임 계층에 걸쳐 존재한다.

1. `src/rag/pipeline.py`의 검색 확장 로직
2. `src/graph/query_planner.py`의 coverage topic, condition, alias, intent 판정
3. `src/graph/extractors.py`의 seed ontology와 keyword extractor
4. `src/graph/retriever.py`의 review path 표시/필터 정책
5. `src/claim_calculation/pipeline.py`와 `deductible_rules.py`의 계산 분류/특례/공제 규칙
6. `src/rag/evidence.py`, `src/api/rag_service.py`, `src/retrieval/index_mode.py`의 근거 검증, 문서 필터, OCR index routing
7. `src/api/routes/chat.py`, `src/api/routes/claim.py`, `src/config.py`의 모델 alias와 운영 설정

이 중 보험 ontology와 직접 연결되는 최우선 정리 대상은 1~5번이다. 특히 검색 확장과 Graph Planner가 서로 다른 하드코딩 목록을 사용한다는 점이 가장 큰 구조적 위험이다.

## Current Hardcoded Logic Layers

| Layer | Representative files | Current role | Main risk |
|---|---|---|---|
| Retrieval query expansion | `src/rag/pipeline.py` | 교통사고, 이륜자동차, 음주, 3대비급여 등 특정 질문군에 검색어를 추가 | Graph Planner와 동기화되지 않으면 검색만 성공하고 구조화 경로는 누락 |
| Graph Planner lexicon | `src/graph/query_planner.py` | coverage topic, condition, alias, intent, clarification 질문 판정 | 새 보험 개념 추가 때 코드 수정 필요 |
| Graph extractor seed ontology | `src/graph/extractors.py` | ClaimCondition, DecisionConcept, ExclusionReason, BenefitLimit, CoordinationRule 등을 seed | GraphDB가 문서 기반 ontology가 아니라 코드 seed에 강하게 종속 |
| Graph retriever display/filter policy | `src/graph/retriever.py` | 어떤 rule/path를 보여줄지 Python set과 context map으로 제한 | 정당한 근거 경로가 UI에 숨겨질 수 있음 |
| Claim calculation rules | `src/claim_calculation/pipeline.py`, `src/claim_calculation/deductible_rules.py` | 급여/비급여/3대비급여 분류, 공제율, 특례, 면책 우선순위 계산 | 약관 세대/상품/개정별 rule 변경이 코드 배포 작업이 됨 |
| Evidence guard and formal routing | `src/rag/evidence.py`, `src/api/rag_service.py`, `src/retrieval/index_mode.py` | strict evidence query, 문서 필터, OCR index routing, template cleanup | 검색 정책과 표시 정책이 코드 곳곳에 분산 |
| Model/runtime aliases | `src/api/routes/chat.py`, `src/api/routes/claim.py`, `src/config.py` | 모델 alias, provider routing, token/reasoning 정책 | 운영 설정 변경과 코드 변경이 섞임 |

## Target Principle

보험 ontology는 다음 네 가지 산출물을 동시에 구동해야 한다.

1. 검색 확장어: 어떤 용어가 들어오면 어떤 근거 단어를 보강할지
2. Planner lexicon: 어떤 입력 표현이 어떤 canonical concept로 정규화되는지
3. Graph seed/build: 어떤 canonical node와 edge를 만들지
4. Runtime policy: 어떤 경로를 노출하고, 어떤 경우 review/human task를 요구할지

현재는 이 네 가지가 코드 곳곳에 따로 있다. 목표 구조에서는 하나의 ontology manifest가 네 가지 산출물을 생성해야 한다.

```text
raw docs / xlsx
  -> extractor 후보
  -> ontology candidate registry
  -> human review / promote
  -> canonical ontology manifest
  -> planner lexicon + graph seed + retrieval expansion + runtime policy
```

## Replacement Methodology Matrix

하드코딩 대체는 "모든 판단을 LLM에게 맡기는 방향"이 아니다. 오히려 보험 도메인에서는 deterministic하고 감사 가능한 구조가 더 중요하다. 권장 방향은 코드 분기를 ontology/rule data로 옮기고, 런타임에서는 검증된 registry를 조회하는 것이다.

| 관점 | 현재 문제 | 대체 방법론 | 기대 효과 |
|---|---|---|---|
| 성능 | 여러 파일에서 같은 문자열 매칭을 반복한다. 특정 질의 보강이 Python 분기에 의존한다. | 앱 시작 시 ontology manifest를 로드해 normalized alias index, retrieval expansion index, planner trigger index로 컴파일한다. | `if any(keyword...)`보다 느릴 필요가 없고, 중복 매칭을 줄일 수 있다. |
| 성능 | Graph path 필터가 Python set/map을 거쳐 후처리된다. | rule node에 `display_policy`, `requires_context`, `priority`를 저장하고 조회 시 metadata로 필터링한다. | path 선정 기준이 명확해지고 cache/materialized path 적용이 쉬워진다. |
| 확장성 | 새 개념을 추가하려면 검색, planner, extractor, retriever, UI를 각각 수정해야 한다. | `concept_id` 중심의 ontology manifest에서 alias, expansion, planner mapping, graph seed, review policy를 함께 정의한다. | `이륜자동차`, `하나의 질병`, `계약 후 알릴 의무` 같은 개념을 코드 수정 없이 확장할 수 있다. |
| 확장성 | 보험금 계산 rule이 세대/상품/특례 변화에 취약하다. | 세대, 방문유형, 급여구분, 특례, 한도, 공제율을 decision table로 관리하고 `rule_id`로 추적한다. | 6세대 실손이나 상품별 특약 추가 시 row 추가로 대응 가능하다. |
| 유지보수 | 동일 도메인 지식이 코드 곳곳에 복제되어 drift가 생긴다. | ontology manifest와 rule registry를 single source of truth로 삼고 sync 검사 스크립트를 둔다. | 어떤 개념이 검색에는 있는데 Graph에는 없는 상태를 자동 탐지할 수 있다. |
| 유지보수 | 코드 리뷰가 Python 분기문 중심이라 도메인 담당자가 검토하기 어렵다. | YAML/SQLite 기반 registry에 `source_doc`, `page`, `status`, `owner_reviewed`, `test_queries`를 포함한다. | 도메인 변경 검토가 ontology diff와 테스트 질의 중심으로 바뀐다. |

## Priority 1. Unified Ontology Manifest 도입

### Scope

`src/graph/query_planner.py`, `src/graph/extractors.py`, `src/rag/pipeline.py`에 흩어진 concept, alias, trigger, expansion term을 `data/ontology/` 아래 versioned manifest로 이동한다.

권장 파일 구조:

```text
data/ontology/
  ontology_manifest.schema.json
  concepts.yml
  aliases.yml
  retrieval_expansions.yml
  planner_intents.yml
  review_path_policies.yml
  claim_rule_registry.yml
```

예시 개념 구조:

```yaml
- concept_id: cond.motorcycle_riding
  node_type: ClaimCondition
  canonical_name: 이륜자동차 운전/탑승
  aliases:
    - 이륜자동차
    - 오토바이
    - 원동기
    - 스쿠터
  retrieval_expansion_terms:
    - 이륜자동차 부담보 특별약관
    - 보험금을 지급하지 않는 사유
    - 알릴 의무
    - 통지
  planner:
    coverage_topics:
      - 운전자보험
    conditions:
      - 이륜자동차 운전/탑승
    intents:
      - claim_condition_lookup
      - session_claim_path_review
  review_policy:
    default_path_type: claim_condition_review
    default_status: review_required
    recommended_actions:
      - 고지/통지의무 확인
      - 특약 가입 여부 확인
  provenance:
    source_policy: 자사_SOL운전자
    source_note: 문서 근거 연결 필요
```

### Performance

- manifest는 앱 시작 시 한 번 로드하고 normalized alias index로 컴파일한다.
- Python `if any(keyword...)`보다 느릴 필요가 없다.
- trie 또는 Aho-Corasick을 쓰면 다수 alias도 선형 시간으로 처리 가능하다.
- retrieval expansion, planner, basis selector가 같은 compiled index를 공유하면 중복 매칭 비용도 줄어든다.

### Scalability

- 새로운 보험 개념을 코드 수정 없이 추가 가능하다.
- `이륜자동차`, `고지의무`, `계약 후 알릴 의무`, `하나의 질병`, `타보험 선보상` 같은 개념을 동일한 흐름으로 확장할 수 있다.
- 외부 의학 ontology가 아니라 프로젝트 원천 문서에서 검토/promote한 concept만 넣을 수 있어 원칙에도 부합한다.

### Maintainability

- 도메인 지식의 single source of truth가 생긴다.
- 코드 리뷰 대상이 Python 분기문이 아니라 ontology diff가 된다.
- concept별 provenance, 적용 문서, 테스트 질의를 함께 둘 수 있어 회귀 관리가 쉬워진다.

### Implementation order

1. `OntologyRegistry` loader 추가
2. 기존 `query_planner.py`의 hardcoded list를 registry-backed list로 대체
3. `_expand_retrieval_query`를 registry-backed expansion으로 대체
4. `extractors.py` seed dictionaries를 manifest에서 생성
5. 기존 hardcoded dict는 deprecated compatibility layer로 두고 테스트 통과 후 제거

## Priority 2. Planner와 Retrieval의 Concept Sync 보장

### Scope

검색 확장과 Graph Planner가 반드시 같은 concept registry를 사용하도록 만든다. 현재처럼 retrieval query는 `이륜자동차`를 알지만 planner는 review path를 열지 못하는 상태를 금지한다.

### Performance

- planner와 retriever가 같은 alias match result를 공유하면 중복 문자열 매칭을 줄일 수 있다.
- `PlannerMatchResult`를 만들어 API debug/audit에도 남기면 운영 진단 속도가 빨라진다.

### Scalability

- 새로운 concept가 추가될 때 검색/Graph/UI가 같이 열린다.
- concept별 `enabled_in` 필드로 검색 전용, planner 전용, 계산 전용을 구분할 수 있다.

### Maintainability

- sync 검사 스크립트를 만들 수 있다.
- 예: `scripts/check_ontology_sync.py`가 다음을 검증한다.
  - 모든 retrieval expansion concept는 planner mapping을 가진다.
  - 모든 planner condition은 GraphDB node seed target을 가진다.
  - 모든 review path policy는 UI label 또는 backend label을 가진다.

### Implementation order

1. `ConceptMatch` dataclass 도입
2. `GraphQueryPlan`에 `matched_concepts` 추가
3. `retrieve_hits`가 `_expand_retrieval_query` 대신 registry expansion 결과를 사용
4. audit log에 `matched_concepts`, `expansion_terms`, `planner_intents` 기록
5. 이륜자동차 질의 회귀 테스트 추가

## Priority 3. GraphDB Seed Ontology를 Code Dict에서 Data Registry로 이전

### Scope

`COMPLICATION_CONCEPTS`, `CLAIM_CONDITIONS`, `DECISION_CONCEPTS`, `EXCLUSION_REASONS`, `BENEFIT_LIMITS`, `DEDUCTIBLE_RULES`, `COORDINATION_RULES`, `RENEWAL_OR_GENERATION_RULES`를 code dict에서 manifest seed로 이전한다.

### Performance

- Graph build 시만 사용되는 데이터이므로 런타임 성능 영향은 작다.
- build 시 schema validation을 먼저 수행해 잘못된 ontology가 SQLite에 들어가는 것을 차단한다.

### Scalability

- Stage 2/3 ontology 확장이 쉬워진다.
- `하나의 질병`, `계약 전 알릴 의무`, `계약 후 알릴 의무`, `이륜자동차 부담보`, `중복 보상 조정`, `타보험 선보상`, `비례보상`, `면책 예외`, `갱신 전후 적용` 등을 일관된 node type과 edge policy로 추가 가능하다.

### Maintainability

- 문서 기반 rule node의 출처를 manifest 단위로 추적할 수 있다.
- 사람이 수정할 수 있는 YAML과 자동 생성된 SQLite를 분리해 운영 안정성이 좋아진다.

### Implementation order

1. 현재 dict를 그대로 YAML로 export하는 script 작성
2. YAML schema validation 추가
3. extractor가 YAML을 읽어 seed하도록 변경
4. 기존 test fixture를 YAML 기반으로 갱신
5. GraphDB rebuild 후 node/edge count 및 대표 path smoke test

## Priority 4. Claim Calculation Rule Engine 분리

### Scope

보험금 계산에서 다음 로직을 data-driven rule table로 옮긴다.

- 세대별 공제율
- 통원/입원/처방 공제
- 건당/연간 한도
- 건강보험 미적용 특례
- 상급병실료 차액 특례
- 면책/보상제외 우선순위
- 표준코드 모호성 처리

권장 구조:

```text
data/rules/claim_calculation_rules.yml
src/claim_calculation/rule_engine.py
src/claim_calculation/rule_trace.py
```

각 rule은 다음 필드를 가진다.

```yaml
- rule_id: claim.5th.outpatient.non_severe_nonpay
  generation: 5th
  visit_type: outpatient
  category: 비중증비급여
  deductible:
    type: max_ratio_or_min
    ratio: 0.5
    min_amount: 50000
  per_visit_limit: 200000
  source:
    doc_short: 표준약관
    page: null
  review:
    required_when:
      - category_uncertain
      - evidence_missing
```

### Performance

- rule lookup은 `(generation, category, visit_type, facility)` key index로 O(1)에 가깝게 처리 가능하다.
- LLM 계산식을 호출하기 전에 deterministic rule engine이 baseline을 산출하므로 현재 정확성 guard도 유지된다.

### Scalability

- 6세대 실손, 상품별 특약, 개정 전후 rule을 새 row로 추가할 수 있다.
- 계산 logic과 source provenance를 함께 관리할 수 있다.

### Maintainability

- rule 변경이 코드 배포가 아니라 rule manifest diff가 된다.
- 결과 payload에 `applied_rule_ids`와 `rule_trace`를 남기면 보상 담당자가 왜 그런 계산이 나왔는지 추적 가능하다.

### Implementation order

1. 현재 `deductible_rules.py` 내용을 YAML rule table로 export
2. `RuleEngine.lookup()` 추가
3. `_classify_claim_category`를 표준코드/ontology 기반 category resolver로 교체
4. `CalculationResult`에 `applied_rule_ids`, `rule_trace` 추가
5. 기존 계산 테스트를 rule_id 기반 assertion으로 보강

## Priority 5. Retriever Path Policy를 Graph Metadata 기반으로 이전

### Scope

`src/graph/retriever.py`의 `_COORDINATION_CONTEXT_NAMES`, `_GENERATION_CONTEXT_NAMES`, `_DIAGNOSIS_EXCLUSION_CONTEXT_MAP` 같은 Python set/map을 GraphDB rule metadata로 옮긴다.

### Performance

- path filtering은 조회 후 list filtering이라 현재도 비용은 작다.
- metadata-driven filtering으로 바꿔도 path 수가 제한되어 성능 저하는 제한적이다.
- 자주 나오는 path는 materialized review path cache로 보완 가능하다.

### Scalability

- 새 rule type을 추가해도 retriever 코드를 수정하지 않아도 된다.
- rule node에 `display_when`, `suppress_when`, `requires_context`, `default_status`를 둔다.

### Maintainability

- "왜 이 path가 보였거나 숨겨졌는지"를 rule metadata로 설명할 수 있다.
- UI/QA에서 path display policy를 검증하기 쉬워진다.

### Implementation order

1. rule node property에 `display_policy` 추가
2. retriever filter가 Python set 대신 node property를 사용
3. diagnosis/coordination/generation path 회귀 테스트 추가
4. admin 진단 탭에 suppressed path count와 reason 노출

## Priority 6. Evidence Guard and Document Routing을 Taxonomy 기반으로 정리

### Scope

`src/rag/evidence.py`, `src/api/rag_service.py`, `src/retrieval/index_mode.py`, `src/claim_calculation/basis_selector.py`의 문서/질의 라우팅 키워드를 문서 taxonomy와 ontology concept에 연결한다.

### Performance

- taxonomy는 작으므로 메모리 lookup 비용이 낮다.
- 검색 전 routing이 안정되면 불필요한 Chroma/BM25 후보가 줄어 응답 시간이 개선될 수 있다.

### Scalability

- 새 문서가 추가되어도 `doc_short`, product type, source priority, index preference만 등록하면 된다.
- OCR index routing도 문서 metadata와 quality score 기반으로 전환할 수 있다.

### Maintainability

- 문서 alias와 product category가 한 곳에 모인다.
- formal search, quick code, claim calculation basis selector가 같은 taxonomy를 공유한다.

### Implementation order

1. `data/ontology/document_taxonomy.yml` 추가
2. `_DOC_ALIASES`, `_PRODUCT_DOC_FILTERS`, `_FORMAL_CATEGORY_DOC_FILTERS` 이전
3. `resolve_effective_index_mode`를 taxonomy/index preference 기반으로 변경
4. admin 검색 진단에서 적용된 taxonomy rule 표시

## Priority 7. Model/Runtime Policy Registry 분리

### Scope

모델 alias, provider, reasoning mode, max token, disabled model, launcher 노출 여부를 code path가 아니라 운영 registry로 관리한다.

### Performance

- 성능 자체보다는 운영 안정성 개선이 목적이다.
- 모델별 context/token/reasoning 설정이 명확해져 잘못된 모델 설정으로 인한 응답 실패를 줄인다.

### Scalability

- 새 모델 추가 시 API route 수정 없이 registry만 갱신한다.
- DGX launcher, `/api/system/models`, frontend selector가 같은 registry를 읽게 한다.

### Maintainability

- 현재 `chat.py`, `claim.py`, `config.py`, ops scripts 사이 모델 목록 불일치를 줄인다.
- 모델별 검증 상태(`stable`, `candidate`, `hidden`, `blocked`)를 명확히 표시할 수 있다.

## Recommended Roadmap

### Phase 0. Inventory Freeze

- 현재 hardcoded logic 목록을 baseline 문서로 고정한다.
- 모든 변경 전 representative queries를 평가셋으로 만든다.
- 특히 다음 질의는 회귀 필수다.
  - 이륜자동차 통지의무 보상 여부
  - N39.3 진단코드 보상 여부
  - 도수치료 4/5세대 계산
  - 건강보험 미적용 특례
  - 상급병실료 차액
  - 췌이식술 Q8061/Q8062

### Phase 1. Ontology Manifest Loader

- code dict를 제거하지 않고 manifest loader를 먼저 추가한다.
- loader 결과와 기존 hardcoded 결과가 같은지 shadow mode로 비교한다.
- admin diagnostic에 `ontology_loaded`, `concept_count`, `alias_count`, `sync_errors` 표시.

### Phase 2. Planner/Retrieval Sync

- Graph Planner와 retrieval expansion이 같은 `OntologyRegistry`를 사용하게 한다.
- 이 단계가 끝나면 특정 용어가 검색에만 반영되고 Graph path에는 빠지는 문제가 줄어든다.

### Phase 3. Graph Seed Migration

- Graph extractor seed dictionaries를 ontology manifest 기반으로 전환한다.
- GraphDB rebuild 및 representative path 검증을 수행한다.

### Phase 4. Claim Rule Engine

- 계산 rule table과 rule trace를 도입한다.
- 현재 deterministic 계산 정확성은 유지하되, rule provenance와 versioning을 강화한다.

### Phase 5. Retriever Display Policy/Data Taxonomy

- Graph retriever의 display/suppression policy를 rule metadata로 이전한다.
- 문서 taxonomy 기반 routing으로 formal/quick/claim basis selector를 정리한다.

## Acceptance Criteria

1. `이륜자동차` 같은 새 concept 추가가 Python 코드 수정 없이 가능해야 한다.
2. 하나의 concept manifest 변경으로 retrieval expansion, planner condition, graph seed, review path policy가 동시에 갱신되어야 한다.
3. 모든 ontology/rule 항목은 `source`, `status`, `owner_reviewed`, `test_queries`를 가진다.
4. GraphDB rebuild 후 대표 질의에서 구조화 검토 경로가 유지되어야 한다.
5. 보험금 계산 결과에는 적용된 `rule_id`와 source provenance가 포함되어야 한다.
6. admin 진단에서 ontology sync 오류를 확인할 수 있어야 한다.

## Immediate Recommendation

Graph Planner를 더 고치기 전에 `OntologyRegistry`와 manifest schema를 먼저 만든다. 그 다음 현재 hardcoded list를 그대로 manifest로 이관하고, planner와 retrieval expansion을 같은 registry에 연결한다. 이 작업이 끝나기 전까지는 `query_planner.py`에 개별 키워드를 계속 추가하는 방식은 중단하는 것이 좋다.
