# Table Multiheader + Vision Cleaner 구현 보고서 (v45)

## 1) 변경 파일

- `src/parser/clova_ocr.py`
  - `_cell_span()`: CLOVA cell의 row/column span 값을 정규화하는 헬퍼 추가
  - `_header_colspan_cols()`: 0행 병합 헤더가 점유한 컬럼 집합 계산
  - `_detect_header_rows()`: 2행 헤더 여부 자동 감지
  - `_build_column_headers()`: 병합 헤더의 하위 행 값을 실제 컬럼명으로 구성
  - `_table_to_json()`: 다단 헤더 감지 결과에 따라 data row 시작 위치 조정
- `src/parser/table_vision_cleaner.py`
  - `clean_table_blocks()`: table block을 OpenAI Vision 모델로 정제
  - `TableVisionCleanerAuthError`: OpenAI 401 인증 오류를 중단 가능하게 표면화
- `scripts/run_true_hybrid_local.py`
  - `--vision-clean` 플래그 추가 및 table block Vision 정제 연결
- `scripts/run_clova_local.py`
  - `--vision-clean` 플래그 추가 및 table block Vision 정제 연결
- `tests/test_clova_ocr.py`
  - CLOVA native table 2행 헤더 감지 테스트 추가
- `tests/test_table_vision_cleaner.py`
  - Vision 정제 성공, invalid shape fallback, non-table skip, 401 오류 테스트 추가

## 2) Manual One-Liner Output

```text
headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
row[0]: {'수술명': '봉합술', '수술해설': '설명', '1-3종': '', '1-5종': '2', '신1-5종': '2'}
PASS
```

## 3) Test Output

Header focused:
```text
pytest tests/test_clova_ocr.py -v -k "header"
2 passed, 12 deselected in 0.02s
```

Vision cleaner:
```text
pytest tests/test_table_vision_cleaner.py -v
4 passed in 0.03s
```

Related regression:
```text
pytest tests/test_clova_ocr.py tests/test_table_vision_cleaner.py tests/test_run_clova_local.py tests/test_run_true_hybrid_local.py -q
27 passed in 0.20s
```

Full regression:
```text
pytest -q
193 passed, 5 warnings in 2.04s
```

Import check:
```text
python -c "from src.parser.table_vision_cleaner import clean_table_blocks; print('import OK')"
import OK
```

## 4) p064 Before/After

Before, 기존 `p064_clova.json` native table output:
```text
headers: ['수술명', '수술해설', '수술종수', '수술종수_2', '수술종수_3']
row[0]: {'수술명': '수술명', '수술해설': '수술해설', '수술종수': '1-3종', '수술종수_2': '1-5종', '수술종수_3': '신1-5종'}
vision_cleaned: None
```

After expectation from deterministic unit/manual validation:
```text
headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
row[0] starts at first data row, not the sub-header row.
```

End-to-end `p064_true_hybrid.json` after `--vision-clean` could not be produced in this Codex sandbox because the command requires exporting the local insurance page image to external CLOVA OCR and OpenAI Vision services.

## 5) End-to-End Attempt

Command:
```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 64 --vision-clean
```

Sandbox result:
```text
[run_true_hybrid_local] p064 -> SKIPPED (API 요청 실패: HTTPSConnectionPool(host='ea1lfq3tos.apigw.ntruss.com', port=443): Max retries exceeded with url: /custom/v1/52772/81d1298723dd879c90085d6ee51ae2c507fdc22a47f0d0eb9822b50c53eb98f0/general (Caused by NameResolutionError("<urllib3.connection.HTTPSConnection object at 0x1542cea50>: Failed to resolve 'ea1lfq3tos.apigw.ntruss.com' ([Errno 8] nodename nor servname provided, or not known)")))
SUCCESS: 0/1 | SKIPPED: 1/1
```

Escalated rerun was blocked by policy because it would send a local insurance document page to two external services: CLOVA OCR and OpenAI Vision.

## 6) vision_cleaned Field

Unit test verifies successful Vision response sets:
```text
block.raw["vision_cleaned"] == True
```

Real p064 output value could not be verified end-to-end due to the external API execution blocker above.

## 7) Remaining Blockers

- External API e2e validation is blocked in this Codex environment unless the operator runs the command locally:
  ```bash
  python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 64 --vision-clean
  ```
- The sandbox attempt overwrote local `reports/ocr_compare/실무가이드/p064_true_hybrid.json` with a SKIPPED result. JSON result files are not committed.
