# 126. SPA Phase 1 구현 중간 리뷰 및 보정 명세

작성일: 2026-05-26
대상 브랜치: `/srv/shared/projects/insurance-rag-chatbot` `codex/spa-latest-backend-integration`
상위 명세: `docs/123_FRONTEND_SPA_LATEST_BACKEND_INTEGRATION_SPEC.md`, `docs/124_FRONTEND_SPA_PHASE1_BACKEND_INTEGRATION_SPEC.md`
작성 목적: 현재 Phase 1 이식 작업물이 파일 복사 단계에 머물러 있어, 최신 메인 RAG/GraphDB 연결과 실행 가능 상태까지 보정하도록 지시한다.

---

## 1. 현재 확인된 상태

원격 메인 저장소:

```text
/srv/shared/projects/insurance-rag-chatbot
branch: codex/spa-latest-backend-integration
base commit: 0068ec5 feat(llm): add model matrix eval and dgx runtime guide
```

현재 `git status --short`에서 다음 파일들이 untracked로 확인된다.

```text
?? docs/123_FRONTEND_SPA_LATEST_BACKEND_INTEGRATION_SPEC.md
?? docs/124_ANTIGRAVITY_PROMPT_FRONTEND_SPA_PHASE1.txt
?? docs/124_FRONTEND_SPA_PHASE1_BACKEND_INTEGRATION_SPEC.md
?? frontend/
?? package-lock.json
?? package.json
?? playwright.config.js
?? scripts/serve_frontend_spa.py
?? src/api/
?? tests/e2e/
?? tests/test_api_admin_audit.py
?? tests/test_api_admin_users.py
?? tests/test_api_auth_system.py
?? tests/test_api_chat_stream.py
?? tests/test_api_rbac.py
?? tests/test_api_security.py
?? tests/test_api_sessions_db.py
?? tests/test_api_sessions_export.py
?? tests/test_error_responses.py
?? tests/test_rate_limit.py
?? tests/test_request_tracking.py
```

또한 다음 오염 파일/디렉터리가 같이 들어와 있다.

```text
frontend/node_modules/.package-lock.json
src/api/__pycache__/
```

이들은 Git에 포함하면 안 된다.

---

## 2. 즉시 차단 결함

### 2.1 API import 실패

명령:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
PYTHONPATH=. .venv/bin/python -c "from src.api.main import app; print('api import OK')"
```

현재 결과:

```text
ModuleNotFoundError: No module named 'fastapi'
```

원인:

- eundeo `requirements.txt`에는 FastAPI 관련 의존성이 있었지만 메인 `requirements.txt`에 반영되지 않았다.

메인에 추가해야 할 의존성:

```text
fastapi>=0.111
pydantic-settings>=2.0
SQLAlchemy>=2.0
aiosqlite>=0.20
uvicorn[standard]>=0.30
slowapi>=0.1.9
pytest-cov>=5.0
```

주의:

- 의존성 추가 후 설치는 DGX Spark `.venv`에 수행해야 한다.
- secret 출력 없이 설치 로그만 확인한다.

### 2.2 `src.core` 참조로 인한 구조 불일치

현재 `src/api/rag_service.py`는 다음 예전 import를 사용한다.

```python
from src.core.llm_router import build_llm
from src.core.retriever import BM25Index, Embedder, RagPipeline, VectorStore, search_documents
```

하지만 메인 저장소에는 `src/core`가 없다.

확인 결과:

```text
find: ‘src/core’: No such file or directory
```

이 상태에서는 FastAPI 의존성을 설치해도 `src.api.rag_service` import가 실패한다.

수정 원칙:

- `src/core`를 새로 복사해 와서 예전 래퍼를 살리는 방식은 금지한다.
- 최신 메인 모듈을 직접 사용해야 한다.

사용해야 할 메인 경로:

```python
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore
from src.retrieval.bm25 import BM25Index
from src.retrieval.reranker import build_reranker
from src.llm.factory import build_llm, format_model_label, list_available_models
from src.rag.pipeline import RagPipeline, _hit_to_chunk
from src.graph.context import build_graph_context
from src.rag.evidence import append_evidence_validation_warning
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations
```

---

## 3. 누락된 핵심 요구사항

현재 `src/api/rag_service.py`와 `src/api/routes/chat.py`는 eundeo 예전 구조 그대로이며, 아래 요구사항이 반영되지 않았다.

### 3.1 GraphDB 연동 누락

명세 요구:

- `pipeline.graph_retriever.retrieve(question)`
- `build_graph_context(graph_result)`
- `graph_result.source_chunk_ids`가 있으면 `pipeline.vector_store.get_by_ids(...)`
- 검색 후보에 `graph_hits` 병합
- SSE `graph` 이벤트 송신

현재 상태:

- `src/api/rag_service.py`에 `GraphRetriever`, `build_graph_context`, `get_by_ids`, `graph_hits` 관련 로직이 없다.
- `src/api/routes/chat.py`에 `event: graph`가 없다.
- `frontend/js/pages/chat.js`에서 graph 이벤트 렌더링이 확인되지 않는다.

### 3.2 최신 `RagPipeline` 우회

명세 요구:

- API general mode가 최신 메인 `src.rag.pipeline.RagPipeline`의 검색/프롬프트/GraphDB 결합 구조를 사용해야 한다.

현재 상태:

- `prepare_retrieved_context()`가 `search_documents()`를 호출하는 예전 구조다.
- 최신 `RagPipeline.retrieve_hits(..., graph_hits=...)`와 `pipeline.build_prompt(..., graph_context=...)`를 사용하지 않는다.

### 3.3 evidence validation warning 누락

명세 요구:

- 최종 답변에 `append_retrieved_source_citations()`와 `append_evidence_validation_warning()`을 모두 적용해야 한다.

현재 상태:

```python
def finalize_answer(raw_answer: str, chunks: list) -> str:
    return append_retrieved_source_citations(raw_answer.strip(), chunks)
```

`append_evidence_validation_warning()`이 빠져 있다.

### 3.4 deterministic guard 누락

명세 요구:

- fake code, HIRA multi-row, cross-doc 질문에서 최신 `RagPipeline.answer()`와 같은 deterministic guard를 API streaming 경로에서도 적용해야 한다.

현재 상태:

- API streaming 경로에 `src.rag.pipeline._deterministic_guard_answer()` 또는 공개 helper가 없다.
- `QZ999` 같은 안전 질의가 LLM으로 그대로 넘어갈 수 있다.

### 3.5 빈 답변 방어 누락

명세 요구:

- LLM 토큰이 0개면 출처/Graph fact만 단독 표시하지 않고 SSE `warning` 이벤트를 보내야 한다.

현재 상태:

- `answer = finalize_answer("".join(tokens), chunks)`가 빈 문자열에도 그대로 citation을 붙일 수 있다.
- `warning` SSE 이벤트가 없다.

### 3.6 모델 목록 최신화 미흡

`/api/system/models`는 `src.core.llm_router`에 의존한다.

현재:

```python
from src.core.llm_router import format_model_label, list_available_models
```

수정:

```python
from src.llm.factory import format_model_label, list_available_models
```

반드시 다음 후보가 노출되는지 확인한다.

```text
vllm:nemotron-3-nano-30b-a3b-nvfp4
vllm:gemma-4-26b-a4b-nvfp4
sglang:qwen3-30b-a3b-instruct-2507-fp8
sglang:gpt-oss-20b
```

---

## 4. 보정 구현 지시

### 4.1 의존성 정리

메인 `requirements.txt`에 eundeo API 의존성을 추가한다.

추가 후 설치:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/pip install -r requirements.txt
```

설치 후 확인:

```bash
PYTHONPATH=. .venv/bin/python -c "import fastapi, sqlalchemy, aiosqlite, uvicorn, slowapi; print('api deps OK')"
```

### 4.2 API import 경로 수정

`src/api/rag_service.py`와 `src/api/routes/system.py`의 `src.core.*` 의존을 모두 제거한다.

금지:

```python
from src.core...
```

허용:

```python
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore
from src.retrieval.bm25 import BM25Index
from src.retrieval.reranker import build_reranker
from src.llm.factory import build_llm, format_model_label, list_available_models
from src.rag.pipeline import RagPipeline, _hit_to_chunk
```

### 4.3 general mode 재작성

`prepare_retrieved_context()`를 다음 형태로 바꾼다.

반환값:

```python
chunks, sources, prompt, graph_result, warnings
```

흐름:

```python
graph_result = None
graph_context = ""
graph_hits = []
warnings = []

if pipeline.graph_enabled and pipeline.graph_retriever:
    try:
        graph_result = pipeline.graph_retriever.retrieve(question)
        graph_context = build_graph_context(graph_result)
        if graph_result.source_chunk_ids:
            graph_hits = pipeline.vector_store.get_by_ids(graph_result.source_chunk_ids)
    except Exception as exc:
        warnings.append({"code": "GRAPH_RETRIEVAL_FAILED", "message": str(exc)})

hits, debug = pipeline.retrieve_hits(question, top_k=top_k, graph_hits=graph_hits)
chunks = [_hit_to_chunk(hit) for hit in hits]
sources = [chunk_to_source(chunk) for chunk in chunks]
prompt = pipeline.build_prompt(question, chunks, graph_context=graph_context)
```

history 요약은 필요하면 `question_for_prompt` 앞에 덧붙이되, 최신 `build_prompt()` 결과를 대체하지 않는다.

### 4.4 graph 직렬화 helper 추가

`GraphRetrievalResult`는 그대로 JSON 직렬화되지 않을 수 있다. API용 helper를 만든다.

예:

```python
def graph_result_to_payload(result) -> dict | None:
    if result is None:
        return None
    return {
        "plan": {
            "intents": list(getattr(result.plan, "intents", []) or []),
            "procedure_name": getattr(result.plan, "procedure_name", None),
            "category": getattr(result.plan, "category", None),
            "grade_system": getattr(result.plan, "grade_system", None),
            "requested_grade": getattr(result.plan, "requested_grade", None),
        },
        "facts": [...],
        "warnings": list(getattr(result, "warnings", []) or []),
    }
```

fact evidence는 다음 정도만 담는다.

```text
doc_short
page_start
page_end
chunk_id
source_version
confidence
```

### 4.5 chat stream 이벤트 수정

`src/api/routes/chat.py`에서 general mode 후:

```python
if graph_payload:
    yield _sse("graph", graph_payload)
for warning in warnings:
    yield _sse("warning", warning)
```

LLM 토큰 누적 후:

```python
raw = "".join(tokens).strip()
if not raw:
    yield _sse("warning", {"code": "EMPTY_LLM_OUTPUT", "message": "모델 응답 본문이 비어 있습니다."})
    answer = "모델 응답 본문이 비어 있어 답변을 생성하지 못했습니다. 검색 근거를 다시 확인해 주세요."
else:
    answer = append_retrieved_source_citations(raw, chunks)
    answer = append_evidence_validation_warning(answer, chat_request.query, chunks)
```

주의:

- 사용자가 보는 stream token은 raw 답변 기준으로 나오므로, citation/warning이 최종 저장 answer에만 반영되는 구조일 수 있다.
- 가능하면 최종 citation/warning delta를 별도 token으로 흘려보내거나 `final` 이벤트를 추가한다.
- 기존 프론트가 `done`까지만 처리한다면, 최종 말풍선 내용과 저장 answer가 달라지는 문제가 생긴다. 이 경우 `final` 이벤트 또는 `done.answer` 필드를 추가하고 프론트에서 반영한다.

### 4.6 프론트 graph/warning 렌더링

`frontend/js/pages/chat.js`:

- `let graphResult = null;`
- `let warnings = [];`
- SSE `graph` 이벤트 수신 시 저장
- SSE `warning` 이벤트 수신 시 저장 및 toast 또는 말풍선 하단 표시
- stream 종료 후 `renderGraphFacts(bubble, graphResult)` 호출

표시 규칙:

```text
confirmed: 확정 근거
candidate: 검토 후보, 확정 아님
missing: 구조화 DB에서 확인 못함
```

candidate는 지급 확정처럼 보이면 안 된다.

### 4.7 오염 파일 정리

Git에 포함 금지:

```text
frontend/node_modules/
src/api/__pycache__/
.coverage
insurance_chat.db
```

필요하면 `.gitignore`에 추가한다.

삭제는 작업 디렉터리 산출물만 대상으로 한다. 운영 데이터나 사용자가 만든 파일은 삭제하지 않는다.

---

## 5. 검증 순서

### 5.1 의존성/import

```bash
cd /srv/shared/projects/insurance-rag-chatbot
PYTHONPATH=. .venv/bin/python -c "import fastapi, sqlalchemy, aiosqlite, uvicorn, slowapi; print('api deps OK')"
PYTHONPATH=. .venv/bin/python -c "from src.api.main import app; print('api import OK')"
PYTHONPATH=. .venv/bin/python -c "from src.api.rag_service import get_rag_pipeline; print('rag_service import OK')"
```

### 5.2 코드 검색

아래 명령은 출력이 없어야 한다.

```bash
rg -n "from src\\.core|import src\\.core" src/api
```

아래 명령은 `src/api`에서도 결과가 있어야 한다.

```bash
rg -n "build_graph_context|graph_hits|get_by_ids|append_evidence_validation_warning|event: graph|warning" src/api frontend/js/pages/chat.js
```

### 5.3 테스트

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_api_*.py tests/test_rate_limit.py -q
PYTHONPATH=. .venv/bin/pytest tests/test_graph_*.py tests/test_claim_*.py -q
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
PYTHONPATH=. .venv/bin/pytest -q
```

### 5.4 API smoke

```bash
PYTHONPATH=. API_RATE_LIMIT_DISABLED=true .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8601
```

다른 터미널:

```bash
curl -s http://127.0.0.1:8601/api/health
curl -s http://127.0.0.1:8601/api/system/status
curl -s http://127.0.0.1:8601/api/system/models
```

---

## 6. 보고서 요구

작업 완료 후 다음 보고서를 작성한다.

```text
docs/127_FRONTEND_SPA_PHASE1_REVIEW_FIX_REPORT.md
```

필수 내용:

```text
수정한 결함:
- API 의존성 누락
- src.core 참조 제거
- 최신 RagPipeline 연결
- GraphDB SSE 이벤트
- evidence validation warning
- 빈 답변 방어
- frontend graph/warning 렌더링

변경 파일:
- ...

검증:
- api deps/import
- rg src.core 없음
- pytest 결과
- check_graph_index 결과
- eval_graph_qa 결과
- API smoke 결과

정리한 오염 파일:
- frontend/node_modules 제외/삭제 여부
- __pycache__ 제외/삭제 여부

미수행:
- 보험금 계산 UI/API는 다음 단계
- 대형 모델 수동 질의 미수행 시 이유
```

---

## 7. 완료 판정

이번 보정 작업은 아래가 모두 충족되어야 완료다.

- `from src.api.main import app` 성공
- `src/api`에서 `src.core` 참조가 없음
- `/api/system/models`가 최신 vLLM/SGLang 후보를 반환
- `/api/chat/stream` general mode가 최신 `RagPipeline`을 사용
- GraphDB result가 SSE `graph` 이벤트로 내려감
- 프론트가 graph/warning 이벤트를 렌더링
- 빈 답변 시 출처만 단독 표시하지 않음
- API 테스트와 기존 graph/claim 테스트가 통과하거나, 실패 원인이 구체적으로 보고됨
- 오염 파일이 Git staging 대상에서 제외됨
