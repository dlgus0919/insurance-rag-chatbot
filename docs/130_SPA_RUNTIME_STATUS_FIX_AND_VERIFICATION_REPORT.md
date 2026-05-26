# SPA 런타임 상태 API 수정 및 실사용 검증 보고서

작성일: 2026-05-26

---

## 1. 배경

FastAPI + SPA를 실제로 기동해 검증하던 중 `/api/system/status`가 500 오류를 반환했다. 원인은 API 라우터가 현재 `src.config`에 존재하지 않는 구버전 함수 `get_ingest_paths()`와 `DEFAULT_OCR_VERSION`에 의존하고 있었기 때문이다.

---

## 2. 수정 내용

- `src/api/routes/system.py`
  - 상태 API의 인덱스 경로 확인을 `src.retrieval.index_mode.resolve_index_paths()` 기반으로 변경했다.
  - `USERS_JSON_PATH` 환경변수를 반영해 개인 workspace나 테스트 런타임의 사용자 파일 상태를 정확히 표시하도록 수정했다.
  - 관계형 인덱스는 디렉터리 존재 여부가 아니라 `standard_codes.sqlite` 파일 존재 여부로 확인한다.
- `tests/test_api_system_status.py`
  - 기본 인덱스, v2 OCR 인덱스, 통합 인덱스, GraphDB, 관계형 DB, 사용자 파일 경로 상태를 검증하는 회귀 테스트를 추가했다.

---

## 3. 검증

원격 DGX Spark 메인 repo(`/srv/shared/projects/insurance-rag-chatbot`)에서 검증했다.

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_api_system_status.py tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
```

결과:

```text
4 passed, 1 warning
```

```bash
node --check frontend/js/pages/chat.js
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
409 passed, 3 warnings
```

```bash
cd frontend && npm run build
```

결과:

```text
frontend/dist/app.min.js 생성 완료
```

실제 런타임에서 `/api/system/status`는 다음 상태를 반환했다.

```text
status=ok
chunks/bm25/chroma/v2/combined/graph/relational/users=true
```

---

## 4. 실사용 검증

테스트 런타임을 `127.0.0.1:18080`에 기동하고 다음을 확인했다.

- `/login` 렌더링 및 테스트 관리자 로그인 성공
- `/chat` 렌더링, 인덱스 모드 3종 노출, 검색 모드 4종 노출
- Ollama `exaone3.5:7.8b` 기반 실제 채팅 스트림 응답 수신
- GraphDB 질의에서 `HAS_GRADE` confirmed fact와 `POLICY_COVERS_PROCEDURE` candidate fact 수신
- 보험금 계산 탭에서 도수치료/MX122/150000원 입력 시 예상 지급금액 105000원 표시
- 관리자 페이지에서 감사 로그, 사용자 관리, 시스템 상태 탭 진입 확인
- 세션 목록 조회 및 TXT 내보내기 성공
