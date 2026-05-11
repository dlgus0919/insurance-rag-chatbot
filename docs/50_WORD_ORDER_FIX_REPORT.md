# 50 OCR 단어 순서 오류 수정 보고서

## 변경 함수

- `src/parser/clova_ocr.py::_fields_to_lines()`: CLOVA `lineBreak` 플래그 사용을 제거하고, Y 중심 좌표 간격 기반 줄 분리로 변경했다. `row_gap=None`이면 필드 높이 중앙값 × 0.6, 최소 8px로 자동 계산한다.
- `src/parser/clova_ocr.py::_group_fields_into_rows()`: 고정 `row_gap=20.0` 기본값을 `None`으로 바꾸고 동일한 adaptive gap 계산을 적용했다. 명시적 `row_gap` 인수는 계속 동작한다.
- `src/parser/clova_ocr.py` remainder 처리: PP-Structure/layout region에 매칭되지 않은 CLOVA field를 하나의 블록으로 합치지 않고, row/paragraph gap 기준으로 복수 텍스트 블록으로 분리하도록 보완했다.

## 추가 사용자 요청 반영

- `scripts/run_full_ocr.py`: Vision LLM 표/수술종수 후보정을 기본 적용으로 변경했다. 필요 시 `--no-vision-clean`으로 끌 수 있다.
- `scripts/run_full_ocr.py`: `--clova-native` 옵션을 추가해 PP-Structure layout 전달 없이 CLOVA native table detection만으로 처리할 수 있게 했다.
- `tests/test_run_full_ocr.py`: `--clova-native` 경로가 PP-Structure를 호출하지 않고 `layout_regions=None`으로 CLOVA를 호출하는지 검증하는 테스트를 추가했다.

## 단위 테스트

```bash
pytest tests/test_clova_word_order.py -v
```

결과:

```text
5 passed in 0.02s
```

## 관련 회귀 테스트

```bash
pytest tests/test_clova_ocr.py tests/test_run_full_ocr.py -q
```

결과:

```text
20 passed in 0.05s
```

## 전체 테스트

```bash
pytest -q
```

결과:

```text
212 passed, 5 warnings in 2.00s
```

경고는 기존 `tests/test_pdf_extractor.py`의 SWIG 타입 DeprecationWarning이다.

## Before/After 비교

테스트 필드:

```text
손가락(lineBreak=True), 골절, 고정술
```

세 field는 시각적으로 같은 줄에 있으나, 기존 구현은 Y 정렬 후 `lineBreak=True`를 적용했다.

기존 출력:

```text
손가락
골절 고정술
```

수정 후 출력:

```text
손가락 골절 고정술
```

## Smoke 실행

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 71,81 --force --yes
```

결과:

```text
SUCCESS: 2/2 | SKIPPED: 0/2 | FAILED: 0/2 | 소요: 2m 34s
```

확인:

- `data/extracted/실무가이드/text/p071_b*.txt` 안에 `"71"` 문자열 없음
- `data/extracted/실무가이드/text/p081_b*.txt` 안에 `"81"` 문자열 없음
- footer/page label로 보이는 `78 claim실무 종합가이드`, `88 claim실무 종합가이드`는 별도 텍스트 블록으로 분리되어 본문 문장 중간에 섞이지 않았다.

## 방법론 비교 재실행

단어 순서 수정 후 동일 페이지 세트로 두 OCR 방법론을 재실행했다.

- 대상 페이지:
  - 실무가이드: `64,65,68,74,151,255,279`
  - 상담사례집: `65,189,211,273`
- True Hybrid:
  - `python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,65,68,74,151,255,279 --force --yes --output-dir reports/full_ocr_method_compare_after_word_order/true_hybrid`
  - `python scripts/run_full_ocr.py --doc 상담사례집 --pages 65,189,211,273 --force --yes --output-dir reports/full_ocr_method_compare_after_word_order/true_hybrid`
- CLOVA native:
  - `python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,65,68,74,151,255,279 --clova-native --force --yes --output-dir reports/full_ocr_method_compare_after_word_order/clova_native`
  - `python scripts/run_full_ocr.py --doc 상담사례집 --pages 65,189,211,273 --clova-native --force --yes --output-dir reports/full_ocr_method_compare_after_word_order/clova_native`

비교 HTML:

```text
reports/ocr_method_compare_after_word_order.html
```

검증:

- HTML 크기: `1,476,003 bytes`
- 페이지 섹션: `11`
- True Hybrid 카드: `11`
- CLOVA native 카드: `11`

표/후보정 요약:

| 방법 | 문서 | table | native_table | vision_cleaned | numeric_refined |
| --- | --- | ---: | ---: | ---: | ---: |
| True Hybrid | 실무가이드 | 8 | 8 | 8 | 5 |
| True Hybrid | 상담사례집 | 2 | 2 | 0 | 0 |
| CLOVA native | 실무가이드 | 8 | 8 | 8 | 4 |
| CLOVA native | 상담사례집 | 2 | 2 | 1 | 0 |

일부 Vision 응답은 JSON shape 검증에서 실패해 해당 블록의 후보정이 적용되지 않았다. 이 경우 기존 OCR table_json을 유지하며 다음 페이지 처리는 계속된다.

## 잔여 블로커

None
