# 47 수술종수 정제 개선 결과 보고서

## 1. 구현 요약

v46 숫자 정제는 `1-3종`, `1-5종`, `신1-5종`이 모두 blank인 행만 Vision LLM 후보로 삼았다. 그 결과 p068에서 `1-3종`만 일부 채워지고 같은 행의 `1-5종`, `신1-5종`은 계속 blank로 남았다.

v47에서는 수술종수 3개 컬럼을 하나의 그룹으로 보고, 텍스트 행은 3개 컬럼이 모두 valid 값으로 채워져야 정상으로 판정하도록 변경했다. 부분 누락 행은 반드시 Vision LLM 후보로 포함하고, 적용한 값은 `method: "vision_llm"` 메타데이터로 기록한다.

구현 커밋:

```text
459adf3 Improve surgery grade numeric refinement
push: origin/master 완료
```

## 2. 변경 파일 및 핵심 함수

- `src/parser/numeric_cell_refiner.py`
  - `_grade_column_roles()`: `1-3종/1-5종/신1-5종` 또는 `수술종수*` 3개 컬럼을 역할 기반 그룹으로 식별한다.
  - `_needs_refinement()`: 텍스트 행에서 all blank, partial blank, invalid 값을 후보로 판정한다. `[그림]` 또는 빈 행은 all blank 허용.
  - `_target_cells_for_row()`: 후보 행에서 blank/invalid 셀만 실제 보정 대상 셀로 산출한다.
  - `_crop_grade_columns_image()`: 전체 표 crop 외에 오른쪽 수술종수 영역 확대 crop을 추가 생성한다.
  - `_extract_valid_corrections_and_unresolved()`: Vision 응답의 correction을 컬럼별 허용 값으로 검증하고, 실패/누락 셀은 `numeric_unresolved_cells`로 기록한다.
  - `refine_numeric_cells()`: 기본 모델을 `gpt-4.1`로 변경했다.
- `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`
  - `OCR_NUMERIC_VISION_MODEL` 환경변수를 지원한다.
  - 환경변수가 없으면 숫자 정제는 `gpt-4.1`을 사용한다.
- `scripts/generate_ocr_image_compare_html.py`
  - v45 형식의 원본 페이지 대조 HTML을 재현 가능한 스크립트로 추가했다.
  - Vision 숫자 정제 셀은 초록색, unresolved 셀은 노란색으로 표시한다.
- `tests/test_numeric_cell_refiner.py`
  - all blank 텍스트 행, 부분 누락 행, 그림/빈 행 skip, 컬럼별 허용 값, unresolved 기록, `수술종수*` 헤더, retry, 401 오류 테스트를 갱신/추가했다.

## 3. 기존 v46 한계

p068 v46 결과 중 block 4는 아래처럼 부분 누락이 남았다.

| row | 수술명 | v46 값 |
|---:|---|---|
| 0 | 근육내 양성종양 적출술 | `1`, ``, `` |
| 1 | 양성종양[근층내의 지방종...] | `1`, ``, `` |
| 2 | 용수지수술 | `1`, ``, `` |
| 3 | 탄발지(Trigger Finger) 수술 | `1`, ``, `` |
| 4 | 사각근절단술 | `1`, ``, `` |
| 5 | 사경수술 [관혈개방] | ``, `1`, `1` |
| 8 | 근성 사경수술 | `1`, ``, `` |
| 9 | 경부새열루, 새열낭적출술 | `1`, ``, `` |

원인:

- 후보 조건이 “수술종수 3개 컬럼 전부 blank”로 제한되어 있었다.
- Vision이 일부 셀만 `_corrections`로 반환하면 나머지 blank 셀은 후속 검증 대상이 아니었다.
- `1-3종` / `1-5종` / `신1-5종`이 하나의 완성 그룹이라는 도메인 규칙을 사용하지 않았다.

## 4. p068 E2E 결과

실행:

```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 68 --vision-clean
```

요약 로그:

```text
HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
Numeric cell refinement returned invalid JSON shape (attempt 1)
HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
[run_true_hybrid_local] p068 -> SUCCESS (6블록, 76.3초)
SUCCESS: 1/1 | SKIPPED: 0/1 | 총 소요: 76.8초
```

첫 번째 숫자 정제 응답은 shape 검증에 실패했고, retry 1회 후 정상 응답을 받아 적용했다.

Vision LLM 모델:

```text
OCR_NUMERIC_VISION_MODEL unset -> gpt-4.1
```

## 5. p068 Before / After

대상 block:

```text
block 4
numeric_candidate_rows: [0, 1, 2, 3, 4, 5, 8, 9]
numeric_corrections: 21건
numeric_unresolved_cells: 없음
```

| row | 수술명 | v46 before | v47 after |
|---:|---|---|---|
| 0 | 근육내 양성종양 적출술 | `1`, ``, `` | `1`, `1`, `1` |
| 1 | 양성종양[근층내의 지방종...] | `1`, ``, `` | `1`, `1`, `1` |
| 2 | 용수지수술 | `1`, ``, `` | `1`, `1`, `1` |
| 3 | 탄발지(Trigger Finger) 수술 | `1`, ``, `` | `1`, `1`, `1` |
| 4 | 사각근절단술 | `1`, ``, `` | `1`, `1`, `1` |
| 5 | 사경수술 [관혈개방] | ``, `1`, `1` | `1`, `1`, `1` |
| 8 | 근성 사경수술 | `1`, ``, `` | `1`, `1`, `1` |
| 9 | 경부새열루, 새열낭적출술 | `1`, ``, `` | `1`, `1`, `1` |

빈 행 row 6, 7, 10, 11은 수술명/수술해설 문맥이 없으므로 all blank를 유지했다.

## 6. numeric_corrections 샘플

```json
[
  {
    "row_index": 0,
    "col": "1-3종",
    "from": "",
    "to": "1",
    "method": "vision_llm",
    "reason": "complete_surgery_grade_group",
    "confidence": "high"
  },
  {
    "row_index": 0,
    "col": "1-5종",
    "from": "",
    "to": "1",
    "method": "vision_llm",
    "reason": "complete_surgery_grade_group",
    "confidence": "high"
  },
  {
    "row_index": 0,
    "col": "신1-5종",
    "from": "",
    "to": "1",
    "method": "vision_llm",
    "reason": "complete_surgery_grade_group",
    "confidence": "high"
  }
]
```

전체 p068 correction 수:

```text
21건
```

## 7. numeric_unresolved_cells

p068 E2E 결과 기준 미해결 셀은 없다.

```text
numeric_unresolved_cells: None
```

단위 테스트에서는 invalid Vision 값 또는 미판독 셀이 `numeric_unresolved_cells`에 남는 것을 확인했다.

## 8. HTML 검토 산출물

생성:

```bash
python scripts/generate_ocr_image_compare_html.py --doc 실무가이드 --pages 60-70 --output reports/ocr_compare_v47_image_compare.html
```

결과:

```text
[generate_ocr_image_compare_html] wrote reports/ocr_compare_v47_image_compare.html (3280110 bytes)
Vision 숫자 정제 count: 3
refined-cell count: 22
unresolved-cell count: 1
```

HTML 경로:

```text
reports/ocr_compare_v47_image_compare.html
```

주의: `refined-cell count`, `unresolved-cell count`는 CSS class 정의 문자열까지 포함한 단순 문자열 카운트다. 실제 p068 JSON 기준 숫자 정제 correction은 21건, unresolved는 0건이다.

## 9. pytest 결과

단위 테스트:

```text
pytest tests/test_numeric_cell_refiner.py -v
7 passed in 0.07s
```

관련 회귀:

```text
pytest tests/test_table_vision_cleaner.py tests/test_clova_ocr.py -q
18 passed in 0.07s
```

전체 회귀:

```text
........................................................................ [ 35%]
........................................................................ [ 71%]
.........................................................                [100%]
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
201 passed, 5 warnings in 3.78s
<sys>:0: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```

## 10. 남은 리스크

- Vision LLM이 한 번 invalid JSON shape를 반환할 수 있어 retry가 필요하다. 현재 1회 retry로 p068은 성공했다.
- 수술종수 영역 crop은 표 오른쪽 42%를 확대하는 휴리스틱이다. 향후 셀 좌표를 직접 산출할 수 있으면 행/셀 단위 crop으로 더 안정화할 수 있다.
- 보고서 작성 시점 기준 구현 커밋 `459adf3`은 push 완료했다. 본 보고서 파일은 별도 커밋으로 push한다.
