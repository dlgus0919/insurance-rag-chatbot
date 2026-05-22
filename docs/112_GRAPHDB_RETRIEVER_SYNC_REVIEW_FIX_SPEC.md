# 112. GraphDB Retriever Sync Review And Fix Spec

작성일: 2026-05-22
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
대상 작업자: Antigravity 서브 에이전트
작업 성격: GraphDB retriever 구현 결과 검토, 원격 동기화 결함 복구, RAG 통합 전 품질 보정 명세

## 1. 결론

`docs/110_GRAPHDB_REVIEW_AND_NEXT_INTEGRATION_SPEC.md`에 따른 다음 단계 구현은 Mac 로컬에서는 상당 부분 진행된 것으로 보이나, DGX 메인 프로젝트 디렉터리에는 핵심 파일이 반영되지 않았다. 또한 로컬 `eval/graph_qa.jsonl`의 첫 번째 hard query 기대값이 질문 의도와 맞지 않아, 보고된 `5/5 cases passed`는 품질 보증으로 인정할 수 없다.

따라서 다음 작업은 새 기능 확장이 아니라 다음 순서로 진행한다.

1. DGX 원격 저장소를 기준으로 구현 파일 누락을 복구한다.
2. `GraphRetriever`의 등급 선택 버그를 수정한다.
3. Graph eval dataset을 질문 의도 기준으로 다시 고친다.
4. RAG/Streamlit/보험금 계산 통합은 안전 gate를 둔 뒤 재검증한다.
5. 작업트리 오염을 정리하고 Graph 관련 파일만 선별 staging 가능한 상태로 만든다.

## 2. 원격 DGX 기준 직접 검토 결과

원격 DGX에서 확인한 명령:

```bash
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && git status --short"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/pytest tests/test_graph_*.py tests/test_streamlit_app.py -q"
```

확인 결과:

```text
scripts/eval_graph_qa.py: 원격에 없음
eval/graph_qa.jsonl: 원격에 없음
src/graph/query_planner.py: 원격에 없음
src/graph/retriever.py: 원격에 없음
src/graph/context.py: 원격에 없음
docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md: 원격에 없음
```

원격에서 실제로 통과한 것은 다음이다.

```text
tests/test_graph_extractors.py
tests/test_graph_normalizer.py
tests/test_graph_store.py
tests/test_streamlit_app.py

결과: 25 passed
```

즉, `GraphRetriever`와 `eval_graph_qa.py`까지 포함한 보고된 검증은 DGX 메인 디렉터리 기준으로 재현되지 않았다.

## 3. Mac 로컬 구현 검토 결과

Mac 로컬에 존재하는 구현 파일은 다음과 같다.

```text
src/graph/query_planner.py
src/graph/retriever.py
src/graph/context.py
scripts/eval_graph_qa.py
eval/graph_qa.jsonl
docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md
```

로컬 구현 자체에도 아래 결함이 있다.

### 3.1 Q1 평가셋 기대값 오류

질문:

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고...
```

그런데 로컬 `eval/graph_qa.jsonl`의 기대 fact는 다음으로 되어 있다.

```json
{
  "subject": "기관지 식도루 폐쇄술",
  "relation": "HAS_GRADE",
  "object": "1-3종 2종",
  "status": "confirmed"
}
```

이것은 질문 의도와 다르다. 기대값은 반드시 다음이어야 한다.

```json
{
  "subject": "기관지 식도루 폐쇄술",
  "relation": "HAS_GRADE",
  "object": "신1-5종 4종",
  "status": "confirmed"
}
```

### 3.2 `GraphRetriever` 등급 선택 버그

로컬 `GraphRetriever.retrieve()`는 수술 노드의 `HAS_GRADE` edge를 모두 가져온 뒤 첫 번째 edge를 사용한다.

문제:

- `기관지 식도루 폐쇄술`에는 `1-3종`, `1-5종`, `신1-5종` edge가 모두 있다.
- 질문에서 `신1-5종`을 물어도 첫 번째 row가 `1-3종 2종`이면 그 값을 반환한다.
- 로컬 eval이 이 잘못된 값을 기대값으로 맞춰서 통과했다.

필수 수정:

- `plan.grade_system`이 있으면 해당 grade system의 edge만 선택한다.
- `plan.grade_system == "신1-5종"`이면 `target_node_id LIKE 'grade_new_1_5_%'` 또는 grade node properties `grade_system='신1-5종'` 조건을 사용한다.
- `plan.grade_system`이 없으면 우선순위를 명시한다.
  1. `신1-5종`
  2. `1-5종`
  3. `1-3종`

### 3.3 `GraphQueryPlanner`의 known procedure list가 너무 좁다

로컬 `GraphQueryPlanner`는 `known_procedures` 리스트에 일부 수술명을 하드코딩한다.

문제:

- GraphDB에 2,369개 수술 노드가 있는데 planner는 일부 예시만 안다.
- 실제 사용자 질문에서 수술명이 조금만 바뀌면 `procedure_name` 추출이 실패하거나 엉뚱한 구문을 잡을 수 있다.

필수 수정:

- planner는 regex로 후보 phrase만 추출한다.
- 실제 수술명 매칭은 `GraphRetriever`가 GraphDB alias/node lookup으로 수행한다.
- `GraphRetriever`는 exact normalized match, alias match, fallback fuzzy candidate를 구분해야 한다.

### 3.4 RAG 통합이 GraphDB 부재 환경에서 import 단계부터 깨질 수 있다

로컬 `src/rag/pipeline.py`는 상단에서 바로 다음 import를 한다.

```python
from src.graph.retriever import GraphRetriever
from src.graph.context import build_graph_context
```

문제:

- DGX 원격에는 아직 해당 파일이 없어 import가 깨진다.
- GraphDB 생성 산출물은 Git에 포함되지 않으므로 신규 checkout에서는 DB가 없을 수 있다.
- `GRAPH_ENABLED=true` 기본값이면 DB 준비 전에도 Graph integration path가 활성화될 수 있다.

필수 수정:

- Graph 관련 import는 optional import로 방어하거나, 파일이 반드시 동기화된 뒤 전체 테스트를 돌린다.
- `GRAPH_ENABLED` 기본값은 `false`로 두거나, wrapper에서 DB 존재 확인 후 true로 켠다.
- 최소한 `GraphRetriever` 초기화 실패가 전체 RAG/Streamlit을 막지 않아야 한다.

### 3.5 `VectorStore.get_by_ids()`는 Chroma ID 누락과 순서 보존을 검증해야 한다

로컬 `VectorStore.get_by_ids()`는 `collection.get(ids=ids)` 결과를 그대로 Hit로 바꾼다.

필수 확인:

- 요청한 ID 중 Chroma에 없는 ID가 있어도 예외 없이 넘어가는가
- 반환 순서가 요청 순서와 같은가
- v1/v2 combined chunk id가 Chroma index mode와 맞지 않을 때 fallback이 동작하는가

### 3.6 Chat history에 GraphResult 전체를 저장하는 것은 과할 수 있다

로컬 `chat_store.py`는 `graph_result` 전체를 JSON으로 저장하려 한다.

위험:

- 한 답변에 graph facts가 많아질 경우 chat JSON이 급격히 커질 수 있다.
- debug dict에 직렬화 불가능한 값이 들어가면 저장 실패 가능성이 있다.
- 일반 사용자에게는 source summary만 필요하다.

권장:

- 저장 대상은 `graph_result_summary`로 제한한다.
- fields:
  - intents
  - confirmed/candidate/missing count
  - 사용자 표시용 facts 최대 10개
  - evidence page/chunk
- raw debug는 session memory에만 두거나 관리자 expander에서 즉시 표시한다.

## 4. 즉시 수행할 복구 작업

### 4.1 전체 rsync 금지

Mac 로컬 전체 프로젝트를 DGX로 다시 rsync하지 않는다. 이전 rsync 때문에 PDF, `._*`, 무관 문서가 대량 유입됐다.

허용:

```bash
scp src/graph/query_planner.py src/graph/retriever.py src/graph/context.py ai-hang@100.88.5.57:/srv/shared/projects/insurance-rag-chatbot/src/graph/
scp scripts/eval_graph_qa.py ai-hang@100.88.5.57:/srv/shared/projects/insurance-rag-chatbot/scripts/
scp eval/graph_qa.jsonl ai-hang@100.88.5.57:/srv/shared/projects/insurance-rag-chatbot/eval/
scp docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md ai-hang@100.88.5.57:/srv/shared/projects/insurance-rag-chatbot/docs/
```

단, 위 파일들은 먼저 로컬에서 수정한 뒤 복사한다.

### 4.2 DGX에서만 최종 검증

최종 검증은 반드시 DGX에서 실행한다.

```bash
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/pytest tests/test_graph_*.py tests/test_streamlit_app.py -q"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/pytest -q"
```

Mac 로컬 테스트 결과는 참고만 한다.

## 5. 코드 수정 지시

### 5.1 `GraphRetriever` grade filtering

`GraphRetriever`에 다음 helper를 추가한다.

```python
def _grade_prefix_for_system(grade_system: str | None) -> str | None:
    if grade_system == "신1-5종":
        return "grade_new_1_5_"
    if grade_system == "1-5종":
        return "grade_1_5_"
    if grade_system == "1-3종":
        return "grade_1_3_"
    return None
```

수술 등급 조회 SQL은 다음 조건을 반영한다.

```sql
WHERE e.source_node_id = ?
  AND e.edge_type = 'HAS_GRADE'
  AND (? IS NULL OR n.node_id LIKE ?)
```

`plan.grade_system`이 없으면 모든 grade를 반환하거나, 우선순위에 따라 `신1-5종`을 먼저 반환한다. 단, 답변 context에는 가능하면 세 등급을 모두 제공하는 것이 낫다.

테스트:

```text
기관지 식도루 폐쇄술 + 신1-5종 -> 신1-5종 4종
기관지 식도루 폐쇄술 + 1-5종 -> 1-5종 4종
기관지 식도루 폐쇄술 + 1-3종 -> 1-3종 2종
```

### 5.2 `eval/graph_qa.jsonl` 수정

`graph_001` 기대값을 고친다.

잘못된 값:

```json
"object": "1-3종 2종"
```

올바른 값:

```json
"object": "신1-5종 4종"
```

`graph_002`는 단순 수술 목록 외에 각 수술별 수가코드/지급비율이 missing이면 missing fact를 기대값에 넣어야 한다.

예:

```json
{"subject": "간장 이식수술", "relation": "HAS_MEDICAL_FEE_CODE", "status": "missing"}
```

단, 실제 DB에서 연결이 있으면 해당 code를 기대값으로 명시한다.

### 5.3 `eval_graph_qa.py` 강화

현재 `match_fact()`는 subject/relation/object/status만 본다. 다음을 추가한다.

- expected fact에 `properties_contains` 지원
- evidence 필수 여부 검증:

```json
"requires_evidence": true
```

- candidate fact가 confirmed로 반환되면 실패
- missing fact가 임의 object를 가지면 실패
- case별 actual facts를 JSONL로 `reports/graph/eval_graph_qa_results.jsonl`에 저장

### 5.4 `GraphStore` read-only 모드 원격 반영 확인

원격 `src/graph/store.py`에 다음이 있어야 한다.

- `GraphStore(db_path, readonly=True)`
- read-only 연결은 `file:...?mode=ro`
- read-only에서는 `_init_db()` 쓰기 작업 금지
- read-only에서 `upsert_*`, `execute`, `begin`, `commit`, `rollback` 호출 시 예외

현재 원격에는 아직 이 코드가 없을 가능성이 높다. 반드시 확인 후 반영한다.

### 5.5 `GRAPH_ENABLED` 기본값 정책

`src/config.py`에서 기본값은 다음 중 하나로 정한다.

권장:

```python
GRAPH_ENABLED = os.getenv("GRAPH_ENABLED", "false").lower() == "true"
```

그리고 `/srv/ai-ops/bin/run-insurance-rag` 또는 `scripts/prepare_streamlit_runtime.sh`에서 GraphDB 파일이 있을 때만 `GRAPH_ENABLED=true`를 설정한다.

대안:

```python
GRAPH_ENABLED=true
```

를 유지하려면, `GraphRetriever` import/initialization/file-missing이 절대 앱을 중단시키지 않는 회귀 테스트가 필요하다.

### 5.6 RAG integration safety

`src/rag/pipeline.py` 수정 시 다음을 보장한다.

- GraphDB missing -> 기존 RAG 정상
- `GraphRetriever.retrieve()` 예외 -> warning만 남기고 기존 RAG 정상
- `graph_context`는 prompt 앞에 배치하되 `candidate` 지침을 유지
- graph evidence chunk가 Chroma에 없으면 무시하고 warning
- graph hits가 reranker에서 밀려도 graph context fact는 유지

### 5.7 Streamlit chat 저장 정책

`chat_store.py`에는 raw graph result 전체 저장 대신 summary 저장을 권장한다.

필수:

- JSON serialization 실패 테스트
- graph_result가 큰 경우에도 저장 가능한지 테스트
- 과거 chat history 로드 시 graph 모듈이 없어도 앱이 깨지지 않는지 테스트

## 6. 테스트 지시

### 6.1 Unit tests

추가/수정:

```text
tests/test_graph_retriever.py
- requested grade_system에 맞는 등급 반환
- candidate policy edge가 confirmed로 승격되지 않음
- missing fee code가 hallucination 없이 missing으로 반환

tests/test_graph_query_planner.py
- 비교/차이점 질문에서 "차이점과 각각 해당하는 수술종류"를 수술명으로 오추출하지 않음

tests/test_graph_store.py
- read-only SELECT 가능
- read-only write 금지

tests/test_streamlit_app.py
- GraphDB missing fallback
- graph_result summary 렌더링
```

### 6.2 Integration commands

DGX에서 다음 순서로 실행한다.

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
.venv/bin/pytest tests/test_graph_*.py tests/test_streamlit_app.py -q
.venv/bin/pytest -q
```

## 7. Git 작업트리 정리 지시

현재 원격 작업트리는 오염되어 있다. 커밋 전 반드시 선별 staging만 한다.

### 7.1 staging 금지

```text
AGENTS.md
WORKFLOW.md
docs/._*
scripts/._*
docs/67A_*
docs/67B_*
scripts/generate_v2_manual_batch_plan.py
scripts/prepare_v2_manual_batch.py
scripts/render_v2_manual_batch_pages.py
scripts/validate_v2_manual_batch.py
data/index/graph/insurance_graph.sqlite*
ocr_v1_original_extracted_handoff_*.tar.gz
```

### 7.2 staging 후보

```text
docs/108_GRAPHDB_HYBRID_RAG_IMPLEMENTATION_SPEC.md
docs/109_GRAPHDB_HYBRID_RAG_IMPL_REPORT.md
docs/110_GRAPHDB_REVIEW_AND_NEXT_INTEGRATION_SPEC.md
docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md
docs/112_GRAPHDB_RETRIEVER_SYNC_REVIEW_FIX_SPEC.md
src/graph/
scripts/build_graph_index.py
scripts/check_graph_index.py
scripts/eval_graph_qa.py
eval/graph_qa.jsonl
tests/test_graph_*.py
```

RAG/Streamlit 통합 파일은 실제 DGX 테스트가 통과한 뒤에만 후보로 포함한다.

```text
src/config.py
src/rag/pipeline.py
src/retrieval/vector_store.py
src/ui/chat_store.py
src/ui/streamlit_app.py
src/claim_calculation/pipeline.py
tests/test_streamlit_app.py
```

## 8. Acceptance Criteria

다음 조건을 모두 만족해야 완료로 인정한다.

- DGX 원격에 `query_planner.py`, `retriever.py`, `context.py`, `eval_graph_qa.py`, `graph_qa.jsonl`이 존재
- DGX에서 `eval_graph_qa.py`가 실행되고 5/5 통과
- `graph_001`이 `신1-5종 4종`을 기대하고 실제로 반환
- read-only GraphStore 테스트 통과
- GraphDB missing fallback 테스트 통과
- `pytest -q`가 DGX에서 통과
- `scripts/check_graph_index.py`가 DGX에서 통과
- `docs/111_GRAPHDB_RETRIEVER_IMPL_REPORT.md`가 DGX에 존재하고 실제 원격 검증 결과를 반영
- `git status --short` 기준 Graph 관련 파일만 선별 staging 가능한 상태

## 9. 자체 평가

현재 상태는 "로컬 구현 시도"와 "원격 GraphDB 빌드 성공"이 섞여 있다. 프로젝트의 기준은 DGX 메인 디렉터리이므로, 로컬 성공 보고는 완료 근거가 될 수 없다.

가장 중요한 품질 결함은 `신1-5종` 질의가 `1-3종` 결과로 평가 통과한 점이다. 이 문제는 실제 사용자가 제시한 hard query의 핵심을 정면으로 훼손한다. 따라서 다음 작업의 첫 번째 성공 기준은 GraphRetriever가 사용자가 요청한 등급 체계를 정확히 선택하는 것이다.
