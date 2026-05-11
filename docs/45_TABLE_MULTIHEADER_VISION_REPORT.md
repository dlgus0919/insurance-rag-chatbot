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

After, 실제 `p064_true_hybrid.json` output from `--vision-clean`:
```text
headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
row[0]: {'수술명': '베이커낭종 적출술', '수술해설': '무릎 뒤쪽에서 생기는 것으로 점액낭염이나 슬와낭종이라고도 한다.\n피부를 절개하여 무릎 뒤쪽에서 낭종을 제거해내는 수술을 말한다.', '1-3종': '', '1-5종': '2', '신1-5종': '2'}
row[1]: {'수술명': '', '수술해설': '[그림]', '1-3종': '', '1-5종': '', '신1-5종': ''}
```

## 5) End-to-End Attempt

Command:
```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 64 --vision-clean
```

Actual result:
```text
[2026-05-11 10:43:15,771] [    INFO] _client.py:1025 - HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
[run_true_hybrid_local] p064 -> SUCCESS (3블록, 37.0초)
[run_clova_local] summary.json true_hybrid 업데이트 완료
=== 완료 ===
SUCCESS: 1/1 | SKIPPED: 0/1 | 총 소요: 37.4초
```

HTML review file was regenerated:
```text
[generate_ocr_html] wrote /Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/reports/ocr_compare_v43_review.html (165555 bytes)
```

## 6) vision_cleaned Field

Actual p064 output:
```text
block.raw["vision_cleaned"] == True
block.raw["native_table"] == True
contains "[그림]" == True
```

## 7) Remaining Blockers

None.

JSON result files and HTML files were regenerated locally but are not committed.
