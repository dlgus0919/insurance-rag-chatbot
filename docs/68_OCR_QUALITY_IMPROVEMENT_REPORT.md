# 68_OCR_QUALITY_IMPROVEMENT_REPORT

작성일: 2026-05-13

## 1) 구현 요약

이번 변경은 OCR 엔진 교체 없이 데이터 품질 병목(표 오검출, 노이즈 텍스트, remainder 혼합)을 줄이는 데 집중했다.

- 표 오검출 억제:
  - `src/parser/table_quality.py` 추가
  - `scripts/run_full_ocr.py` 저장 직전 table 품질 평가 후 `table -> text` 다운캐스트
  - 다운캐스트 메타: `downcast_from_table`, `downcast_reason`
- 텍스트 노이즈 필터 보강:
  - `src/parser/ocr_postprocess.py`에 장식성 영문 라인/숫자·기호-only 라인 필터 추가
  - `is_noise_text_block()` 추가
  - `scripts/run_full_ocr.py`, `src/parser/ocr_chunker.py`에서 공통 적용
- remainder 분리 안정화:
  - `src/parser/clova_ocr.py`에 `_should_split_paragraph()` 추가
  - Y-gap + 들여쓰기 변화를 함께 고려해 문단 혼합을 더 보수적으로 분리

## 2) 변경 파일

- `src/parser/table_quality.py` (신규)
- `scripts/run_full_ocr.py`
- `src/parser/ocr_postprocess.py`
- `src/parser/ocr_chunker.py`
- `src/parser/clova_ocr.py`
- `tests/test_table_quality.py` (신규)
- `tests/test_run_full_ocr.py`
- `tests/test_ocr_postprocess.py`
- `tests/test_ocr_chunker.py`
- `tests/test_clova_ocr.py`

## 3) 정량 자체 검토 (로컬 기존 데이터 기준)

실행 스크립트: 기존 `data/extracted/*` 산출물에 신규 휴리스틱을 적용해 예상 downcast/noise 규모를 집계.

- `상담사례집`
  - table 223개 중 downcast 후보 148개
  - 사유: `single_column_prose_like` 118, `missing_headers` 23, `rows_empty` 6, `rows_effectively_empty` 1
  - text 840개 중 noise 후보 67개
- `실무가이드`
  - table 317개 중 downcast 후보 10개
  - 사유: `missing_headers` 6, `single_column_prose_like` 4
  - text 607개 중 noise 후보 70개

해석:
- 상담사례집의 표 오검출 억제 효과가 큼.
- 실무가이드는 핵심 표 손실 위험이 낮은 보수적 영향 범위.

## 4) 테스트 결과

- 타깃 테스트:
  - `pytest tests/test_table_quality.py tests/test_run_full_ocr.py tests/test_ocr_postprocess.py tests/test_ocr_chunker.py tests/test_clova_ocr.py -q`
  - 결과: `36 passed`
- 전체 회귀:
  - `pytest -q`
  - 결과: `255 passed, 0 failed` (warning 5건)

## 5) 샘플 재실행 검증 상태

계획상 샘플 페이지 재OCR를 시도했으나, Codex 실행 환경 정책상 외부 CLOVA API로 OCR 원본 페이지를 전송하는 호출이 차단되어 실행 불가.

- 샌드박스 실행: DNS 해석 실패
- 권한 상승 실행: tenant 정책에 의해 data egress 차단

따라서 이번 턴에서는 코드/테스트/기존 산출물 정량 분석으로 자체 검토를 완료했다.

## 6) 워크플로우/자동화 영향

- 기존 weekend/nightly 수동교정 자동화 프롬프트는 그대로 사용 가능.
- 추가로 확인할 검증 포인트:
  - 배치 리포트에 `downcast_from_table` 개수
  - noise text 제거 후 블록 수 변화

