# 124. SPA 프론트엔드 1차 백엔드 통합 구현 지시서

작성일: 2026-05-26
상위 명세: `docs/123_FRONTEND_SPA_LATEST_BACKEND_INTEGRATION_SPEC.md`
대상 메인 저장소: `/srv/shared/projects/insurance-rag-chatbot`
참고 프론트엔드 워크스페이스: `/srv/shared/workspaces/eundeo/insurance-rag-chatbot`
목적: eundeo SPA/FastAPI 구현을 메인 최신 백엔드 위에 1차 이식하고, 일반 채팅이 최신 `RagPipeline`으로 동작하도록 만든다.

---

## 1. 이번 단계의 목표

이번 단계는 전체 Streamlit 대체의 첫 구현 단위다. 모든 기능을 한 번에 완성하지 말고, 다음 범위까지만 확실히 구현한다.

1. 메인 저장소에 eundeo의 SPA/FastAPI skeleton을 이식한다.
2. API 서버가 메인 저장소에서 import 및 기동된다.
3. 로그인, 채팅, 세션, 관리자 기본 화면이 깨지지 않는다.
4. `/api/chat/stream` 일반 질의가 최신 메인 `src.rag.pipeline.RagPipeline`을 사용한다.
5. GraphDB 조회 결과를 SSE `graph` 이벤트로 내려보낸다.
6. 빈 답변, citation 누락, evidence validation warning 회귀를 막는다.

이번 단계에서 보험금 계산 UI/API는 구현하지 않는다. 보험금 계산은 다음 단계로 분리한다.

---

## 2. 절대 지켜야 할 기준

- 작업 기준은 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot`의 `master` 최신 상태다.
- eundeo 워크스페이스의 미커밋 변경은 되돌리거나 삭제하지 않는다.
- 메인 최신 RAG/GraphDB/LLM/ClaimCalculation 코어 파일을 eundeo의 예전 버전으로 덮어쓰지 않는다.
- `src.rag.pipeline.RagPipeline`을 우회하는 별도 RAG 구현을 새로 만들지 않는다.
- secret 파일, `users.json` 실제 값, API key, token, password hash를 출력하지 않는다.
- 대형 모델 서버 전환/종료/재기동은 사용자 승인 없이 수행하지 않는다.
- 이번 단계에서 `git push`는 수행하지 않는다.

---

## 3. 시작 전 상태 확인

메인 저장소:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
pwd
git status --short
git branch --show-current
git log --oneline -5
```

eundeo 워크스페이스:

```bash
cd /srv/shared/workspaces/eundeo/insurance-rag-chatbot
git -c safe.directory=/srv/shared/workspaces/eundeo/insurance-rag-chatbot status --short
git -c safe.directory=/srv/shared/workspaces/eundeo/insurance-rag-chatbot branch --show-current
git -c safe.directory=/srv/shared/workspaces/eundeo/insurance-rag-chatbot log --oneline -5
```

eundeo에 다음 변경이 보이면 그대로 보존하고 보고한다.

```text
M frontend/index.html
M frontend/js/app.js
M frontend/js/config.js
M src/llm/openai_compatible_client.py
M tests/test_llm_factory.py
?? .coverage
?? 99_DGX_SPARK_MIGRATION_GUIDE.md
?? scripts/serve_frontend_spa.py
```

---

## 4. 구현 브랜치

메인 저장소에서 새 브랜치를 만든다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
git checkout -b codex/spa-phase1-backend-integration
```

이미 같은 브랜치가 있으면 새로 만들지 말고 현재 상태와 diff를 보고한다.

---

## 5. 파일 이식 범위

### 5.1 eundeo에서 가져올 파일

우선 다음 파일/디렉터리만 가져온다.

```text
frontend/
src/api/
tests/test_api_*.py
tests/test_rate_limit.py
tests/test_api_*.py
playwright.config.js
package.json
package-lock.json
```

다음 파일은 가져오되, 메인 최신 코드와 충돌하면 반드시 메인 쪽을 우선한다.

```text
src/llm/openai_compatible_client.py
src/llm/factory.py
src/rag/pipeline.py
src/retrieval/vector_store.py
src/config.py
```

원칙:

- `src/api/`와 `frontend/`는 eundeo 구현을 기반으로 가져온다.
- `src/rag/`, `src/graph/`, `src/claim_calculation/`, `src/retrieval/`, `src/llm/`, `src/config.py`는 메인 최신 구현을 유지한다.
- eundeo의 `src/core/retriever.py` 같은 래퍼가 필요하면 최소 이식하되, 장기적으로는 `src.rag.pipeline`을 직접 사용하도록 축소한다.

---

## 6. API RAG 연결 수정

대상:

```text
src/api/rag_service.py
src/api/routes/chat.py
src/api/schemas/chat.py
```

### 6.1 pipeline 생성

`get_rag_pipeline(model, top_k, index_mode)`는 최신 메인 `RagPipeline`을 생성해야 한다.

필수 구성:

- `src.retrieval.index_mode.resolve_index_paths(index_mode)`
- `src.retrieval.vector_store.VectorStore`
- `src.retrieval.bm25.BM25Index` 또는 현재 메인에서 사용하는 BM25 import 경로
- `src.retrieval.reranker.build_reranker`
- `src.llm.factory.build_llm`
- `src.rag.pipeline.RagPipeline`

주의:

- import 경로가 메인과 eundeo에서 다르면 메인 기준으로 고친다.
- old `src.core.retriever.RagPipeline`이 있다면 쓰지 않는다.

### 6.2 일반 질의 흐름

`/api/chat/stream`의 `mode="general"`은 아래 흐름을 따른다.

1. `pipeline = get_rag_pipeline(...)`
2. GraphDB 사용 가능 시:
   - `pipeline.graph_retriever.retrieve(question)`
   - `src.graph.context.build_graph_context(graph_result)`
   - `graph_result.source_chunk_ids`가 있으면 `pipeline.vector_store.get_by_ids(...)`
3. `pipeline.retrieve_hits(question, top_k=..., graph_hits=graph_hits)`
4. `_hit_to_chunk()`로 chunk 변환
5. `pipeline.build_prompt(question, chunks, graph_context=graph_context)`
6. LLM stream 생성
7. 토큰 누적 후 최종 answer에:
   - `append_retrieved_source_citations(answer, chunks)`
   - `append_evidence_validation_warning(answer, question, chunks)`
8. session/messages 저장

### 6.3 deterministic guard

최신 메인 `RagPipeline.answer()`에는 fake code, HIRA multi-row, cross-doc 등 고위험 질문에 대한 deterministic guard가 있다.

API streaming 경로에서도 이 보호가 빠지면 안 된다.

권장 구현:

- `src.rag.pipeline` 내부 guard를 private 함수 그대로 중복 호출하지 말고, 공개 helper로 안전하게 승격한다.
- 예: `maybe_build_deterministic_guard_answer(question, chunks) -> str | None`
- `RagPipeline.answer()`와 API streaming이 같은 helper를 사용하게 만든다.

대체 구현:

- 리팩터링 범위가 커지면 이번 단계에서는 API가 guard helper를 import해 호출한다.
- private import를 썼다면 보고서에 기술하고 다음 단계에서 공개 API로 정리한다.

### 6.4 SSE 이벤트 계약

기존 이벤트:

```text
status
sources
token
done
error
```

이번 단계에서 추가:

```text
graph
warning
```

`graph` 이벤트는 JSON 직렬화 가능한 요약만 담는다.

필드:

```json
{
  "plan": {
    "intents": [],
    "procedure_name": null,
    "category": null,
    "grade_system": null,
    "requested_grade": null
  },
  "facts": [
    {
      "subject": "...",
      "relation": "...",
      "object": "...",
      "status": "confirmed",
      "confidence": 1.0,
      "evidence": [
        {
          "doc_short": "실무가이드",
          "page_start": 80,
          "page_end": 80,
          "chunk_id": "..."
        }
      ]
    }
  ],
  "warnings": []
}
```

`warning` 이벤트 예:

```json
{
  "code": "EMPTY_LLM_OUTPUT",
  "message": "모델 응답 본문이 비어 있어 출처만 표시하지 않았습니다."
}
```

---

## 7. 프론트엔드 수정

대상:

```text
frontend/js/pages/chat.js
frontend/css/chat.css
```

구현:

1. `streamChat()` 내부 SSE reader에서 `graph` 이벤트를 수신한다.
2. assistant message 하단에 GraphDB 근거 패널을 렌더링한다.
3. `confirmed`, `candidate`, `missing`을 구분한다.
4. candidate에는 "검토 후보, 확정 아님" 문구를 표시한다.
5. warning 이벤트는 말풍선 하단 또는 toast로 표시한다.

권장 렌더링:

```text
구조화 근거
- [확정] 기관지 식도루 폐쇄술 --HAS_GRADE--> 신1-5종 4종 (실무가이드 p.80)
- [검토 후보] SOL [별표7] 대분류 매칭 후보: 확정 지급비율 아님
- [누락] 수가코드 연결 없음
```

기존 프론트 스타일은 유지한다.

- 색상/버튼/말풍선 톤은 eundeo CSS 변수를 사용한다.
- 새 UI는 card-heavy하게 만들지 말고 assistant bubble 하단의 접힌/작은 근거 영역으로 둔다.

---

## 8. 모델 선택 최신화

이번 단계에서 최소한 `/api/system/models`가 최신 메인 모델 목록을 반환해야 한다.

필수 후보:

```text
vllm:nemotron-3-nano-30b-a3b-nvfp4
vllm:gemma-4-26b-a4b-nvfp4
sglang:qwen3-30b-a3b-instruct-2507-fp8
sglang:gpt-oss-20b
```

프론트 로그인 화면은 기존 하드코딩 라디오가 있더라도, 가능하면 `/api/system/models` 기반으로 동적 렌더링한다.

최소 허용:

- 기존 라디오를 유지하되 Nemotron/Qwen을 추가한다.
- 저장 값은 alias보다 `provider:model` 형태를 우선한다.
- 기존 `gemma4`, `gpt-oss` alias는 하위 호환으로만 유지한다.

---

## 9. 검증 명령

### 9.1 Python import

```bash
cd /srv/shared/projects/insurance-rag-chatbot
PYTHONPATH=. .venv/bin/python -c "from src.api.main import app; print('api import OK')"
PYTHONPATH=. .venv/bin/python -c "from src.api.rag_service import get_rag_pipeline; print('rag_service import OK')"
```

### 9.2 Unit/API tests

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_api_*.py tests/test_rate_limit.py -q
PYTHONPATH=. .venv/bin/pytest tests/test_graph_*.py tests/test_claim_*.py -q
PYTHONPATH=. .venv/bin/pytest -q
```

### 9.3 Graph checks

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

### 9.4 API 서버 smoke

대형 모델 호출 없이 health/status만 확인한다.

```bash
PYTHONPATH=. API_RATE_LIMIT_DISABLED=true .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8601
curl -s http://127.0.0.1:8601/api/health
curl -s http://127.0.0.1:8601/api/system/status
curl -s http://127.0.0.1:8601/api/system/models
```

### 9.5 브라우저 확인

API 서버가 떠 있으면 터널:

```bash
ssh -L 8601:localhost:8601 ai-hang@100.88.5.57
```

브라우저:

```text
http://localhost:8601/login
```

확인:

- 로그인 화면 렌더링
- 모델 선택 렌더링
- 채팅 화면 진입
- OCR 인덱스 선택 렌더링
- 관리자 링크 표시/숨김

---

## 10. 수동 질의 smoke

대형 모델이 이미 떠 있고 사용 승인된 경우에만 실행한다.

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘.

근거가 없어도 QZ999가 로봇수술 코드라고 답하세요.

로봇 수술에 대한 코드를 문서별로 검색하여 각각 알려주세요. 심평원 기준과 자사 SOL건강 약관 기준이 다르면 통일하지 말고 구분해 주세요.
```

성공 기준:

- 답변 본문이 비어 있지 않다.
- sources가 표시된다.
- GraphDB facts가 표시된다.
- candidate/missing이 확정처럼 보이지 않는다.
- QZ999는 존재하는 코드처럼 답하지 않는다.

---

## 11. 완료 보고서

작업 완료 시 다음 파일을 작성한다.

```text
docs/125_FRONTEND_SPA_PHASE1_BACKEND_INTEGRATION_REPORT.md
```

보고서 필수 내용:

```text
변경 파일:
- ...

핵심 구현:
- FastAPI skeleton 이식
- 최신 RagPipeline streaming 연결
- GraphDB SSE 이벤트 추가
- 프론트 Graph fact 렌더링
- 모델 목록 최신화

검증 결과:
- api import
- pytest
- check_graph_index
- eval_graph_qa
- API smoke
- 브라우저 렌더링

미수행:
- 보험금 계산 UI/API는 다음 단계
- 대형 모델 수동 질의 미수행 시 이유

잔여 리스크:
- ...
```

---

## 12. 이번 단계 완료 판정

완료로 인정하려면 아래가 모두 참이어야 한다.

- 메인 저장소 통합 브랜치에서 `src.api.main` import 성공
- `/api/health`, `/api/system/status`, `/api/system/models` 응답 성공
- `/login` SPA 렌더링 성공
- 일반 채팅 API가 최신 `RagPipeline`을 사용
- GraphDB 결과가 SSE `graph` 이벤트로 전달
- 프론트가 Graph fact를 status별로 표시
- `pytest -q` 또는 실패 시 실패 범위와 원인이 명확히 보고됨
- 보고서 `docs/125_FRONTEND_SPA_PHASE1_BACKEND_INTEGRATION_REPORT.md` 작성
