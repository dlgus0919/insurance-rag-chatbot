# 56 Surgery Name Boost Report

작성일: 2026-05-13  
대상 명세: `docs/56_CODEX_SPEC_SURGERY_NAME_BOOST.md`

## 1) 수정 함수 목록

- `src/rag/pipeline.py::_extract_surgery_name_from_query(question)`
  - `"X의 수술종수..."`, `"X 수술은 어떤..."` 형태 질의에서 수술명 문자열을 추출.
- `src/rag/pipeline.py::_boost_surgery_name_table_rows(hits, surgery_name)`
  - `table_json.rows[].수술명`에 부분 일치하는 청크를 상단으로 재정렬.
- `src/rag/pipeline.py::RagPipeline.retrieve_hits(...)`
  - 수술명 질의일 때 RRF 후보 풀을 확장(`final_top_k * 3`) 후 수술명 row boost를 reranker 이전 공통 경로에 적용.

## 2) 테스트 추가 내역

`tests/test_pipeline.py`에 아래 4개 테스트를 추가:

1. `test_extract_surgery_name_from_query_surgery_grade`
2. `test_extract_surgery_name_from_query_non_surgery`
3. `test_boost_surgery_name_table_rows_matched_first`
4. `test_boost_surgery_name_table_rows_no_match_preserves_order`

## 3) `pytest tests/test_pipeline.py -v -k "surgery"` 결과

실행:

```bash
pytest tests/test_pipeline.py -v -k "surgery"
```

결과:

```text
============================= test session starts ==============================
collected 22 items / 18 deselected / 4 selected

tests/test_pipeline.py::test_extract_surgery_name_from_query_surgery_grade PASSED
tests/test_pipeline.py::test_extract_surgery_name_from_query_non_surgery PASSED
tests/test_pipeline.py::test_boost_surgery_name_table_rows_matched_first PASSED
tests/test_pipeline.py::test_boost_surgery_name_table_rows_no_match_preserves_order PASSED

======================= 4 passed, 18 deselected in 0.35s =======================
```

## 4) `pytest -q` 전체 결과

실행:

```bash
pytest -q
```

결과:

```text
229 passed, 5 warnings in 3.17s
```

## 5) OCR retrieval-only eval 결과

실행:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 \
python scripts/eval.py --ocr
```

핵심 결과:

```text
[11] surgery_grade recall=OK top_pages=['64', '188', '63'] llm=SKIP
retrieval recall@8: 1.000
```

- 기준 확인: `recall@8 >= 0.975` 충족
- `ocr_011` 전환: `MISS -> OK(HIT)` 확인 (p64가 top_pages 첫 항목으로 상승)

## 6) 최종 판정 / 블로커

- 최종 판정: `PASS`
- 잔여 블로커: `None`
