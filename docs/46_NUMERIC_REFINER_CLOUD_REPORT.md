# 46 숫자 셀 정제 + Cloud 인덱스 보고서

## 1. 변경 파일

- `src/parser/numeric_cell_refiner.py`
  - `refine_numeric_cells()`: 수술종수 유형 컬럼이 모두 blank인 후보 행만 Vision LLM으로 재판독한다.
  - `_candidate_row_indexes()`: 수술명/수술해설 문맥이 있고 수술종수 컬럼이 전부 공란인 행만 선별한다.
  - `_extract_valid_corrections()`: `_corrections` 중 수술종수 컬럼, 허용 값(`1`,`2`,`3`,`""`), 원본 blank 조건만 통과시킨다.
- `tests/test_numeric_cell_refiner.py`
  - 숫자 보정 적용, 후보 없음 스킵, invalid shape 방어, 비허용 보정 무시, 401 auth error 테스트 5개 추가.
- `scripts/run_true_hybrid_local.py`
  - `--vision-clean` 경로에서 `clean_table_blocks()` 다음에 `refine_numeric_cells()` 호출.
- `scripts/run_clova_local.py`
  - 동일하게 CLOVA 단독 실행 경로에도 숫자 정제 연결.
- `scripts/generate_ocr_html.py`
  - `vision_cleaned`, `numeric_refined` 배지 렌더링 추가.
- `scripts/check_cloud_index.py`
  - `chunks.jsonl`, ChromaDB, BM25의 `doc_short`별 카운트 및 누락 문서 요약 출력.
- `scripts/build_cloud_index.py`
  - `rebuild_from_chunks()`: cloud-safe / non-OCR 청크만 필터링해 ChromaDB와 BM25를 재빌드.
  - CLI: `python scripts/build_cloud_index.py [--zip-output PATH]`.
- `scripts/bootstrap_assets.py`
  - 직접 실행 시 repo root import 경로 보정.
  - `REBUILD_INDEX_FROM_CHUNKS=true`이면 ChromaDB가 비었을 때 `chunks.jsonl`에서 재빌드.

## 2. pytest -q

```text
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
=============================== warnings summary ===============================
tests/test_pdf_extractor.py::test_extract_page_image_uses_embedded_image
tests/test_pdf_extractor.py::test_extract_page_image_uses_embedded_image
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

tests/test_pdf_extractor.py::test_extract_page_image_uses_embedded_image
tests/test_pdf_extractor.py::test_extract_page_image_uses_embedded_image
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

tests/test_pdf_extractor.py::test_extract_page_image_uses_embedded_image
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
198 passed, 5 warnings in 2.15s
<sys>:0: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```

추가 확인:

```text
pytest tests/test_numeric_cell_refiner.py -v
5 passed in 0.03s

pytest tests/test_table_vision_cleaner.py tests/test_clova_ocr.py -q
18 passed in 0.06s

python -c "from src.parser.numeric_cell_refiner import refine_numeric_cells; print('OK')"
OK
```

## 3. p068 수술종수 Before / After

실행:

```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 68 --vision-clean
```

결과:

```text
[run_true_hybrid_local] p068 -> SUCCESS (6블록, 51.0초)
SUCCESS: 1/1 | SKIPPED: 0/1 | 총 소요: 51.3초
```

대표 비교:

| row | 수술명 | before | after |
|---:|---|---|---|
| 0 | 근육내 양성종양 적출술 | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |
| 1 | 양성종양[근층내의 지방종, 혈관종, 양성섬유종, 거대세포종] | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |
| 2 | 용수지수술 | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |
| 3 | 탄발지(Trigger Finger) 수술 | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |
| 4 | 사각근절단술 | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |
| 8 | 근성 사경수술 | `1-3종=""`, `1-5종=""`, `신1-5종=""` | `1-3종="1"`, `1-5종=""`, `신1-5종=""` |

## 4. check_cloud_index.py Before / After

로컬 before 상태도 이미 SOL 두 문서 벡터를 포함하고 있었다.

```text
[chunks.jsonl]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[ChromaDB]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[BM25]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[missing cloud vectors]
None
```

재빌드:

```text
python scripts/build_cloud_index.py
[build_cloud_index] 재빌드 완료
chunks: 4925
docs: 심평원, 약관, 자사_SOL건강, 자사_SOL운전자
```

After:

```text
[chunks.jsonl]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[ChromaDB]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[BM25]
심평원: 2286
약관: 384
가이드북: 0
자사_SOL건강: 1494
자사_SOL운전자: 761
실무가이드: 0
상담사례집: 0

[missing cloud vectors]
None
```

부트스트랩 확인:

```text
REBUILD_INDEX_FROM_CHUNKS=true python scripts/bootstrap_assets.py
ChromaDB 존재 - 재빌드 스킵
```

## 5. numeric_refined / numeric_corrections 샘플

```json
{
  "numeric_refined": true,
  "numeric_corrections": [
    {"row_index": 0, "col": "1-3종", "from": "", "to": "1"},
    {"row_index": 1, "col": "1-3종", "from": "", "to": "1"},
    {"row_index": 2, "col": "1-3종", "from": "", "to": "1"},
    {"row_index": 3, "col": "1-3종", "from": "", "to": "1"},
    {"row_index": 4, "col": "1-3종", "from": "", "to": "1"},
    {"row_index": 8, "col": "1-3종", "from": "", "to": "1"}
  ]
}
```

HTML 확인:

```text
python scripts/generate_ocr_html.py --doc 실무가이드 --output reports/ocr_compare_v46_review.html
[generate_ocr_html] wrote reports/ocr_compare_v46_review.html (165584 bytes)
```

## 6. 남은 블로커

None.
