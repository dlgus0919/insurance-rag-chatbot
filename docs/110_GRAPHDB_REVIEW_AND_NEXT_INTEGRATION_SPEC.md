# 110. GraphDB Review And Next Integration Spec

작성일: 2026-05-22
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
대상 작업자: Antigravity 서브 에이전트
작업 성격: GraphDB 1차 구현 검토, 결점 보정 지시, Graph-RAG 통합 다음 단계 명세

## 1. 현재 구현 상태 요약

GraphDB 1차 빌드 파이프라인은 작동한다. 이전 병목이었던 row 단위 commit 문제는 벌크 적재와 명시적 transaction으로 해소되었고, `data/index/graph/insurance_graph.sqlite` 산출물도 정상 생성되었다.

현재 원격 DGX 검증 결과:

```text
GraphDB: data/index/graph/insurance_graph.sqlite
크기: 약 536MB
Node: 539,247
Edge: 21,787
Evidence: 21,882
Alias: 528,090
```

주요 node:

```text
MedicalFeeCode: 9,020
NonpayStandardCode: 527,679
PolicyBenefitRule: 69
SurgeryCategory: 87
SurgeryGrade: 20
SurgeryProcedure: 2,369
```

주요 edge:

```text
HAS_GRADE: 5,373
HAS_CATEGORY: 4,800
HAS_MEDICAL_FEE_CODE: 1,933
PAYS_BY_RATIO: 70
POLICY_COVERS_PROCEDURE: 432
```

검증:

```bash
.venv/bin/pytest tests/test_graph_extractors.py tests/test_graph_store.py -v
# 6 passed

.venv/bin/python scripts/check_graph_index.py
# Q1/Q2 hard query fixture coverage PASS
# Detailed Integrity Check PASS
```

SQLite 확인:

```text
PRAGMA integrity_check: ok
PRAGMA foreign_key_check: no rows
```

## 2. 긍정 평가

### 2.1 성능 병목 해소

초기 구현은 52.7만 건 비급여 표준코드를 row 단위 commit으로 적재해 수 시간 소요가 예상되었다. 현재는 batch insertion과 explicit transaction으로 빌드 시간이 실사용 가능한 수준으로 개선되었다.

### 2.2 SOL [별표7] 행 분리 개선

이전에는 18번 항목과 19번 항목이 하나의 `PolicyBenefitRule`로 섞였다. 현재는 다음처럼 분리된다.

```text
rule_sol_health_별표7_18
- 기관(氣管), 기관지(氣管支), 폐(肺), 흉막(胸膜) 관혈수술...
- grade_value: 4

rule_sol_health_별표7_19
- 폐장(肺臟) 이식수술 [수용자(受容者)에 한함]
- grade_value: 5
```

### 2.3 일반어 매칭 개선

`matched_keyword: "수술"` 같은 무의미한 연결은 제거되었다. 현재 대표 matched keyword는 `식도`, `췌장`, `기관`, `직장`, `후두`, `담도`, `결장` 등 도메인 명사 중심이다.

### 2.4 Evidence 연결 개선

`POLICY_COVERS_PROCEDURE` 432개 edge 모두 `source_evidence_id`가 있고, `graph_edge_evidence`에도 매핑되어 있다. 이전의 evidence 없는 coverage edge 문제는 해결되었다.

## 3. 남은 결점과 위험

### 3.1 Policy coverage edge는 아직 "확정 관계"가 아니다

현재 `POLICY_COVERS_PROCEDURE` 432개는 전부 `confidence=0.8`이다. 즉, exact match가 아니라 category alignment + keyword partial match 기반이다.

예:

```text
기관지 식도루 폐쇄술
  <- rule_sol_health_별표7_18
  matched_keyword: 기관
```

이 연결은 업무적으로 그럴듯하지만, "기관"이라는 키워드는 넓다. 따라서 현재 edge를 보험금 지급비율의 최종 확정 근거로 직접 사용하면 안 된다. UI/답변에서는 "약관 별표 후보" 또는 "동일 대분류 후보"로 취급해야 한다.

### 3.2 `check_graph_index.py`의 Q2 검증이 아직 약하다

Q2는 `소화기계 + 신1-5종 5종` 결과로 `간장 이식수술`, `췌장 이식수술`을 잘 찾는다. 하지만 현재 검증은 다음을 충분히 보장하지 않는다.

- 각 수술별 수가코드가 정확히 연결됐는가
- 각 수술별 SOL [별표7] 지급비율이 정확한 rule에서 왔는가
- 지급비율이 대분류 일반값인지, 수술명 특정값인지 구분되는가

따라서 Q2의 graph retrieval 결과는 "수술 목록"까지는 비교적 신뢰할 수 있으나, "각 수술의 수가코드와 지급비율"은 별도 검증이 필요하다.

### 3.3 GraphStore 런타임 연결은 read-only가 아니다

`GraphStore(build_mode=False)`는 `synchronous=NORMAL`로 개선됐지만 여전히 `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`를 실행한다. Streamlit/RAG 런타임에서는 생성 산출물에 쓰기 권한이 필요 없는 read-only 연결이 더 안전하다.

필요:

- `GraphStore.open_readonly(path)` 또는 `GraphStore(db_path, readonly=True)`
- SQLite URI `file:...?mode=ro`
- read-only 모드에서는 schema creation/PRAGMA write 동작 금지

### 3.4 실패 시 rollback/finally가 부족하다

extractor/build 단계에서 `begin()` 후 예외가 발생하면 rollback과 close가 보장되지 않는다. 지금은 빌드가 성공했지만, 추후 데이터가 일부 깨지거나 parser 예외가 발생하면 lock 또는 partial transaction이 남을 수 있다.

필요:

- `GraphStore.transaction()` context manager
- build 단계 `try/except/finally`
- 실패 시 partial DB 삭제 또는 `.failed`로 이동

### 3.5 Git 작업트리 오염

서브 에이전트의 rsync 과정에서 불필요한 파일이 원격 작업트리에 들어왔다.

확인된 문제:

```text
?? AGENTS.md
?? WORKFLOW.md
?? docs/._...
?? scripts/._...
?? 다수 OCR v2 manual 문서/스크립트
```

이번 GraphDB 커밋에는 GraphDB 관련 파일만 포함해야 한다. Mac resource fork 파일(`._*`)과 무관한 OCR batch 산출물은 절대 staging하지 않는다.

## 4. 다음 단계 목표

다음 작업의 목표는 GraphDB를 바로 LLM prompt에 무분별하게 주입하는 것이 아니다. 먼저 "읽기 전용 Graph Retriever"를 만들고, Graph fact의 신뢰도와 근거를 명확히 구분해 기존 RAG에 안전하게 병합한다.

목표:

1. GraphDB read-only query layer 구현
2. hard query 2개를 LLM 없이 graph result object로 재현
3. graph fact를 `confirmed`, `candidate`, `missing`으로 구분
4. 기존 BM25/Chroma RAG와 optional로 병합
5. 보험금 계산 파이프라인에는 `candidate policy rule`로만 전달
6. Streamlit 관리자 진단에서 graph path와 confidence 표시

## 5. 구현 범위

### 5.1 신규/수정 파일

신규:

```text
src/graph/query_planner.py
src/graph/retriever.py
src/graph/context.py
tests/test_graph_retriever.py
tests/test_graph_query_planner.py
eval/graph_qa.jsonl
scripts/eval_graph_qa.py
```

수정:

```text
src/graph/store.py
src/rag/pipeline.py
src/claim_calculation/pipeline.py
src/ui/streamlit_app.py
scripts/prepare_streamlit_runtime.sh
scripts/check_graph_index.py
```

보고서:

```text
docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md
```

## 6. GraphStore 보강 지시

### 6.1 Read-only 연결

`GraphStore`에 read-only 모드를 추가한다.

요구사항:

- `GraphStore(db_path, readonly=True)` 또는 `GraphStore.open_readonly(db_path)`
- SQLite URI 연결 사용:

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

- read-only 모드에서는 `_init_db()`가 테이블/인덱스를 생성하지 않는다.
- read-only 모드에서 `upsert_*`, `execute`, `begin`, `commit`, `rollback` 중 쓰기 계열 호출 시 명확한 예외를 낸다.
- `query()`만 허용한다.

테스트:

- read-only connection에서 `SELECT` 성공
- read-only connection에서 `upsert_node()` 실패
- 없는 DB를 read-only로 열면 명확한 `FileNotFoundError` 또는 사용자 정의 예외

### 6.2 Transaction context manager

다음 API를 추가한다.

```python
with store.transaction():
    ...
```

요구사항:

- 정상 종료 시 commit
- 예외 발생 시 rollback
- 중첩 transaction은 금지하거나 명확히 처리
- extractor가 직접 `begin()/commit()`을 호출하는 구조를 점진적으로 context manager로 바꾼다.

## 7. Query Planner 설계

### 7.1 Intent

`src/graph/query_planner.py`에 다음 intent를 구현한다.

```text
surgery_grade_lookup
same_grade_surgery_list
category_grade_listing
policy_appendix_payment_lookup
hira_code_lookup
claim_policy_basis_lookup
ordinary_rag
```

초기 버전은 regex/rule 기반으로 충분하다. LLM-based planner는 금지한다.

### 7.2 Entity extraction

필수 추출:

- 수술명 후보
- 등급 시스템: `1-3종`, `1-5종`, `신1-5종`
- 등급 값: `1~5`, `N`
- 카테고리: `소화기계`, `호흡기계`, `흉부`, `비뇨기계` 등
- 상품/약관 키워드: `SOL`, `처음건강보험`, `별표7`
- 수가코드 후보: `QZ966` 등

예:

```python
GraphQueryPlan(
    intents=["surgery_grade_lookup", "same_grade_surgery_list", "policy_appendix_payment_lookup"],
    procedure_name="기관지 식도루 폐쇄술",
    grade_system="신1-5종",
    requested_peer_count=3,
    policy_product="자사_SOL건강",
    appendix="별표7",
)
```

## 8. Graph Retriever 설계

### 8.1 반환 데이터 구조

`src/graph/retriever.py`는 LLM 문자열이 아니라 구조화 결과를 반환한다.

```python
@dataclass
class GraphFact:
    subject: str
    relation: str
    object: str
    confidence: float
    status: Literal["confirmed", "candidate", "missing"]
    evidence: list[GraphEvidence]
    properties: dict

@dataclass
class GraphRetrievalResult:
    plan: GraphQueryPlan
    facts: list[GraphFact]
    source_chunk_ids: list[str]
    warnings: list[str]
    debug: dict
```

### 8.2 Confidence policy

다음 정책을 적용한다.

```text
confirmed:
  - exact normalized name/code match
  - graph edge confidence >= 1.0
  - evidence exists

candidate:
  - partial keyword match
  - confidence < 1.0
  - category-level inferred match

missing:
  - 요청 필드가 graph에 없음
  - 수가코드 또는 지급비율 연결이 없음
```

현재 `POLICY_COVERS_PROCEDURE` 432개는 전부 `confidence=0.8`이므로 `candidate`로 취급한다.

### 8.3 Hard Query 1 처리

질문:

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고,
이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘.
그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.
```

필수 결과:

- `기관지 식도루 폐쇄술`: `신1-5종 4종`
- 같은 `신1-5종 4종` peer procedures 3개 이상
- 각 peer의 category
- SOL [별표7] 동일 대분류 후보 표시
- policy rule은 `candidate`로 표시
- evidence page/chunk 표시

금지:

- SOL [별표7] 후보를 확정 지급비율처럼 단정
- `candidate` edge를 `confirmed`처럼 답변

### 8.4 Hard Query 2 처리

질문:

```text
신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을
소화기계 카테고리에서 모두 나열해줘.
각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.
```

필수 결과:

- 소화기계 + `신1-5종 5종` 수술 목록
- 현재 확인된 수술:
  - `간장 이식수술`
  - `췌장 이식수술`
- 각 수술별:
  - 수가코드가 있으면 표시
  - 없으면 `missing`으로 표시
  - SOL [별표7] 지급비율 연결이 있으면 `candidate` 또는 `confirmed` 상태와 함께 표시
  - 없으면 `missing`으로 표시

금지:

- 전체 `HAS_MEDICAL_FEE_CODE` count만 보고 각 수술별 수가코드가 있다고 간주
- 전체 `PAYS_BY_RATIO` count만 보고 각 수술별 지급비율이 있다고 간주

## 9. Graph Context 생성

`src/graph/context.py`는 `GraphRetrievalResult`를 LLM prompt용 텍스트로 변환한다.

형식:

```text
[구조화 그래프 사실]
1. confirmed
- subject: 기관지 식도루 폐쇄술
- relation: HAS_GRADE
- object: 신1-5종 4종
- evidence: 실무가이드 p.79, chunk_id=...

2. candidate
- subject: SOL [별표7] 18번
- relation: POLICY_COVERS_PROCEDURE
- object: 기관지 식도루 폐쇄술
- reason: category+keyword partial match, matched_keyword=기관
- evidence: 자사_SOL건강 p.384, chunk_id=...
```

Prompt 규칙:

- `confirmed`는 답변 근거로 사용 가능
- `candidate`는 "후보", "동일 대분류 기준 가능성"으로 표현
- `missing`은 "GraphDB에서 연결을 확인하지 못함"으로 표현
- LLM이 candidate를 확정 표현으로 바꾸지 못하도록 system/user prompt에 명시

## 10. RAG 파이프라인 통합

### 10.1 Config

`src/config.py`에 다음을 추가하거나 기존 환경변수를 확인한다.

```env
GRAPH_ENABLED=true
GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite
GRAPH_REQUIRE_EVIDENCE=true
GRAPH_ALLOW_CANDIDATE_POLICY=true
GRAPH_CONTEXT_TOP_K=20
```

### 10.2 `src/rag/pipeline.py`

통합 원칙:

- GraphDB는 optional dependency다.
- GraphDB 누락/손상 시 기존 RAG는 계속 동작한다.
- Graph facts는 기존 `structured_context`보다 앞에 배치한다.
- Graph facts의 source chunk id가 있으면 기존 retrieved chunks와 병합한다.
- 관리자 debug에 graph result를 포함한다.

Pseudo flow:

```text
question
  -> graph_result = GraphRetriever.retrieve(question) if enabled
  -> graph_context = build_graph_context(graph_result)
  -> existing retrieval
  -> merge graph evidence chunks + BM25/Chroma chunks
  -> LLM answer
```

### 10.3 보험금 계산 통합

`src/claim_calculation/pipeline.py`에 graph basis hook을 추가한다.

원칙:

- `candidate` policy rule은 계산 확정값으로 사용하지 않는다.
- 계산 planner에는 candidate rule을 "검토 후보"로만 전달한다.
- 지급예상액 산식에 policy rule이 직접 반영되려면 `confirmed` 또는 사용자 선택이 필요하다.

## 11. Streamlit UI 통합

### 11.1 관리자 진단

관리자 화면에 다음 expander를 추가한다.

```text
GraphDB 진단
- graph enabled
- graph db path
- manifest build_date
- matched intents
- matched entities
- confirmed facts
- candidate facts
- missing facts
- evidence coverage
```

### 11.2 일반 사용자 답변

일반 사용자에게는 복잡한 그래프 용어를 노출하지 않는다.

표현 예:

```text
구조화 근거:
- 실무가이드 p.79: 기관지 식도루 폐쇄술은 신1-5종 4종입니다.
- SOL 처음건강보험 [별표7] p.384: 동일 대분류 후보 조항은 18번입니다. 이 연결은 수술명 직접 일치가 아니라 동일 대분류/키워드 기반 후보입니다.
```

## 12. 평가 및 테스트

### 12.1 신규 eval

`eval/graph_qa.jsonl` 생성:

- `graph_001_bronchial_esophageal_fistula_grade_peers`
- `graph_002_digestive_grade5_with_codes_and_payment_ratio`
- `graph_003_robot_code_doc_split`
- `graph_004_sol_appendix_18_19_split`
- `graph_005_missing_fee_code_must_not_hallucinate`

### 12.2 Unit tests

필수:

```bash
.venv/bin/pytest tests/test_graph_query_planner.py tests/test_graph_retriever.py -v
.venv/bin/pytest tests/test_graph_extractors.py tests/test_graph_store.py -v
```

추가 검증:

- read-only store test
- missing GraphDB fallback test
- candidate policy rule가 confirmed로 승격되지 않는 test
- Q2에서 수술별 수가코드 missing을 정확히 표시하는 test

### 12.3 Integration tests

```bash
.venv/bin/python scripts/check_graph_index.py
.venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
.venv/bin/pytest -q
```

대형 LLM/vLLM/SGLang 기동은 이번 단계 필수 검증이 아니다. Graph retrieval은 LLM 없이 먼저 검증한다.

## 13. Git 작업트리 정리 지시

현재 원격 작업트리는 rsync 부산물로 오염되어 있다. 다음을 지킨다.

### 13.1 절대 staging 금지

```text
docs/._*
scripts/._*
AGENTS.md
WORKFLOW.md
docs/67A_*
docs/67B_*
scripts/generate_v2_manual_batch_plan.py
scripts/prepare_v2_manual_batch.py
scripts/render_v2_manual_batch_pages.py
scripts/validate_v2_manual_batch.py
data/index/graph/insurance_graph.sqlite*
```

### 13.2 GraphDB 관련 staging 후보

다음만 후보로 본다.

```text
docs/108_GRAPHDB_HYBRID_RAG_IMPLEMENTATION_SPEC.md
docs/109_GRAPHDB_HYBRID_RAG_IMPL_REPORT.md
docs/110_GRAPHDB_REVIEW_AND_NEXT_INTEGRATION_SPEC.md
src/graph/
scripts/build_graph_index.py
scripts/check_graph_index.py
tests/test_graph_extractors.py
tests/test_graph_normalizer.py
tests/test_graph_store.py
```

다음 단계 구현 후 추가 후보:

```text
src/graph/query_planner.py
src/graph/retriever.py
src/graph/context.py
tests/test_graph_query_planner.py
tests/test_graph_retriever.py
scripts/eval_graph_qa.py
eval/graph_qa.jsonl
docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md
```

## 14. Acceptance Criteria

다음 조건을 모두 만족해야 다음 단계 완료로 본다.

- GraphDB read-only connection 구현 및 테스트 통과
- hard query 2개가 LLM 없이 `GraphRetrievalResult`로 재현됨
- `candidate` policy rule이 답변/계산에서 확정값처럼 쓰이지 않음
- Q2에서 수술별 수가코드와 지급비율이 없을 때 `missing`으로 명시됨
- GraphDB 누락 시 기존 RAG와 보험금 계산 UI가 깨지지 않음
- `pytest -q` 통과
- `scripts/check_graph_index.py` 통과
- `scripts/eval_graph_qa.py` 통과
- 구현 보고서 `docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md` 작성

## 15. 자체 검토 결과

현재 구현은 GraphDB 생성 파이프라인의 PoC로는 성공이다. 다만 프로젝트의 목적은 "복합 질의 답변 강화"와 "보험 보상금 계산 정확도 향상"이므로, 다음 단계에서는 graph edge 존재 자체보다 신뢰도 상태와 근거 표시가 중요하다.

특히 보험금 계산 기능에서는 candidate policy rule을 산식에 직접 반영하면 위험하다. 따라서 다음 구현의 핵심은 graph retrieval을 만드는 것이 아니라, graph fact의 신뢰도 경계를 UI와 LLM prompt, 계산 planner에 끝까지 보존하는 것이다.
