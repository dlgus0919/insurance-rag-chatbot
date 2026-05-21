# 94. Codex OCR Integration Review And Push Report

작성일: 2026-05-21
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`

## 1. 검토 배경

Antigravity 서브 에이전트가 `docs/92_OCR_V1_V2_DB_INTEGRATION_SPEC.md` 기반으로 Dani 워크스페이스의 OCR v1/v2 매핑 코드를 메인 저장소에 이식했다. 이후 Codex가 메인 저장소 기준으로 실제 반영 상태를 재검토했다.

## 2. 발견 사항

초기 검토 시 다음 문제가 있었다.

- `git diff --check` 실패: `scripts/eval.py`, `src/rag/evidence.py`, `src/ui/streamlit_app.py`에 trailing whitespace 존재
- `src/parser/ocr_chunker.py`에 중복 `return chunks` 존재
- `src/ui/streamlit_app.py`에 OCR index mode 선택 및 pair mapping 로딩 연결이 누락됨
- `src/ui/admin_page.py`에 OCR pair mapping 요약 표시가 누락됨
- Antigravity가 실행한 검증은 `tests/test_build_v1_v2_pair_mapping.py` 1개에 한정됨

## 3. Codex 보정 내용

- whitespace 및 EOF 정리 후 `git diff --check` 통과
- `compileall`로 `scripts`, `src`, `tests` 구문 검증
- `src/parser/ocr_chunker.py` 중복 return 제거
- `src/rag/evidence.py`의 `Any` 타입 주석 정리
- Streamlit에 `OCR 인덱스 모드` 선택 연결 추가
  - `기본 운영 인덱스` -> `default`
  - `보정본 OCR만` -> `v2_only`
  - `원본+보정본 OCR 통합` -> `v1_v2_combined`
- `_load_heavy_components(index_mode)`에서 index mode별 BM25/Chroma 경로를 로드하도록 연결
- pair mapping과 v1 chunk lookup을 optional로 로드하여 `RagPipeline`에 전달
- 관리자 페이지 시스템 탭에 OCR pair mapping 요약 표 추가
- 회귀 테스트 추가
  - pair OCR context prompt 주입 테스트
  - OCR hierarchy context propagation 테스트
  - 로그 payload의 `index_mode` 기록 테스트

## 4. 검증 결과

실행 명령:

```bash
git diff --check
.venv/bin/python -m compileall -q scripts src tests
.venv/bin/python -m pytest tests/test_build_v1_v2_pair_mapping.py tests/test_ingest.py tests/test_ocr_chunker.py tests/test_pipeline.py tests/test_streamlit_app.py tests/test_conflict_detection.py -q
.venv/bin/python -m pytest -q
```

결과:

```text
OCR/충돌/Streamlit 관련 테스트: 62 passed, 1 warning
전체 테스트: 284 passed, 3 warnings in 3.00s
```

경고는 기존 의존성 deprecation 경고이며 테스트 실패는 아니다.

## 5. 데이터 산출물 처리

다음 runtime artifact는 Git에 포함하지 않았다.

- `data/index_v1_original_ocr/`
- `data/index_v2_manual/`
- `data/index_v1_v2_combined/`
- `data/mapping/*.jsonl`
- `data/processed/chunks_v1_*.jsonl`
- `data/processed/chunks_v2_manual.jsonl`
- `data/processed/chunks_v1_v2_combined.jsonl`
- Chroma SQLite/BM25 pickle 산출물

현재 메인 저장소에는 코드와 문서만 push 대상으로 남긴다. 실제 OCR v1/v2 runtime 산출물 반입은 별도 운영 작업으로 수행해야 한다.

## 6. 남은 주의사항

- OCR index mode UI는 준비됐지만, `v2_only`와 `v1_v2_combined` 모드는 해당 인덱스와 mapping runtime 파일이 메인 운영 디렉터리에 반입된 뒤 사용할 수 있다.
- 기본 선택지는 기존 앱 동작을 깨지 않도록 `기본 운영 인덱스(default)`로 유지했다.
- 상담사례집 pair mapping은 low-confidence 비율이 높으므로, 운영 기본값으로 v1 보조 컨텍스트를 강하게 쓰기 전 검수가 필요하다.
