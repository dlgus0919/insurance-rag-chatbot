# 사이드바 차단 버그 수정 보고

## 1. 수정 배경

- Streamlit Cloud에서는 원본 PDF가 Git 추적 제외 상태라 `source.path.exists()`가 `False`가 된다.
- 이 때문에 `INDEXED_PDF_SOURCES`가 빈 리스트가 되고, 사이드바 문서 체크박스가 0개가 되어 질문 입력이 차단됐다.

## 2. 구현 내용

- `src/config.py`
  - `INDEXED_PDF_SOURCES` 산정 조건을 `path.exists()`에서 `cloud_safe=True` + `requires_ocr=False`로 변경
  - 테스트 가능한 `indexed_pdf_sources()` 헬퍼 추가
- `src/ui/streamlit_app.py`
  - 사이드바의 보험사/상품 유형 필터와 문서 개별 선택 체크박스 제거
  - 안내 문구만 표시: “현재 전체 문서를 검색합니다.”
  - 일반 질의는 항상 `doc_filter=None`으로 검색
  - 퀵 코드/약관 정형 검색도 앱 호출 경로에서는 `doc_filter=None`으로 전체 검색
  - 로그 스키마 호환을 위해 `selected_docs` 필드는 빈 리스트로 유지
- `tests/test_streamlit_app.py`
  - 제거된 `_get_doc_filter_from_meta()` 테스트 삭제
- `tests/test_config.py`
  - PDF 파일 경로가 존재하지 않아도 `cloud_safe=True` 문서는 인덱싱 대상에 포함되는지 검증

## 3. 검증 결과

- `config.INDEXED_PDF_SOURCES` 확인:
  - `심평원`
  - `약관`
  - `자사_SOL건강`
  - `자사_SOL운전자`
- `pytest -q tests/test_config.py tests/test_streamlit_app.py`: 15 passed
- `pytest -q --ignore=tests/test_vector_store.py`: 128 passed, 5 warnings
- `streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8501`: 부팅 성공
- `curl http://localhost:8501 | head -3`: HTML 응답 확인
- `git diff --check`: 통과
- `python scripts/check_raw_assets.py`: 통과
- Git diff 확인 결과 PDF/XLSX/SQLite 바이너리 변경 없음

## 4. 범위 제외

- 비급여 코드 조회 UI 연결은 수행하지 않음
- D6/D7 OCR 파이프라인은 수행하지 않음
- 신규 인덱스 재생성은 수행하지 않음

## 5. GitHub 반영

- 본 수정은 커밋 후 `master` 브랜치에서 `origin/master`로 푸시 완료한다.
- 이후 구현 보고서에도 커밋/푸시 여부를 계속 명시한다.
