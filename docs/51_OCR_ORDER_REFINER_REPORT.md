# 51 OCR 순서/후보정 리포트

## 1. 변경 요약

명세 51에 따라 CLOVA 필드 텍스트 재조립과 Vision LLM 숫자 후보정 응답 형식을 수정했다.

- `src/parser/clova_ocr.py`
  - `_fields_to_lines()`가 줄은 Y 좌표 기준으로 나누되, 같은 줄 내부 단어는 CLOVA 원본 field 순서를 보존하도록 변경했다.
  - 기존처럼 `(center_y, center_x)`로 재정렬하지 않으므로, CLOVA가 이미 올바른 읽기 순서로 반환한 단어가 기울기/박스 좌표 때문에 뒤집히는 문제를 막는다.
  - 명세 범위에 맞춰 `_group_fields_into_rows()`는 이번 작업에서 추가 변경하지 않았다.

- `src/parser/numeric_cell_refiner.py`
  - Vision LLM 프롬프트를 전체 `table_json` 에코 방식에서 delta-only 방식으로 변경했다.
  - 응답 형식은 `corrections` / `unresolved` 목록만 허용한다.
  - 후보 행에는 `row_index`, `수술명`, 현재 수술종수 값만 전달한다.
  - `max_tokens`를 `512`로 낮췄다.
  - `_is_valid_delta()`를 추가하고, `_extract_valid_corrections_and_unresolved()`가 delta를 직접 검증/적용하도록 수정했다.

## 2. 테스트 추가

- `tests/test_clova_field_order.py`
  - 같은 줄에서 X 좌표가 어긋나도 CLOVA 원본 field 순서를 보존하는지 검증했다.
  - 두 줄 이상인 경우 줄 분리는 유지되고, 줄 내부 X 정렬은 적용되지 않음을 확인했다.

- `tests/test_numeric_refiner_delta.py`
  - delta-only correction 적용 검증
  - 허용 범위를 벗어난 값 reject 검증
  - 존재하지 않는 row/cell 응답 처리 검증

기존 `tests/test_numeric_cell_refiner.py`도 delta-only 응답에 맞춰 갱신했다.

## 3. p255 단어 순서 검증

검증 대상 문장:

- 정상: `원칙적으로 각각`
- 오류: `각각 원칙적으로`

결과:

| 방식 | 정상 문구 포함 | 오류 문구 포함 | 비고 |
|---|---:|---:|---|
| True Hybrid | Yes | No | `... 지급률은 원칙적으로 각각 합산하되 ...` |
| CLOVA native | Yes | No | `... 지급률은 원칙적으로 각각 합산하되 ...` |

단위 테스트에서는 CLOVA field 원본 순서가 `원칙적으로` -> `각각`인 상황에서 X 좌표가 반대로 들어와도 결과가 `원칙적으로 각각`으로 유지되는 케이스를 추가했다. 기존 X 정렬 방식이었다면 이 케이스는 `각각 원칙적으로`로 뒤집힌다.

## 4. p064 숫자 후보정 검증

재실행 결과 p064 수술종수 후보정은 양쪽 방식 모두 동일하게 적용됐다.

| 방식 | numeric corrections | unresolved |
|---|---:|---:|
| True Hybrid | 12 | 0 |
| CLOVA native | 12 | 0 |

주요 correction 샘플:

| 방식 | row_index | col | from | to | method | confidence |
|---|---:|---|---|---|---|---|
| True Hybrid | 0 | 1-3종 | 빈값 | 1 | vision_llm | high |
| True Hybrid | 3 | 1-3종 | 빈값 | 1 | vision_llm | high |
| True Hybrid | 4 | 1-3종 | 빈값 | 1 | vision_llm | high |
| True Hybrid | 5 | 1-3종 | 빈값 | 1 | vision_llm | high |
| CLOVA native | 0 | 1-3종 | 빈값 | 1 | vision_llm | high |
| CLOVA native | 3 | 1-3종 | 빈값 | 1 | vision_llm | high |
| CLOVA native | 4 | 1-3종 | 빈값 | 1 | vision_llm | high |
| CLOVA native | 5 | 1-3종 | 빈값 | 1 | vision_llm | high |

전체 보정 row index:

- `0, 3, 4, 5, 6, 7, 9, 12, 13, 14, 15, 16`
- 대상 컬럼: `1-3종`
- 모두 `from="" -> to="1"`, `method="vision_llm"`, `reason="complete_surgery_grade_group"`

## 5. 회귀 페이지 품질 확인

| 페이지 | 방식 | blocks | tables | vision_cleaned tables | numeric corrections | unresolved |
|---:|---|---:|---:|---:|---:|---:|
| 68 | True Hybrid | 5 | 2 | 2 | 0 | 0 |
| 68 | CLOVA native | 4 | 2 | 2 | 0 | 0 |
| 74 | True Hybrid | 4 | 1 | 1 | 0 | 0 |
| 74 | CLOVA native | 3 | 1 | 1 | 0 | 0 |
| 151 | True Hybrid | 5 | 2 | 2 | 16 | 0 |
| 151 | CLOVA native | 3 | 2 | 2 | 16 | 0 |

## 6. E2E 재실행

출력 경로:

- `reports/full_ocr_method_compare_v51/true_hybrid`
- `reports/full_ocr_method_compare_v51/clova_native`
- `reports/ocr_method_compare_v51.html`

실행 요약:

| 방식 | 문서 | 페이지 | 결과 |
|---|---|---|---|
| True Hybrid | 실무가이드 | 64,65,68,74,151,255,279 | SUCCESS 7/7 |
| True Hybrid | 상담사례집 | 65,189,211,273 | SUCCESS 4/4 |
| CLOVA native | 실무가이드 | 64,65,68,74,151,255,279 | SUCCESS 7/7 |
| CLOVA native | 상담사례집 | 65,189,211,273 | SUCCESS 4/4 |

HTML 확인:

- `reports/ocr_method_compare_v51.html` 생성 완료
- 11개 페이지에 대해 원본 이미지, True Hybrid 결과, CLOVA native 결과를 대조할 수 있다.
- p255 순서 오류 확인 문구와 p064/p151 숫자 후보정 메타데이터를 포함한다.

## 7. 테스트 결과

명세 지정 테스트:

```text
pytest tests/test_clova_field_order.py tests/test_numeric_refiner_delta.py -v
7 passed in 0.06s
```

추가 회귀 테스트:

```text
pytest tests/test_clova_field_order.py tests/test_clova_word_order.py -v
9 passed in 0.02s
```

```text
pytest tests/test_numeric_refiner_delta.py tests/test_numeric_cell_refiner.py -v
10 passed in 0.04s
```

전체 테스트:

```text
pytest -q
219 passed, 5 warnings in 2.15s
```

## 8. 남은 주의점

- E2E 중 일부 Vision table cleaner 호출에서 invalid JSON 경고가 있었으나, 해당 페이지 OCR 실행 자체는 모두 성공했다.
- 이번 명세 범위는 `_fields_to_lines()`와 숫자 후보정 delta 처리에 한정했다.
- 생성된 전체 OCR 산출물 디렉터리는 로컬 검토용으로 유지하고, 커밋 대상은 코드/테스트/보고서/비교 HTML로 한정한다.

## 9. Git

- Implementation commit hash: `f1b39ce`
- Push: 완료 (`master -> origin/master`)
