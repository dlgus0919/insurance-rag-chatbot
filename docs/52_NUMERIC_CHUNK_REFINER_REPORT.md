# 52 Numeric Chunk Refiner Report

## 1. 배경

실무가이드 p074에서 수술종수 빈 셀이 남는 문제를 재확인했다. 원인은 VisionLLM이 적용되지 않은 것이 아니라, p074 후보 셀이 많아 응답 JSON이 `max_tokens=512`에서 중간에 잘렸고 `invalid delta format`으로 폐기된 것이었다.

## 2. 변경 사항

- `src/parser/numeric_cell_refiner.py`
  - 후보 행을 target cell 수 기준으로 chunk 분할한다.
  - 기본 chunk 한도는 `NUMERIC_CHUNK_TARGET_CELLS = 15`이다.
  - Vision 응답 토큰 한도를 `NUMERIC_VISION_MAX_TOKENS = 1536`으로 상향했다.
  - 응답 형식을 더 짧은 row compact delta로 변경했다.
  - 기존 `corrections` delta 형식도 계속 파싱한다.
  - invalid delta가 나오면 해당 chunk를 더 작은 chunk로 나눠 재시도한다.
  - 끝까지 실패한 후보 셀은 `numeric_unresolved_cells`에 `invalid_delta_format`으로 남긴다.
  - 후보/실행 상태를 `numeric_candidate_rows`, `numeric_refiner_status`, `numeric_refiner_chunks`에 기록한다.

- `scripts/run_full_ocr.py`
  - manifest table entry에 `numeric_candidate_rows`, `numeric_refiner_status`, `numeric_refiner_chunks`를 저장한다.

- 테스트
  - compact row delta 파싱 테스트 추가
  - 대량 후보 행 chunk 분할 테스트 추가
  - invalid delta 실패 시 unresolved metadata 기록 테스트 추가

## 3. 재실행 결과

명령:

```text
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,74 --force --yes --output-dir reports/full_ocr_numeric_chunk_v52/true_hybrid
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,74 --clova-native --force --yes --output-dir reports/full_ocr_numeric_chunk_v52/clova_native
```

실행 결과:

| 방식 | 페이지 | 결과 | blocks |
|---|---:|---|---:|
| True Hybrid | 64 | SUCCESS | 3 |
| True Hybrid | 74 | SUCCESS | 4 |
| CLOVA native | 64 | SUCCESS | 2 |
| CLOVA native | 74 | SUCCESS | 3 |

숫자 후보정 결과:

| 방식 | 페이지 | candidates | chunks | corrections | unresolved |
|---|---:|---:|---:|---:|---:|
| True Hybrid | 64 | 12 | 1 | 12 | 0 |
| True Hybrid | 74 | 19 | 4 | 54 | 0 |
| CLOVA native | 64 | 12 | 1 | 12 | 0 |
| CLOVA native | 74 | 19 | 4 | 54 | 0 |

p074 chunk 상세:

- `[0, 1, 2, 3, 4]`: 15 target cells, 15 corrections
- `[5, 7, 10, 11, 12]`: 13 target cells, 13 corrections
- `[13, 14, 15, 16, 17]`: 15 target cells, 15 corrections
- `[18, 19, 20, 21]`: 11 target cells, 11 corrections

## 4. HTML

생성 파일:

```text
reports/ocr_numeric_chunk_v52_compare.html
```

HTML은 실무가이드 p064/p074 원본 페이지와 True Hybrid/CLOVA native 결과를 대조한다. VisionLLM으로 채운 수술종수 셀은 초록색으로 표시된다.

## 5. 테스트

```text
pytest tests/test_numeric_cell_refiner.py tests/test_numeric_refiner_delta.py tests/test_run_full_ocr.py -q
18 passed in 0.04s
```

```text
pytest -q
221 passed, 5 warnings in 2.04s
```

## 6. Git

- Implementation commit hash: `df4c7e8`
- Push: 완료 (`master -> origin/master`)
