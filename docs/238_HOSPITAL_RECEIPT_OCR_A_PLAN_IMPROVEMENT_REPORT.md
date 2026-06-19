# 238. Hospital Receipt OCR A-Plan Improvement Report

## Summary

2026-06-16 DGX main repository 기준으로 A안 `opencv_paddle` 병원 영수증 OCR 파이프라인을 개선하고 재검증했다.

이번 개선은 자동 보험금 계산 완성이 아니라, 기존 A안의 첫 smoke 실패 원인 중 문서 분류와 row/column 매핑 품질을 보강하는 작업이다. 계산 입력 승격 정책은 유지했다. 즉, source cell에서 읽힌 값과 산식 검증을 통과한 row만 `claim_items_ready`에 포함한다.

## External References Checked

- OpenCV morphology line extraction tutorial: 수평/수직 구조 요소를 분리해 선 기반 문서 구조를 검출하는 방향이 현재 A안의 OpenCV grid 방식과 맞는다.
- PaddleOCR PP-Structure/PP-StructureV3 documentation: table/document structure recognition 계열은 A안 내부 보강보다는 다음 B안 후보로 다루는 것이 적절하다.

## Changes

### Document Classification

`src/hospital_receipt_ocr/preprocess.py`

- 단순 전역 키워드 방식에서 weighted keyword 방식으로 변경했다.
- `진단서`라는 단어 하나만으로 진단서로 분류하지 않도록 했다.
- 진료비 영수증, 진단서, 수술확인서를 각각 여러 layout/field keyword 조합으로 판정한다.
- 개선 결과, 12개 샘플 문서 유형이 기대 구조로 분류됐다.

### Detail Row Normalization

`src/hospital_receipt_ocr/normalize.py`

- 기존 위치 기반 fallback은 유지하면서, cell column id와 명칭 cell anchor를 이용해 shifted table을 보정한다.
- 숫자가 포함된 항목명 예: `2인실 병실차액`을 코드로 오인하지 않도록 code-like 판정을 좁혔다.
- 단가 셀이 비어 있고 총액만 오른쪽에 있는 경우, 총액을 단가로 오인하지 않도록 보정했다.
- 추정 계산값으로 `count/day`를 채워 넣지는 않았다. 자동 승격에 필요한 값은 계속 OCR source cell 기반이어야 한다.

### Tests

`tests/test_hospital_receipt_ocr_validation.py`

- weighted document classification 테스트 추가.
- shifted code/name columns 테스트 추가.
- digit-containing service name 테스트 추가.
- far total-as-unit 오인 방지 테스트 추가.

## DGX Validation

Command:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_opencv_grid.py \
  tests/test_run_hospital_receipt_ocr_cli.py \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_standard_opinion_excludes_only_nonpay_part \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_unresolved_split_nonpay_is_human_task_excluded_from_totals \
  -q
```

Result:

```text
15 passed in 0.17s
```

## DGX Smoke Result

Command:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python scripts/run_hospital_receipt_ocr.py \
  --input-dir data/hospital_receipts/manual_20260609/input \
  --output-dir data/hospital_receipts/manual_20260609/runs/opencv_paddle_dgx_improved3 \
  --strategy opencv_paddle \
  --redact-sensitive \
  --no-llm \
  --export-claim-items
```

Baseline:

```json
{
  "processed_documents": 12,
  "document_type_counts": {
    "medical_detail_statement": 9,
    "unknown": 2,
    "diagnosis_certificate": 1
  },
  "detail_row_count": 135,
  "verified_detail_row_count": 0,
  "claim_items_ready_count": 0,
  "validation_issue_count": 239,
  "human_task_count": 135
}
```

Improved:

```json
{
  "processed_documents": 12,
  "document_type_counts": {
    "medical_detail_statement": 9,
    "diagnosis_certificate": 1,
    "medical_bill_receipt": 1,
    "surgery_certificate": 1
  },
  "detail_row_count": 135,
  "verified_detail_row_count": 0,
  "claim_items_ready_count": 0,
  "validation_issue_count": 205,
  "human_task_count": 135
}
```

## Evaluation

개선된 점:

- 문서 유형 분류가 기대값으로 정상화됐다.
- `validation_issue_count`가 239건에서 205건으로 감소했다.
- 항목명 누락은 14건에서 1건으로 줄었다.
- `llm_used=false`, `ocr_degraded=false`로 A안 deterministic OCR 경로가 유지됐다.

남은 한계:

- 자동 승격 row는 아직 0건이다.
- 주된 원인은 `횟수/일수`처럼 작은 숫자 열이 PaddleOCR 단계에서 누락되거나, 금액 자릿수가 잘려 산식 검증을 통과하지 못하는 것이다.
- 총액 누락은 19건에서 24건으로 늘었다. 이는 잘못된 자동 승격을 피하기 위해 총액/단가 오인을 더 보수적으로 처리한 영향이다.
- 따라서 A안만으로는 현재 샘플 품질에서 자동 보험금 계산 입력을 안정적으로 생성하기 어렵다.

## Next Recommendation

다음 작업은 A안의 추가 미세조정보다 B안 `PP-Structure/table structure recognition` 또는 C안 layout/table detection backend를 같은 공통 스키마에 붙여 비교하는 것이 더 타당하다. A안은 계속 fallback 또는 기준선으로 유지하되, 자동 승격 품질은 다른 table structure backend와 비교해야 한다.
