# 베타 Stage 2 구현 보고

## 1. 작업 범위

- D3 `자사_SOL건강`, D4 `자사_SOL운전자` 실제 인덱싱 수행
- D6 `실무가이드`, D7 `상담사례집`은 `requires_ocr=True`로 자동 제외
- 사이드바 문서 필터를 실제 인덱싱 가능 문서 기준으로 변경
- 자사/타사 필터와 상품 유형 필터 추가
- OCR 본격 처리, GraphDB 구축, 약관 비교 모드, 과제 2는 수행하지 않음

## 2. 인제스트 변경

- `scripts/ingest.py`의 `select_sources()`에 `skip_ocr=True` 기본값 추가
- `--include-ocr` 옵션을 명시할 때만 OCR 필요 문서를 포함하도록 변경
- 기본 인제스트 대상: `심평원`, `약관`, `가이드북`, `자사_SOL건강`, `자사_SOL운전자`
- 실제 파일이 없는 `가이드북`은 기존 로직대로 건너뜀

## 3. 재인덱싱 결과

- 실행 명령: `python scripts/ingest.py`
- 전체 청크 수: 4,925
- 문서별 청크 수:
  - `심평원`: 2,286
  - `약관`: 384
  - `자사_SOL건강`: 1,494
  - `자사_SOL운전자`: 761
- 제외 확인:
  - `실무가이드`: 미포함
  - `상담사례집`: 미포함
- 갱신 산출:
  - `data/processed/chunks.jsonl`
  - `data/index/bm25.pkl`
  - `data/index/chroma/`

## 4. 사이드바 필터

- `config.INDEXED_PDF_SOURCES`, `config.INDEXED_DOC_SHORT_ORDER` 추가
- 사이드바 체크박스는 인덱싱 가능 문서만 표시:
  - 표시: `심평원`, `약관`, `자사_SOL건강`, `자사_SOL운전자`
  - 미표시: `실무가이드`, `상담사례집`
- 상위 필터 추가:
  - 보험사 구분: `전체`, `자사`, `타사`
  - 상품 유형: `전체`, `건강`, `실손`, `운전자`
- 필터 결과가 비면 빈 리스트 대신 `None`으로 폴백해 검색 결과 0건 고정을 방지

## 5. 검색 확인

- `chunks.jsonl`에서 `자동갱신` 텍스트 확인: 성공
- 오프라인 모드 직접 벡터 검색 확인:
  - 질의: `자동갱신형 처음건강보험 보장내용`
  - 필터: `["자사_SOL건강"]`
  - 결과: `자사_SOL건강` 청크 3건 반환

## 6. 테스트 결과

- `pytest -q --ignore=tests/test_vector_store.py`: 130 passed, 5 warnings
- `pytest -q tests/test_ingest.py tests/test_streamlit_app.py`: 21 passed
- `python scripts/check_raw_assets.py`: 통과
- `git ls-files | grep -E '\.(pdf|xlsx|xls)$'`: 0건
- `git diff --check`: 통과
- Streamlit 부팅 확인:
  - `streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8501`
  - `curl http://localhost:8501 | head -3` HTML 응답 확인

## 7. 남은 확인 사항

- D5 `보상가이드북.pdf` 원본 파일은 현재 프로젝트 루트에 없어 이번 인덱스에도 포함되지 않음
- D6/D7은 다음 OCR 명세 전까지 계속 인덱싱 제외
- D6 `cloud_safe` 정책과 D7 외부 공시 출처 확인 필요

## 8. GitHub 반영

- 구현 커밋 `b730b4a`는 `master` 브랜치에서 `origin/master`로 푸시 완료.
- 원본 PDF/XLSX와 SQLite 산출 DB는 Git 추적 대상에서 제외한다.
