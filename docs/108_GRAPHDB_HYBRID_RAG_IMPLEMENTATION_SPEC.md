# 108. GraphDB Hybrid RAG Implementation Spec

작성일: 2026-05-22
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
대상 작업자: Antigravity 서브 에이전트
작업 성격: GraphDB/GraphRAG 설계 명세 및 구현 지시

## 1. 목적

현재 챗봇은 BM25, Chroma VectorDB, 구조화 테이블 직접 조회, LLM 생성 로직을 조합해 보험 문서 질의에 답한다. 그러나 다음과 같은 복합 질의에서는 벡터 검색만으로 필요한 행, 관계, 같은 등급/같은 대분류의 주변 사실을 안정적으로 모으기 어렵다.

1. `기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.`
2. `신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.`

이번 작업의 목표는 VectorDB를 대체하는 것이 아니라, 문서의 구조화 사실을 GraphDB로 추가 색인하고 RAG 파이프라인이 다음 정보를 함께 참고하게 만드는 것이다.

- 수술명, 수술해설, 1-3종, 1-5종, 신1-5종
- 수술 대분류/중분류/소분류 또는 문서상 상위 항목
- 심평원 수가코드/행위코드
- SOL 처음건강보험 [별표7] 등 약관 별표의 지급비율/담보명/분류
- 원본 chunk, 문서명, 페이지, OCR v1/v2 보정 상태
- 같은 등급, 같은 카테고리, 같은 수가코드, 같은 약관 지급 기준의 관계

## 2. 외부 방법론 조사 요약

### 2.1 Microsoft GraphRAG

Microsoft GraphRAG는 문서에서 엔티티 knowledge graph를 만들고, 관련 엔티티/관계/텍스트 chunk를 함께 검색해 답변 컨텍스트를 구성한다. 공식 문서의 Local Search는 구조화된 graph data와 원문 text chunks를 결합해 특정 엔티티 중심 질문에 답하는 방식이라고 설명한다.

설계 반영:

- 우리 프로젝트의 1차 목표는 Global Search보다 Local Search다.
- 질문에서 수술명, 등급, 카테고리, 상품명, 별표명을 엔티티로 잡고, 관련 노드와 관계를 따라가며 필요한 표 행을 수집한다.
- Graph 사실과 원문 chunk를 함께 답변 컨텍스트에 넣는다.

참고:

- https://microsoft.github.io/graphrag/query/overview/
- https://microsoft.github.io/graphrag/query/local_search/
- https://arxiv.org/abs/2404.16130

### 2.2 Neo4j GraphRAG

Neo4j의 GraphRAG 설명은 GraphRAG가 엔티티와 관계를 추출해 knowledge graph를 만들고, 검색 단계에서 graph와 vector search를 함께 사용해 더 관련성 높은 정보를 탐색하는 패턴이라고 설명한다. GraphAcademy는 vector search로 시작점을 찾고 graph traversal로 관련 노드를 확장하는 흐름을 제시한다.

설계 반영:

- 기존 Chroma/BM25 hit를 graph traversal의 시작점으로 사용할 수 있다.
- 반대로 graph structured query로 정확한 행을 찾고, 해당 source chunk를 BM25/Chroma 컨텍스트와 병합할 수도 있다.
- 복잡한 질의는 `vector -> graph expansion -> evidence-ranked context`와 `graph exact query -> source chunk expansion` 두 경로를 모두 지원한다.

참고:

- https://neo4j.com/labs/genai-ecosystem/graphrag/
- https://graphacademy.neo4j.com/courses/genai-fundamentals/2-rag/4-graphrag/
- https://neo4j.com/developer/genai-ecosystem/graphrag-python/

### 2.3 LlamaIndex PropertyGraphIndex

LlamaIndex의 Property Graph Index는 label이 있는 node와 property, relationship으로 지식을 구성하고, chunk 단위에서 entity/relation을 추출하거나 기존 node relationship metadata를 이용하는 구조를 제공한다.

설계 반영:

- 우리 프로젝트는 OCR table_json, Parquet table index, SQLite 표준코드 DB처럼 이미 구조화된 자료가 있으므로 LLM 기반 triple extraction을 기본값으로 쓰지 않는다.
- Phase 1에서는 deterministic extractor를 우선하고, LLM extraction은 낮은 confidence 후보 검토용으로만 둔다.

참고:

- https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/

### 2.4 LangChain Neo4j Text-to-Cypher

LangChain Neo4j 예시는 자연어 질문에서 Cypher를 생성해 graph DB를 질의하는 패턴을 제공하지만, 생성된 query가 schema 밖의 관계나 속성을 쓰지 않도록 제한하는 prompt와 validation이 필요하다.

설계 반영:

- 초기 버전에서 LLM-generated Cypher/SQL은 금지한다.
- 질의 유형별로 안전한 Python query planner와 parameterized SQL만 사용한다.
- 추후 Text-to-Cypher를 쓰더라도 admin-only 실험 모드로 분리한다.

참고:

- https://docs.langchain.com/oss/python/integrations/graphs/neo4j_cypher

## 3. 프로젝트 현황 진단

### 3.1 이미 존재하는 구조화 자산

현재 DGX 프로젝트에는 다음 자산이 존재한다.

- `data/processed/chunks.jsonl`
- `data/processed/chunks_v2_manual.jsonl`
- `data/processed/chunks_v1_v2_combined.jsonl`
- `data/index/bm25.pkl`
- `data/index/chroma/`
- `data/index_v2_manual/`
- `data/index_v1_v2_combined/`
- `data/index/relational/standard_codes.sqlite`
- `data/mapping/v1_v2_pairs_실무가이드.jsonl`
- `data/mapping/v1_v2_pairs_상담사례집.jsonl`
- `data/index/surgery_grades.parquet` 생성 스크립트: `scripts/build_table_index.py`
- 수술종수/장해율 직접 조회 인터페이스: `src/rag/table_store.py`

### 3.2 현재 한계

현재 `TableStore.lookup_surgery_grade()`는 특정 수술명 1건을 찾는 데는 유용하지만, 다음 기능에는 부족하다.

- 같은 `신1-5종` 등급에 속하는 다른 수술 나열
- `소화기계` 같은 상위 카테고리 기준 필터링
- 실무가이드 수술종수표 행과 SOL 건강보험 [별표7] 행의 연결
- 수술명과 수가코드의 동의어/약칭/표기 차이 해소
- 복수 문서의 충돌/차이를 graph path로 설명
- 보험금 계산 파이프라인에서 지급비율, 한도, 면책 조건을 구조화 근거로 주입

### 3.3 기본 판단

처음부터 Neo4j 서버를 도입하지 않는다. 이 프로젝트는 완전 오프라인 실행과 단일 wrapper 실행을 중시하고, Docker를 쓰지 않는 운영 경로를 이미 선택했다. Phase 1 GraphDB는 Python 표준 라이브러리로 접근 가능한 SQLite property graph로 구축한다.

이 선택의 이유:

- 별도 서비스 없이 로컬/망분리 실행 가능
- SQLite는 이미 `standard_codes.sqlite` 운영 경험이 있음
- 작은 팀/최대 4명 동시 사용 조건에서 충분한 성능 예상
- 그래프 스키마와 extractor 품질을 먼저 검증한 뒤 Neo4j export 여부 결정 가능

Neo4j는 Phase 6의 선택적 export/시각화/고급 traversal 대상으로만 둔다.

## 4. 목표 아키텍처

```text
원본 OCR/보정본/문서 chunk
  -> 기존 ingest: BM25 + Chroma
  -> 신규 graph build:
       - table_json / Parquet / SQLite / metadata extractor
       - surgery/policy/code entity normalization
       - graph_nodes / graph_edges / graph_evidence 저장

질문
  -> intent classifier
  -> graph planner
       - entity lookup
       - exact structured query
       - graph expansion
       - evidence source chunk 수집
  -> 기존 BM25/Vector retrieval
  -> graph facts + RAG chunks 병합/rerank
  -> LLM 답변 생성
  -> evidence validation
```

## 5. GraphDB 저장 방식

### 5.1 파일 위치

기본 산출물:

```text
data/index/graph/insurance_graph.sqlite
data/index/graph/insurance_graph_manifest.json
reports/graph/graph_build_report.json
reports/graph/graph_low_confidence_edges.jsonl
```

주의:

- `data/index/graph/*.sqlite`는 대용량/생성 산출물이므로 Git 커밋 대상이 아니다.
- `reports/graph/*`는 크기가 작고 재현성에 도움이 되면 커밋 가능하나, 개인정보나 원문 대량 복사본을 넣지 않는다.

### 5.2 SQLite property graph 스키마

```sql
CREATE TABLE graph_nodes (
  node_id TEXT PRIMARY KEY,
  node_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  properties_json TEXT NOT NULL DEFAULT '{}',
  confidence REAL NOT NULL DEFAULT 1.0,
  created_by TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE graph_aliases (
  alias_id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  FOREIGN KEY(node_id) REFERENCES graph_nodes(node_id)
);

CREATE TABLE graph_edges (
  edge_id TEXT PRIMARY KEY,
  source_node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  properties_json TEXT NOT NULL DEFAULT '{}',
  confidence REAL NOT NULL DEFAULT 1.0,
  source_evidence_id TEXT,
  created_by TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(source_node_id) REFERENCES graph_nodes(node_id),
  FOREIGN KEY(target_node_id) REFERENCES graph_nodes(node_id)
);

CREATE TABLE graph_evidence (
  evidence_id TEXT PRIMARY KEY,
  chunk_id TEXT,
  doc_short TEXT NOT NULL,
  doc_name TEXT,
  pdf_filename TEXT,
  page_start INTEGER,
  page_end INTEGER,
  source_version TEXT,
  source_method TEXT,
  table_id TEXT,
  row_index INTEGER,
  row_text TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  confidence REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE graph_node_evidence (
  node_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY(node_id, evidence_id, role)
);

CREATE TABLE graph_edge_evidence (
  edge_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY(edge_id, evidence_id, role)
);

CREATE TABLE graph_build_manifest (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

필수 index:

```sql
CREATE INDEX idx_graph_nodes_type_norm ON graph_nodes(node_type, normalized_name);
CREATE INDEX idx_graph_aliases_norm ON graph_aliases(normalized_alias);
CREATE INDEX idx_graph_edges_type_src ON graph_edges(edge_type, source_node_id);
CREATE INDEX idx_graph_edges_type_dst ON graph_edges(edge_type, target_node_id);
CREATE INDEX idx_graph_evidence_chunk ON graph_evidence(chunk_id);
CREATE INDEX idx_graph_evidence_doc_page ON graph_evidence(doc_short, page_start);
```

## 6. Domain Ontology

### 6.1 Node Types

필수 node type:

- `Document`
- `DocumentSection`
- `Table`
- `TableRow`
- `SurgeryProcedure`
- `SurgeryGrade`
- `SurgeryCategory`
- `MedicalFeeCode`
- `PolicyProduct`
- `PolicyAppendix`
- `PolicyBenefitRule`
- `CoverageItem`
- `NonpayStandardCode`

권장 확장 node type:

- `Diagnosis`
- `BodySystem`
- `ClaimScenario`
- `ExclusionRule`
- `DeductibleRule`
- `LimitRule`

### 6.2 Edge Types

필수 edge type:

- `APPEARS_IN`: entity -> Document/Table/Section
- `HAS_SOURCE_ROW`: entity -> TableRow
- `HAS_GRADE`: SurgeryProcedure -> SurgeryGrade
- `HAS_CATEGORY`: SurgeryProcedure -> SurgeryCategory
- `HAS_MEDICAL_FEE_CODE`: SurgeryProcedure -> MedicalFeeCode
- `DEFINED_IN_APPENDIX`: PolicyBenefitRule -> PolicyAppendix
- `POLICY_COVERS_PROCEDURE`: PolicyBenefitRule -> SurgeryProcedure
- `PAYS_BY_RATIO`: PolicyBenefitRule -> CoverageItem 또는 SurgeryGrade
- `SAME_GRADE_AS`: SurgeryProcedure -> SurgeryProcedure
- `SAME_CATEGORY_AS`: SurgeryProcedure -> SurgeryProcedure
- `CROSS_REFERENCES`: TableRow/PolicyBenefitRule -> TableRow/PolicyBenefitRule
- `HAS_CANONICAL_SOURCE`: v1 TableRow -> v2 TableRow

### 6.3 속성 규칙

`SurgeryProcedure` properties:

```json
{
  "procedure_name": "기관지 식도루 폐쇄술",
  "procedure_name_raw": "...",
  "description": "...",
  "grade_1_3": "N|1|2|3",
  "grade_1_5": "N|1|2|3|4|5",
  "grade_new_1_5": "N|1|2|3|4|5",
  "category_path": ["소화기계", "..."],
  "source_doc_priority": "v2_manual",
  "source_page_label": 123
}
```

`MedicalFeeCode` properties:

```json
{
  "code": "QZ966",
  "code_system": "HIRA",
  "name": "로봇 보조 수술 ...",
  "doc_specific": true
}
```

`PolicyBenefitRule` properties:

```json
{
  "product_name": "신한 SOL 처음건강보험(무배당)(자동갱신형)",
  "appendix_name": "별표7",
  "benefit_name": "...",
  "payment_ratio": "100%",
  "payment_ratio_numeric": 1.0,
  "limit_text": "...",
  "condition_text": "...",
  "exclusion_text": ""
}
```

## 7. Extractor 설계

### 7.1 기본 원칙

- LLM extraction을 1차 사실 생성기로 쓰지 않는다.
- OCR `table_json`, 기존 Parquet, SQLite, chunk metadata에서 deterministic extraction을 먼저 수행한다.
- 추출 confidence가 낮은 row는 graph에 넣더라도 `confidence < 0.8`로 표시하고 `reports/graph/graph_low_confidence_edges.jsonl`에 남긴다.
- v2 manual 보정본이 있으면 v2를 canonical로 우선한다.
- v1 원본은 보조 evidence로 연결한다.

### 7.2 Surgery Grade Extractor

입력 후보:

- `data/index/surgery_grades.parquet`
- `data/processed/chunks_v2_manual.jsonl`
- `data/processed/chunks_v1_v2_combined.jsonl`
- 원본 table JSON: `data/extracted/실무가이드/tables/*.json`

추출 항목:

- 수술명
- 수술해설
- `1-3종`
- `1-5종`
- `신1-5종`
- 페이지
- table file / row index
- 문서상 category path

필수 개선:

- 기존 `scripts/build_table_index.py`는 수술명과 등급은 뽑지만 상위 category path가 약하다. GraphDB builder는 chunk metadata의 `volume`, `part`, `chapter`, `section` 및 table 주변 텍스트를 이용해 `SurgeryCategory`를 최대한 채워야 한다.
- category path를 확정할 수 없으면 빈 값으로 두고 low confidence report에 남긴다.

### 7.3 HIRA Code Extractor

입력 후보:

- `data/processed/chunks_v2_manual.jsonl`
- `data/processed/chunks_v1_v2_combined.jsonl`
- chunk metadata의 `codes`, `is_code_table`
- 본문 code regex

추출 항목:

- 코드
- 코드명 또는 행위명
- 코드가 나온 문서/페이지/표 행
- 카테고리 path

주의:

- 심평원 코드와 약관 별표 코드는 같은 문자열처럼 보여도 문서별 의미가 다를 수 있다.
- 따라서 `MedicalFeeCode`에는 `code_system`, `doc_short`, `doc_specific`를 속성으로 둔다.
- 로봇수술처럼 문서별 코드가 충돌하는 경우 통합하지 않고 별도 node 또는 별도 edge evidence로 분리한다.

### 7.4 SOL Policy Appendix Extractor

입력 후보:

- `자사_SOL건강` chunks
- `[별표7]` 또는 `별표 7` 주변 chunk
- 약관 PDF table_json이 있으면 우선 사용

추출 항목:

- 상품명
- 별표명
- 담보명/수술분류명
- 대분류/중분류
- 지급비율/보험금 비율
- 조건/한도/면책 문구
- 수가코드 또는 수술명 연결 후보

주의:

- 약관 별표의 `대분류`와 실무가이드/심평원 카테고리는 명칭이 다를 수 있다.
- 같은 이름이라는 이유만으로 자동 동일시하지 않는다.
- `normalized_name` exact 또는 alias table에 의해 연결된 경우만 strong edge로 만들고, 부분 일치는 candidate edge로 둔다.

### 7.5 Nonpay Standard Code Extractor

입력:

- `data/index/relational/standard_codes.sqlite`

추출 항목:

- `std_cd`, `std_cd_nm`
- 중분류, 진료유형, 의료분류, item class level
- 보상 의견, notes, 적용기간

역할:

- 보험금 계산 기능에서 항목 식별과 보상 의견을 graph node로 연결한다.
- 단, 병원별 실제 금액은 여기에 없으므로 지급예상액 산술 원천으로 쓰지 않는다.

## 8. 신규 모듈 및 스크립트

### 8.1 신규 패키지

```text
src/graph/
  __init__.py
  normalizer.py
  schema.py
  store.py
  extractors.py
  build.py
  retriever.py
  query_planner.py
  context.py
```

역할:

- `normalizer.py`: 한글/영문/기호 정규화, 수술명 alias, 코드 정규화
- `schema.py`: node/edge/evidence dataclass 및 enum
- `store.py`: SQLite 연결, migration, upsert, query
- `extractors.py`: surgery, HIRA code, SOL appendix, standard code extractor
- `build.py`: graph build orchestration
- `retriever.py`: graph facts 조회 및 path expansion
- `query_planner.py`: 질문 유형 분류와 parameterized graph query 생성
- `context.py`: LLM prompt에 넣을 graph fact block 생성

### 8.2 신규 스크립트

```text
scripts/build_graph_index.py
scripts/check_graph_index.py
scripts/eval_graph_qa.py
```

`build_graph_index.py` 요구사항:

```bash
.venv/bin/python scripts/build_graph_index.py \
  --chunks-path data/processed/chunks_v1_v2_combined.jsonl \
  --standard-code-db data/index/relational/standard_codes.sqlite \
  --output data/index/graph/insurance_graph.sqlite \
  --manifest data/index/graph/insurance_graph_manifest.json \
  --low-confidence-report reports/graph/graph_low_confidence_edges.jsonl
```

옵션:

- `--source-mode default|v2_only|v1_v2_combined`
- `--rebuild`
- `--skip-standard-codes`
- `--skip-policy-appendix`
- `--skip-hira-codes`
- `--strict`

`check_graph_index.py` 요구사항:

```bash
.venv/bin/python scripts/check_graph_index.py \
  --graph data/index/graph/insurance_graph.sqlite
```

출력해야 할 항목:

- node/edge/evidence count
- node type별 count
- edge type별 count
- low confidence count
- hard query fixture coverage
- graph manifest의 chunks hash/index mode

`eval_graph_qa.py` 요구사항:

```bash
.venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
```

LLM 호출 없이 graph retrieval 결과만 채점하는 모드가 기본이어야 한다.

## 9. RAG 파이프라인 통합

### 9.1 Config

`src/config.py`에 다음 환경변수를 추가한다.

```env
GRAPH_ENABLED=true
GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite
GRAPH_STRICT_MODE=true
GRAPH_CONTEXT_TOP_K=20
GRAPH_MAX_EXPANSION_DEPTH=2
GRAPH_REQUIRE_EVIDENCE=true
```

오프라인 실행 wrapper와 `scripts/prepare_streamlit_runtime.sh`에는 GraphDB 존재 확인을 추가한다.

### 9.2 Retrieval 흐름

`src/rag/pipeline.py`에 graph retrieval을 다음 방식으로 추가한다.

```text
question
  -> existing query expansion
  -> graph intent classify
  -> if graph intent:
       graph facts = GraphRetriever.retrieve(question)
       graph evidence chunks = graph facts source chunks
  -> existing dense/BM25 retrieval
  -> merge graph evidence chunks + vector hits
  -> rerank
  -> structured_context = existing TableStore direct lookup + graph fact block
  -> LLM answer
```

중요:

- 기존 `TableStore` 직접 조회는 제거하지 않는다.
- GraphDB가 없거나 disabled이면 기존 동작으로 graceful fallback한다.
- GraphDB facts가 있는 경우 LLM prompt에 `구조화 그래프 사실` 블록을 RAG chunks보다 위에 배치한다.
- Graph facts는 답변의 numeric/code 사실에 대해 RAG text보다 우선한다.
- 단, Graph facts도 evidence가 없으면 답변에 사용하지 않는다.

### 9.3 Query Intent

최소 intent:

- `surgery_grade_lookup`
- `same_grade_surgery_list`
- `category_grade_listing`
- `policy_appendix_payment_lookup`
- `hira_code_lookup`
- `cross_doc_code_conflict`
- `claim_calculation_basis`
- `ordinary_rag`

질문 예시 매핑:

```text
"기관지 식도루 폐쇄술의 신1-5종 ..."
  -> surgery_grade_lookup + same_grade_surgery_list + policy_appendix_payment_lookup

"5종에 해당하는 수술을 소화기계 카테고리에서 모두 ..."
  -> category_grade_listing + hira_code_lookup + policy_appendix_payment_lookup
```

### 9.4 Graph Context Format

LLM에 넣는 graph context는 아래 형식을 지킨다.

```text
[구조화 그래프 사실]
Fact 1
- subject: 기관지 식도루 폐쇄술
- relation: HAS_GRADE
- object: 신1-5종 5종
- evidence: 실무가이드 p.123, chunk_id=...
- confidence: 0.98

Fact 2
- subject: 기관지 식도루 폐쇄술
- relation: HAS_MEDICAL_FEE_CODE
- object: ...
- evidence: 심평원 p....
- confidence: 0.92
```

금지:

- evidence 없는 fact 사용
- graph fact와 RAG chunk가 충돌할 때 단정 답변
- 문서별 코드 충돌을 통합해서 하나의 코드처럼 답변

## 10. 보험금 계산 기능과의 연결

보험금 계산 파이프라인은 현재 `src/claim_calculation`에 있다. GraphDB 통합 후 다음 흐름을 추가한다.

```text
claim item
  -> standard code matcher
  -> graph lookup by treatment/procedure/code
  -> policy benefit rule candidates
  -> basis selector
  -> planner prompt
  -> code sandbox calculation
```

GraphDB에서 제공할 계산 근거:

- 보장 항목과 약관 별표 지급비율
- 동일 수술/동의어 수술명 매칭
- 수가코드와 수술명 연결
- 면책/한도/자기부담금 후보 조항
- low confidence 또는 복수 후보 여부

계산 결과 원칙:

- LLM은 산술 원천이 아니다.
- LLM planner는 적용 과정과 조건을 JSON으로 제안한다.
- 금액은 Decimal 기반 sandbox에서 계산한다.
- Graph fact confidence가 낮거나 benefit rule 후보가 2개 이상이면 `requires_review=true`로 보류한다.

## 11. UI 통합

Streamlit에 다음을 추가한다.

### 11.1 관리자 진단 Expander

관리자 모드에서만 표시:

- Graph intent
- matched entities
- graph facts
- traversed paths
- evidence coverage
- low confidence warnings
- GraphDB index manifest

### 11.2 일반 사용자 표시

일반 사용자는 답변 하단에 간결한 출처만 본다.

예:

```text
구조화 근거:
- 실무가이드 p.123: 기관지 식도루 폐쇄술, 신1-5종 5종
- SOL 처음건강보험 [별표7] p.300: 해당 수술분류 지급비율 ...
```

## 12. 평가 데이터

신규 파일:

```text
eval/graph_qa.jsonl
```

필수 문항:

```json
{
  "id": "graph_001_bronchial_esophageal_fistula_grade_peers",
  "question": "기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.",
  "required_intents": ["surgery_grade_lookup", "same_grade_surgery_list", "policy_appendix_payment_lookup"],
  "must_have_fields": ["procedure", "grade_new_1_5", "peer_procedures", "same_policy_category_marker", "evidence"],
  "review_type": "graph_auto_then_human"
}
```

```json
{
  "id": "graph_002_digestive_grade5_with_codes_and_payment_ratio",
  "question": "신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.",
  "required_intents": ["category_grade_listing", "hira_code_lookup", "policy_appendix_payment_lookup"],
  "must_have_fields": ["category", "grade_new_1_5", "procedure_list", "medical_fee_code", "payment_ratio", "evidence"],
  "review_type": "graph_auto_then_human"
}
```

추가 문항:

- 로봇수술 심평원 코드와 SOL 건강 약관 코드 분리
- 도수치료 표준코드, 약관 한도, SOL 건강 보장 제외/조건 비교
- 장해율 분류와 지급률의 주변 항목 나열
- 같은 수가코드가 여러 문서에 등장할 때 문서별 의미 차이 구분

## 13. 테스트 계획

### 13.1 Unit Tests

신규 테스트:

```text
tests/test_graph_normalizer.py
tests/test_graph_store.py
tests/test_graph_extractors.py
tests/test_graph_retriever.py
tests/test_graph_query_planner.py
tests/test_graph_pipeline_integration.py
```

필수 검증:

- node/edge upsert idempotent
- alias lookup
- evidence 없는 fact 거부
- 같은 등급 peer procedure 조회
- category + grade filter 조회
- policy appendix payment ratio 연결
- GraphDB 없음 fallback
- GraphDB disabled fallback
- LLM 호출 없이 `eval_graph_qa.py` 실행 가능

### 13.2 Integration Tests

명령:

```bash
.venv/bin/pytest tests/test_graph_*.py -v
.venv/bin/python scripts/build_graph_index.py --source-mode v1_v2_combined --rebuild
.venv/bin/python scripts/check_graph_index.py --graph data/index/graph/insurance_graph.sqlite
.venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

최종 회귀:

```bash
.venv/bin/pytest -q
```

대형 LLM/SGLang/vLLM 직접 기동은 이번 GraphDB 구현 검증의 필수 조건이 아니다.

## 14. 구현 단계

### Phase 0. Data Audit

목표:

- Graph로 만들 수 있는 실제 필드를 확인한다.
- hard query 2개에 필요한 원문 위치를 수동으로 1회 조사한다.

작업:

- `rg`로 `기관지 식도루`, `폐쇄술`, `소화기계`, `별표7`, `신1-5종` 위치 확인
- `data/index/surgery_grades.parquet` 존재 여부 및 컬럼 확인
- SOL 건강 [별표7] table_json 또는 chunk 위치 확인
- 발견 결과를 `reports/graph/data_audit_report.json`에 저장

### Phase 1. Graph Store

목표:

- SQLite graph schema와 store API 구현

작업:

- `src/graph/schema.py`
- `src/graph/store.py`
- migration function
- idempotent upsert
- query helpers
- unit tests

### Phase 2. Deterministic Extractors

목표:

- 수술종수, 수가코드, SOL 별표, 비급여 표준코드의 1차 graph 생성

작업:

- `SurgeryGradeExtractor`
- `HiraCodeExtractor`
- `PolicyAppendixExtractor`
- `NonpayStandardExtractor`
- evidence 연결
- low confidence report

### Phase 3. Build/Check Scripts

목표:

- 한 번의 명령으로 GraphDB 생성/검증

작업:

- `scripts/build_graph_index.py`
- `scripts/check_graph_index.py`
- manifest 생성
- `scripts/prepare_streamlit_runtime.sh`에 GraphDB 체크 옵션 추가

### Phase 4. Graph Retriever

목표:

- 질의 유형별로 Graph facts를 가져오는 retriever 구현

작업:

- `src/graph/query_planner.py`
- `src/graph/retriever.py`
- `src/graph/context.py`
- hard query 2개 fixture 기반 테스트

### Phase 5. RAG/Claim Pipeline Integration

목표:

- 기존 RAG 파이프라인과 보험금 계산 파이프라인에 graph context를 주입

작업:

- `src/rag/pipeline.py`에 optional graph retrieval 추가
- `src/claim_calculation/pipeline.py`에 optional graph facts basis 추가
- prompt에는 graph fact block을 추가하되, 기존 citation/evidence warning 로직 유지

### Phase 6. UI/Admin Diagnostics

목표:

- 사용자 답변에는 간결한 구조화 근거 표시
- 관리자에게 graph path와 confidence 진단 제공

작업:

- `src/ui/streamlit_app.py` 관리자 expander 추가
- GraphDB 상태 표시
- GraphDB 없음/오래됨 경고

### Phase 7. Optional Neo4j Export

목표:

- 필요할 때 Neo4j Browser 또는 고급 Cypher 실험 가능

작업:

- `scripts/export_graph_to_neo4j_csv.py`
- 이 단계는 기본 운영 필수가 아니며 Docker/Neo4j 서버를 요구하지 않는다.

## 15. Acceptance Criteria

필수:

- `pytest -q` 통과
- `scripts/build_graph_index.py --source-mode v1_v2_combined --rebuild` 성공
- `scripts/check_graph_index.py`가 node/edge/evidence count와 hard query coverage를 출력
- `eval/graph_qa.jsonl`의 hard query 2개에서 graph retrieval 결과가 다음을 포함
  - 대상 수술명
  - 신1-5종 등급
  - 같은 등급 peer procedures
  - 소화기계/대분류 category
  - 수가코드 또는 missing reason
  - SOL 별표 지급비율 또는 missing reason
  - evidence page/chunk
- GraphDB 파일이 없으면 기존 RAG가 깨지지 않음
- 오프라인 모드에서 외부 네트워크 호출 없음

금지:

- 모델 파일, Chroma DB, Graph SQLite 산출물을 Git에 커밋
- evidence 없는 graph fact를 답변에 사용
- 문서별 충돌 코드를 임의 통합
- LLM-generated SQL/Cypher를 기본 경로에서 실행
- 기존 보험금 계산 UI와 Streamlit lazy loading 회귀

## 16. 서브 에이전트 작업 지시

작업 시작 전 반드시 읽을 파일:

```text
src/rag/pipeline.py
src/rag/table_store.py
scripts/build_table_index.py
src/claim_calculation/pipeline.py
src/claim_calculation/basis_selector.py
src/claim_calculation/planner.py
src/llm/prompt.py
src/retrieval/index_mode.py
scripts/build_ocr_combined_chunks.py
scripts/build_v1_v2_pair_mapping.py
scripts/prepare_streamlit_runtime.sh
docs/97_CLAIM_PAYOUT_CALCULATION_PIPELINE_SPEC.md
docs/99_CLAIM_CALCULATION_FIX_AND_STABILIZATION_SPEC.md
docs/103_STREAMLIT_RUNTIME_PREP_GUIDE.md
docs/106_GEMMA4_VLLM_STREAMING_FIX_REPORT.md
```

작업 원칙:

- DGX Spark `/srv/shared/projects/insurance-rag-chatbot`에서만 작업한다.
- Mac 로컬 프로젝트를 기준 저장소로 쓰지 않는다.
- 기존 untracked OCR v2 manual batch 산출물은 만지지 않는다.
- `.venv`, `.venv-sglang`, `.venv-vllm`, `data/index/graph/*.sqlite`, 모델 파일은 커밋하지 않는다.
- 수정 후 구현 보고서를 `docs/109_GRAPHDB_HYBRID_RAG_IMPL_REPORT.md`로 작성한다.
- 커밋/push는 별도 승인 전까지 수행하지 않는다.

## 17. 자체 검토 및 보정 내역

### Review Pass 1

문제:

- 처음 설계는 Neo4j 도입을 고려했으나, 현재 프로젝트의 완전 오프라인/비 Docker 운영 조건과 맞지 않는다.

보정:

- Phase 1은 SQLite property graph로 확정하고 Neo4j는 optional export로 낮췄다.

### Review Pass 2

문제:

- GraphRAG 일반론을 그대로 적용하면 LLM extraction이 숫자/코드 사실의 출처가 될 위험이 있다.

보정:

- deterministic extractor를 기본으로 하고, LLM extraction은 low confidence 후보/검토 보조로 제한했다.

### Review Pass 3

문제:

- GraphDB가 없거나 오래된 상태에서 Streamlit이 다시 막힐 수 있다.

보정:

- GraphDB는 optional dependency로 통합하고, disabled/missing 시 기존 RAG fallback을 acceptance criteria에 추가했다.

### Review Pass 4

문제:

- 보험금 계산 기능이 Graph fact를 과신하면 지급예상액이 확정값처럼 보일 수 있다.

보정:

- graph facts는 계산 근거 후보이며, 복수 후보/낮은 confidence는 `requires_review=true`로 처리하도록 명시했다.

최종 판단:

- 이 명세는 현재 프로젝트의 데이터 구조, 오프라인 운영 조건, 기존 RAG/보험금 계산 파이프라인을 보존하면서 GraphDB를 점진적으로 추가하는 계획이다.
- 구현 리스크는 주로 OCR 표 구조와 SOL [별표7] row extraction 정확도에 있으므로 Phase 0 data audit과 low confidence report를 필수 단계로 둔다.
