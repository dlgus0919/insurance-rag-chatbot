# UX 버그 수정 및 채팅 영속화 구현 보고서

작성일: 2026-05-07

## 구현 범위

- M-ux-1: 검색 진단 체크박스 제거 및 일반 질의 debug 상시 수집 적용.
- M-ux-2: 답변 Markdown에서 단일 물결표(`~`)가 취소선으로 렌더링되지 않도록 정규화.
- M-ux-3/4: 계정별 채팅 내역 저장소(`data/chat_history/<user_id>/<chat_id>.json`)와 사이드바 멀티 채팅 목록 추가.

## 주요 변경 파일

- `src/ui/streamlit_app.py`
  - 저장된 채팅 목록 초기화, 새 채팅, 채팅 전환, 삭제, 자동 저장 흐름 추가.
  - 일반 질의, 퀵 코드 검색, 약관 정형 검색의 assistant 응답 append 직후 자동 저장.
  - 로그아웃 시 채팅 관련 session state 정리.
- `src/ui/chat_store.py`
  - 채팅 저장, 로드, 목록, 삭제, 이름 변경, `Chunk` 직렬화/역직렬화 구현.
- `tests/test_chat_store.py`
  - 채팅 저장소 왕복 저장, 최신순 목록, 삭제, 이름 변경, 손상 파일 처리 테스트 추가.
- `tests/test_streamlit_app.py`
  - 물결표 Markdown 정규화 테스트 추가.
- `.gitignore`
  - `data/chat_history/` 명시.

## 기존 파이프라인 영향 검토

- BGE-M3 임베딩, Chroma dense 검색, BM25, RRF, Reranker, LLM 호출 흐름은 변경하지 않았다.
- 답변 생성 이후 UI 표시 및 메시지 저장 단계에서만 Markdown 정규화와 자동 저장을 수행한다.
- 저장소는 assistant 메시지 append 이후에만 동작하므로 검색 결과 산출과 답변 생성 결과에는 개입하지 않는다.

## 검증

- `pytest tests/test_streamlit_app.py -q`: 14 passed.
- `pytest tests/test_chat_store.py tests/test_streamlit_app.py -q`: 22 passed.
- `pytest -q --ignore=tests/test_vector_store.py`: 119 passed, 5 warnings.
