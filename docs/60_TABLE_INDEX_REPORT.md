# 60 Table Index 구현 보고서

작성일: 2026-05-13

## 1) 구현 파일

- `scripts/build_table_index.py`
  - `data/extracted/실무가이드/tables/*.json`에서 수술종수표와 장해분류표를 추출해 Parquet 인덱스를 생성한다.
- `data/index/surgery_grades.parquet`
  - 수술종수표 행 단위 인덱스.
- `data/index/disability_rates.parquet`
  - 장해분류표 행 단위 인덱스.
- `src/rag/table_store.py`
  - `TableStore` 직접 조회 인터페이스.
- `src/rag/pipeline.py`
  - `_build_structured_context()`의 C hook 활성화.
  - `RagPipeline.__init__()`에 `table_store` 주입 지점 추가.
- `tests/test_table_store.py`
  - 임시 Parquet 기반 단위 테스트 5건.

## 2) Parquet 생성 결과

실행:

```text
python scripts/build_table_index.py
```

결과:

```text
surgery_grades: 2408 rows -> data/index/surgery_grades.parquet
disability_rates: 100 rows -> data/index/disability_rates.parquet
skip_stats:
- skipped_empty_surgery_name: 380
- skipped_figure_disability: 2
- skipped_empty_disability_rate: 3
- skipped_empty_disability_classification: 0
- skipped_disability_files: 1
```

## 3) 컬럼 목록

### `surgery_grades.parquet`

```text
['수술명', '수술명_원문', '수술해설', '종_1_3', '종_1_5', '종_신1_5', 'source_page_label', 'source_file', 'table_type', 'table_group_id', 'group_page_range', 'is_page_continued']
```

### `disability_rates.parquet`

```text
['신체부위', '장해분류', '장해분류_원문', '지급률', '지급률_원문', '지급률_범위_최소', '지급률_범위_최대', 'source_page_label', 'source_file', 'table_type', 'table_group_id', 'is_page_continued']
```

## 4) 신체부위별 장해분류 행 수

```text
귀의 장해                 6
눈의 장해                10
다리의 장해               12
발가락의 장해               7
손가락의 장해               6
신경계·정신행동 장해          11
신경계·정신행동 장해 (ADL)     8
씹어먹거나 말하는 장해          9
외모의 추상 장해             2
정신행동 장해 (GAF)         4
척추(등뼈)의 장해            9
체간골의 장해               3
코의 장해                 1
팔의 장해                 9
흉복부장기 및 비뇨생식기의 장해     3
```

## 5) `is_page_continued` 분포

수술종수표는 첫 수술종수표 페이지(p.33)의 행 13건이 `False`, 이후 연속 페이지 행 2,395건이 `True`로 기록됐다.

```text
True     2395
False      13
```

## 6) 핵심 조회 테스트

```text
충수절제술 조회 OK: 1-5종=2, p.109
두 눈 실명 조회 OK: 지급률=100%, p.236
한 팔 손목 이상 조회 OK: 지급률=60%
두 귀 청력 상실 조회 OK: 지급률=80%
모든 핵심 조회 PASS
```

## 7) C hook 구조화 컨텍스트 샘플

```text
[구조화 데이터 — 직접 조회 (C)]
수술명: 충수절제술
1-3종: 1 | 1-5종: 2 | 신1-5종: 2
출처: 실무가이드 p.109
```

```text
[구조화 데이터 — 직접 조회 (C)]
신체부위: 눈의 장해
장해 분류: 1) 두 눈이 멀었을 때 / - 안구적출 광각무. 광각유. 안전수지. 만전수통
지급률: 100%
출처: 실무가이드 p.236
```

## 8) 테스트 결과

```text
pytest tests/test_table_store.py -v
5 passed
```

```text
pytest -q
240 passed, 5 warnings in 10.32s
```

## 9) OCR retrieval eval

실행:

```text
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

결과:

```text
retrieval recall@8: 1.000
출처 페이지 정확도: N/A (LLM skip)
수술종수 정확도 (grade_accuracy): N/A
장해 지급률 정확도 (rate_accuracy): N/A
키워드 포함율 (keyword_coverage): N/A
```

## 10) 미처리 행

- 빈 수술명 스킵: 380건
- `[그림]` 장해 행 스킵: 2건
- 지급률 미검출 장해 행 스킵: 3건
- 파일 단위 스킵: 1건 (`p276_t00.json`, 명세상 rows 전체 공백/비정형 파일)

## 11) 특이사항

- 실제 원천 테이블에는 명세의 장해분류 매핑에 없던 `p248_t00.json`(외모의 추상 장해), `p254_t00.json`(팔의 장해), `p266_t00.json`(흉복부장기 및 비뇨생식기의 장해)이 존재했다.
- 검증 핵심 질의인 "한 팔의 손목 이상" 조회를 위해 `p254_t00.json`을 `팔의 장해`로 매핑했다.
- 위 추가 매핑 후 `disability_rates.parquet`은 100행으로 명세 기대 범위에 도달했다.
