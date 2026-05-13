# 65_N_VALUE_GUARD_REPORT

작성일: 2026-05-13  
대상 명세: `docs/65_CODEX_SPEC_N_VALUE_GUARD.md` (+ `docs/66_OCR_DIRECT_CORRECTION_PLAN.md` 참고 재평가)

## 1) 구현 요약

수정 파일:

- `src/rag/table_store.py`
- `tests/test_table_store.py`

핵심 수정:

1. 중간점(·) 포함 문자열 정규화 강화
   - `_MIDDLE_DOT_PATTERN` 추가
   - `_normalize_lookup_text()`가 공백 + 중간점 계열 문자를 제거하도록 변경

2. 수술종수 조회 시 all-`N` 행 차단
   - `_GRADE_COLUMNS = ("종_1_3", "종_1_5", "종_신1_5")` 추가
   - `lookup_surgery_grade()`에서 hit 후보를 순회하며 세 grade 값이 모두 `N`인 행은 skip
   - 유효 행이 없으면 `None` 반환 (C 주입 방지)

## 2) 버그 A 검증 (중간점 정규화)

실측 비교:

- 구 로직(공백만 제거):  
  `수족골적출술` in `수·족골적출술(=수,족골적제술)` => **False**
- 신 로직(중간점 포함 제거):  
  `수족골적출술` in `수족골적출술(=수,족골적제술)` => **True**

추가 확인:
- `_normalize_lookup_text("수 · 족골 적출술\n(=수,족골 적제술)")`
  -> `"수족골적출술(=수,족골적제술)"`

## 3) 버그 B 검증 (all-N 행 차단)

샘플 데이터(`절개술`=N/N/N, `충수절제술`=2/3/2)로 확인:

- `lookup_surgery_grade("절개술")` -> `None` (기대 동작)
- `lookup_surgery_grade("충수절제술")` -> 반환, `종_1_3="2"` (기대 동작)

## 4) 추가 테스트

`tests/test_table_store.py`에 3개 케이스 추가:

1. `test_normalize_removes_middle_dot`
2. `test_lookup_surgery_grade_middle_dot_match`
3. `test_lookup_surgery_grade_skips_all_n_rows`

## 5) 테스트 결과

- `pytest tests/test_table_store.py -v` -> **8 passed**
- `pytest -q` -> **246 passed, 0 failed**

## 6) OCR 데이터 품질 전반 재평가 (명세 66 관점)

### 6-1. 수술종수 Parquet 유효 행 현황

- `surgery_grades.parquet` 총 행 수: **2408**
- all-`N`(비급여) 행 수: **574**
- 유효 행 수(비급여 제외): **1834**

=> 이번 수정으로 C lookup 단계에서 최소 574행이 방어적으로 차단됨.

### 6-2. 구형 수술분류표(p006~p021) 반영 현황

- `data/extracted/실무가이드/tables`의 p006~p021 JSON 파일 수: **21**
- 하지만 `data/index/surgery_grades.parquet`에서 p006~p021 유래 행 수: **0**

=> 현재 인덱스 산출물에는 구형표가 직접 반영되지 않은 상태이며, `spec #63`의 old-table marker guard와 함께 이중 방어 상태.

### 6-3. 상담사례집 노이즈 청크 현황

- `상담사례집` 청크 총량: **1181**
- 50자 미만: **407**
- 숫자-only(정규식 `[\d\s\n]+`) 50자 미만: **67** (전체의 **5.67%**)

=> 노이즈는 존재하나, 명세 66 문서의 과거 추정(숫자-only 393건)과 현재 산출물은 차이가 큼.

## 7) 현재 평가 상태 및 해석

최근 OCR eval(사용자 실행 기준)에서 확인된 핵심 지표:

- retrieval recall@8: 1.000
- grade_accuracy: 0.294
- rate_accuracy: 0.357
- keyword_coverage: 0.515

이번 수정(#65)은 주로 C 주입 안정성(오탐/누락 방지) 개선이며, OCR 원문 품질 자체(글자 인식률) 개선 작업은 아님.

## 8) 장시간 실행 필요 작업(미실행, 사용자 보고)

OCR 데이터를 실제로 다시 재생성/재적재하려면 아래는 장시간 명령입니다.

1. OCR 전체 재실행  
`python scripts/run_full_ocr.py --doc all --yes`

2. OCR 포함 재인제스트/인덱스 재생성  
`python scripts/ingest.py --include-ocr --stage all`

3. OCR eval 재실행  
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_TEMPERATURE=0 python scripts/eval.py --ocr`

사용자 요청에 따라 위 장시간 명령은 이번 턴에서 실행하지 않았습니다.

