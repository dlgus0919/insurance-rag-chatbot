# 231. Clause Detail Lookup Source-Grounded 개선 계획

## 목적

`clause_detail_lookup` 실패를 하드코딩 지식 로직 없이 개선한다.

이번 계획은 `semi-adaptive-k`와 분리한다. `semi-adaptive-k`는 검색 청크 수 조절 실험 후보이고, `clause_detail_lookup`은 조항·표·숫자 근거를 구조화해서 읽는 문제다.

## 기존 원칙 문서 확인

확인한 저장소 문서:

- `docs/190_PROJECT_DIRECTION_AND_ONTOLOGY_OPERATING_PLAN.md`
- `docs/214_ONTOLOGY_POLICY_EXTERNALIZATION_PLAN.md`
- `docs/208_DIKW_AI_ORGANIZATIONAL_KNOWLEDGE_PROJECT_PERSPECTIVE.md`
- `docs/230_SEMI_ADAPTIVE_K_AND_CLAUSE_DETAIL_LOOKUP_PLAN.md`

공통 원칙:

- Python 코드에는 보험 개념과 업무 판단 값을 직접 하드코딩하지 않는다.
- 코드는 schema, extractor, validator, retriever, planner, interpreter 같은 일반 처리 방식을 담당한다.
- 보험 지식은 ontology manifest, rule table, GraphDB, evidence metadata, source mapping으로 관리한다.
- raw 문서와 OCR/LLM 추출 결과는 바로 운영 지식이 아니라 후보 또는 근거 데이터로 시작한다.
- 실무자 승인 또는 명시된 검증 절차 없이 active ontology, GraphDB, 계산 rule로 승격하지 않는다.

따라서 `clause_detail_lookup` 개선에서도 다음 방식은 금지한다.

- 질문 문자열에 따라 `80%`, `20%`, `2만원` 같은 값을 직접 반환한다.
- 평가 케이스 ID나 특정 질문 문장에 맞춘 분기를 둔다.
- 약관 개정 시 Python 코드를 수정해야 하는 값 상수를 둔다.
- LLM이 표의 수치나 조건을 추측해 채우게 한다.

허용되는 방식:

- 원문 약관, 보정본 OCR, table metadata, section metadata에서 값을 추출한다.
- 조항·표·행·열·페이지·chunk id를 가진 evidence 객체를 만든다.
- 질문과 evidence row의 매칭 규칙은 일반화하되, 답변 값은 source evidence에서 읽는다.
- LLM은 선택된 근거를 설명하는 역할만 맡고, 값 생성 권한은 갖지 않는다.

## 현재 구현 진단

현재 `clause_detail_lookup`은 `src/rag/search_intent.py`에서 intent로 분기된다. `자기부담금`, `청구서류`, `진단확정` 같은 세부 조항 단서가 감지되면 BM25 비중을 높인다.

하지만 `src/rag/pipeline.py`의 `_deterministic_clause_detail_answer()`는 chunk 텍스트에서 키워드가 포함된 줄을 골라 요약한다. 표의 행/열 관계, 숫자와 조건의 결합, 제3조 `<표1>` 같은 구조를 별도 evidence 객체로 다루지 않는다.

DGX 기준 `data/processed/chunks.jsonl`에는 `약관` p.8-31 범위 chunk가 있고, 요약서에는 `급여(상해) 입원치료`, `보장대상의료비의 20%`, `급여(질병) 통원치료`, `1~2만원`, `20%중 큰 금액` 같은 표현이 포함되어 있다. 즉 완전한 검색 누락이 아니라 구조화 추출과 답변 조립의 문제로 보는 것이 타당하다.

## 웹 조사 요약

최근 표/반구조 문서 RAG 연구 흐름은 일반 chunk 검색만으로는 표 기반 질의의 정확도가 낮고, row/cell/entry 단위의 세밀한 evidence 표현이 필요하다는 방향이다.

- FT-RAG는 복잡한 표 추론을 위해 table을 entry-level semantic unit으로 분해하고 구조적 neighbor expansion을 사용한다.
- HD-RAG는 text와 hierarchical table이 섞인 문서에서 row-and-column level table representation과 2단계 retrieval을 제안한다.
- Structure-Aware RAG 계열은 noisy context를 줄이기 위해 중간 structured table representation을 둔다.
- multi-table retrieval 연구는 query-table relevance만으로는 부족하고 table-table 또는 row/column 구조 관계를 함께 봐야 한다고 지적한다.

우리 프로젝트에는 거대한 새 프레임워크를 도입하기보다, 기존 BM25/Chroma/RRF/reranker 위에 `clause evidence row layer`를 추가하는 방식이 적합하다.

참고:

- https://arxiv.org/abs/2605.01495
- https://arxiv.org/abs/2504.09554
- https://arxiv.org/abs/2605.24366
- https://arxiv.org/abs/2404.09889

## 개선 방식 평가

`docs/230`의 권장안인 조항·표 row manifest, query-to-row matching, evidence-first answer builder, numeric coverage 검증은 기존 하드코딩 금지 원칙에 부합한다.

이유:

- 값은 코드 상수가 아니라 원문/OCR/metadata에서 읽는다.
- 검색과 매칭 규칙은 일반 처리 로직이다.
- evidence provenance가 page, chunk, section, table, row 단위로 남는다.
- 실패 시 값 추측이 아니라 coverage 실패로 처리할 수 있다.
- 약관 개정 시 코드는 유지하고 ingestion/index 산출물만 갱신할 수 있다.

다만 `normalized_terms` 목록을 Python 상수로 크게 늘리면 다시 정책 하드코딩으로 흐를 수 있다. 따라서 query facet과 synonym 정책은 가능하면 `data/ontology/policies/` 또는 별도 `data/rag/policies/clause_detail_policy.json`으로 외부화한다.

## 대안 검토

### 대안 A. Prompt 강화만 수행

검색된 chunk를 그대로 LLM에 주고 "표 값을 정확히 읽으라"고 지시한다.

- 장점: 구현이 빠르다.
- 단점: 표형 OCR 텍스트가 깨지면 숫자와 조건을 잘못 결합할 수 있다.
- 판정: 단독 개선책으로 부적절하다. evidence row 추출 후 표현 보조 용도로만 사용한다.

### 대안 B. Top-K 확대 또는 semi-adaptive-k

더 많은 청크를 넣어 누락 가능성을 낮춘다.

- 장점: 근거 후보가 실제로 누락된 경우에는 효과가 있다.
- 단점: 이번 실패처럼 근거가 이미 있는데 행/숫자 추출이 안 되는 경우에는 본질 해결이 아니다.
- 판정: 보조 실험으로 보류한다.

### 대안 C. 정규식만으로 숫자 추출

`자기부담금`, `%`, `만원` 주변 문장을 정규식으로 추출한다.

- 장점: 빠르고 LLM이 필요 없다.
- 단점: 행/열이 섞인 표에서 잘못된 숫자를 가져올 수 있다.
- 판정: 단독 사용 금지. row evidence 후보 생성의 feature로만 사용한다.

### 대안 D. 조항·표 row evidence layer

약관/OCR chunk에서 조항, 표, row, 숫자, term facet을 분리해 별도 manifest 또는 SQLite table로 저장하고, 질의 시 row 단위로 조회한다.

- 장점: 하드코딩 없이 근거 기반 수치 답변을 만들 수 있다.
- 단점: ingestion/post-processing과 회귀 테스트가 필요하다.
- 판정: 1순위 권장 방식이다.

### 대안 E. GraphDB에 ClauseTableRow 노드 추가

row evidence layer를 GraphDB node/edge로 승격한다.

- 장점: Graph review path와 연결하기 쉽다.
- 단점: 초기 구현 범위가 커지고 rebuild 영향이 있다.
- 판정: 2단계 확장으로 둔다. 1단계에서는 별도 manifest/SQLite로 시작한다.

## 적용 계획

### Phase 0. 재현과 기준선 고정

목표:

- 현재 실패를 다시 재현한다.
- 개선 전후 비교 기준을 고정한다.

작업:

- `policy_xlsx_018`, `policy_xlsx_019`, `policy_xlsx_026`를 clause detail smoke set으로 묶는다.
- 각 케이스의 top hit, doc/page, chunk id, answer preview, required number coverage를 기록한다.
- 보정본 OCR 편입본 `data/processed/chunks.jsonl`을 기본 DB로 사용한다.

성공 기준:

- 현재 실패 원인이 검색 누락인지, row/number extraction 실패인지 케이스별로 분리 기록된다.

### Phase 1. Clause Evidence Row Manifest 생성

새 산출물 후보:

```text
data/index/clause_detail_rows.jsonl
```

또는 조회 성능을 위해:

```text
data/index/clause_detail_rows.sqlite
```

row schema:

```json
{
  "row_id": "약관:p31:article_3:table_1:row_0001",
  "doc_short": "약관",
  "doc_name": "신한 이지로운 실손의료보험 약관",
  "page_start": 31,
  "page_end": 36,
  "section_id": "article_3",
  "section_title": "제3조",
  "table_id": "table_1",
  "table_title": "<표1>",
  "row_text": "원문/OCR에서 추출한 행 또는 행 후보",
  "numbers": ["원문에서 발견된 숫자"],
  "facets": {
    "benefit_type": ["급여", "비급여"],
    "visit_type": ["입원", "통원"],
    "measure_type": ["자기부담금", "공제금액", "보상비율"]
  },
  "source_chunk_id": "약관_ch_...",
  "source": "processed_chunks|table_json|ocr_manifest",
  "extraction_version": "clause-detail-row-v1"
}
```

원칙:

- `numbers`는 정답 상수가 아니라 `row_text`에서 추출된 값이다.
- `facets`는 ontology/policy 기반 동의어를 사용하되, 특정 정답값을 포함하지 않는다.
- manifest 생성은 재현 가능한 script로 수행한다.

예상 파일:

- `src/rag/clause_detail_rows.py`
- `scripts/build_clause_detail_rows.py`
- `tests/test_clause_detail_rows.py`

### Phase 2. Query Facet Extractor

질문에서 다음 facet을 일반 규칙으로 추출한다.

- 문서 범위: 약관, 표준약관, 실무가이드 등
- 조항/표: 제3조, 별표, 표1 등
- 담보/급부: 급여, 비급여, 3대비급여
- 방문 구분: 입원, 통원, 외래, 처방조제
- 측정 대상: 자기부담금, 공제금액, 보상비율, 한도, 필요서류

정책 위치:

```text
data/rag/policies/clause_detail_policy.json
```

Python 코드에는 facet 추출 알고리즘만 두고, synonym/stopword/가중치는 정책 파일에서 읽는다.

### Phase 3. Row Retrieval and Ranking

`clause_detail_lookup` intent에서 기존 chunk retrieval 뒤에 row retrieval을 추가한다.

ranking feature:

- facet 일치 수
- 조항/표 일치
- source chunk가 기존 top hit에 포함되는지
- 숫자 포함 여부
- row_text와 질문의 BM25/token overlap
- 같은 section/table 주변 row 확장

금지:

- 특정 질문이면 특정 row_id를 고르는 분기
- 특정 값이 있으면 무조건 정답으로 쓰는 분기

### Phase 4. Evidence-First Answer Builder

선택된 row evidence를 먼저 만든다.

출력 구조:

```text
제공된 약관 근거 기준으로 답변드립니다.

- 기준 조항/표: ...
- 적용 구분: ...
- 원문 근거: ...
- 확인된 수치: ...

[출처: ...]
```

LLM 사용 정책:

- 기본은 deterministic answer builder다.
- LLM을 사용할 경우 row evidence를 자연어로 정리하는 후처리만 허용한다.
- LLM 출력이 selected row의 숫자 coverage를 만족하지 못하면 deterministic 답변으로 fallback한다.

### Phase 5. Coverage Validator

질문/평가셋이 요구하는 요소를 검사한다.

검증 항목:

- 선택 row의 숫자가 답변에 포함됐는가
- 조항/표가 답변에 포함됐는가
- 입원/통원/급여/비급여 등 핵심 facet이 답변에 포함됐는가
- 답변 숫자가 selected row에 없는 값을 새로 만들지 않았는가

실패 처리:

- row 후보를 max 후보까지 재탐색한다.
- 그래도 실패하면 "근거는 찾았으나 수치 추출이 불안정하다"는 안전 답변을 반환한다.

### Phase 6. 평가와 회귀 테스트

필수 테스트:

- `tests/test_clause_detail_rows.py`
- `tests/test_pipeline.py`의 clause detail 회귀 테스트 확장
- `scripts/eval_auto_rag_params.py` 또는 별도 smoke script로 018/019/026 실행

필수 검증:

```bash
.venv/bin/python -m pytest tests/test_clause_detail_rows.py tests/test_pipeline.py -q
.venv/bin/python scripts/eval_auto_rag_params.py \
  --cases eval/policy_xlsx_qa.jsonl \
  --stage all \
  --index-mode v2_only \
  --label clause_detail_rows_smoke \
  --max-tokens 700
```

성공 기준:

- `policy_xlsx_018`이 `80%`, `20%`, `입원`, `제3조`를 포함한다.
- `policy_xlsx_019`가 `1회`, `20%`, `2만원`, `통원`, `제3조`, `<표1>`을 포함한다.
- 기존 전체 pass rate가 악화되지 않는다.
- 답변의 숫자가 source row에 없는 경우 실패로 기록된다.

## 위험과 대응

| 위험 | 대응 |
|---|---|
| OCR row가 실제 표 행을 잘못 분리함 | 같은 section/table 주변 row expansion, 원문 chunk fallback, coverage warning |
| 정규식이 잘못된 숫자를 잡음 | 숫자 단독이 아니라 facet + row_text + section/table 일치로 ranking |
| 정책 파일이 사실상 지식 하드코딩이 됨 | synonym/stopword/가중치만 정책화하고 정답 수치는 금지 |
| LLM이 근거 밖 숫자를 생성함 | selected row number coverage validator와 deterministic fallback |
| GraphDB rebuild 영향이 커짐 | 1단계는 별도 manifest/SQLite로 시작하고 GraphDB 노드화는 후속 |
| 특정 평가셋 과적합 | 018/019 외 026 및 일반 clause detail 질문을 함께 smoke set에 포함 |

## 최종 권장

즉시 구현할 1순위는 `clause_detail_rows` 보조 evidence layer다. 이 방식은 기존 "하드코딩 지식 로직 금지" 원칙을 지키면서도, 현재 실패 원인인 표/조항 숫자 추출 문제를 직접 해결한다.

`semi-adaptive-k`, prompt 강화, LLM reranking은 보조 수단으로 남긴다. 이들은 근거 후보가 빠지는 문제에는 도움이 될 수 있지만, 표의 행/열/숫자 관계를 운영 가능한 근거로 만드는 문제를 대체하지 못한다.
