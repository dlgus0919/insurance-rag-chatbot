# 63_C_HOOK_FIX 구현 보고서

작성일: 2026-05-13  
대상 명세: `docs/63_CODEX_SPEC_C_HOOK_FIX.md`

## 1) 변경 파일

- `src/rag/pipeline.py`
- `scripts/eval.py`
- `tests/test_pipeline.py`

## 2) Task 1 — 구 수술분류표 질의 C Hook 차단

`_build_structured_context()`에서 수술명 추출 직후 구(舊) 표 질의 마커를 검사하도록 가드를 추가했습니다.

- 추가 상수: `_OLD_SURGERY_TABLE_MARKERS = ("수술종류분류", "종류분류(종)", "수술분류표")`
- 적용 로직:
  - 질문을 공백 제거한 `compact_question`으로 정규화
  - 구 표 마커가 포함되면 `surgery_name = None` 처리
  - 결과적으로 `TableStore.lookup_surgery_grade()` C 조회를 건너뜀

## 3) Task 2 — 장해 지급률 질의 추출 정밀도 개선

장해 질의에서 키워드 단위가 아닌 조건구 전체를 우선 추출하도록 변경했습니다.

- 추가 정규식: `_DISABILITY_RATE_QUESTION_PATTERN = r"^(.{4,60}?)\s*(?:장해\s*)?지급률"`
- `_extract_disability_region_from_query()` 우선순위:
  1. `"X 지급률"` 패턴에서 전체 조건구 추출
  2. 기존 신체부위 키워드 fallback
  3. 기존 정규식 fallback

예시:
- `"두 눈이 멀었을 때 장해 지급률은?"` → `"두 눈이 멀었을 때"`
- `"한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때 지급률은?"` → 전체 조건구 반환

## 4) Task 3 — eval C 디버그 로깅 보강

`scripts/eval.py`에 C 컨텍스트 주입/디버그를 추가했습니다.

- `eval.py`에서 LLM 호출 전 `_build_structured_context(question, chunks, table_store=...)` 실행
- 구조화 컨텍스트가 있으면 user prompt 상단에 prepend
- surgery_grade 항목 로그에 `"[C_DEBUG] C블록 존재:{True|False}"` 추가

## 5) 테스트 및 실행 상태

이미 수행:

- `pytest tests/test_pipeline.py -v` → **30 passed**
- `pytest -q` → **242 passed**

중단 처리:

- 장시간 `eval.py --ocr` 실행은 사용자 요청으로 중단
- `pkill -f "python scripts/eval.py"` 수행
- OCR/ingest/eval 잔여 프로세스 없음 확인

## 6) 추가된/수정된 테스트

`tests/test_pipeline.py`에 아래 검증을 반영:

- 장해 지급률 질의에서 전체 조건구 추출 검증
- 구 수술분류표 질의 시 C lookup 차단 검증
- 기존 장해 추출 기대값을 변경된 로직에 맞게 업데이트

## 7) 후속(사용자 직접 실행 예정)

필요 시 아래 순서로 명세 63 지표 검증을 재개하면 됩니다.

1. `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false python scripts/eval.py --ocr`
2. `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false python scripts/eval.py`

