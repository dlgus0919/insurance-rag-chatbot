# 242. 병원 영수증 OCR D안 TATR 실실행 결과 보고서

작성일: 2026-06-16  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`  
실행 결과 경로: `data/hospital_receipts/manual_20260609/runs/tatr_ocr_12_gpu`

## 1. 목적

D안 `tatr_ocr` backend를 DGX 메인 저장소에 실제 반영하고, 12장 병원 서류 샘플 세트에 대해 실실행 결과를 평가했다.

이번 작업의 목표는 자동 보험금 계산 적용이 아니라 다음 세 가지를 확인하는 것이다.

1. TATR 기반 table structure + PaddleOCR text assignment가 DGX에서 안정적으로 실행되는가
2. 12장 샘플을 공통 OCR 계약으로 처리할 수 있는가
3. 자동 보험금 계산 입력으로 승격 가능한 row가 실제로 생기는가

외부 API, LLM 서버, VLM 서버는 사용하지 않았다.

## 2. 구현 내용

추가/수정 파일:

- `src/hospital_receipt_ocr/backends/tatr_ocr.py`
- `src/hospital_receipt_ocr/runner.py`
- `scripts/run_hospital_receipt_ocr.py`
- `tests/test_hospital_receipt_ocr_backends.py`
- `tests/test_run_hospital_receipt_ocr_cli.py`

핵심 구현:

- `tatr_ocr` 전략 추가
- Table Transformer detection/structure-recognition 모델로 row/column 구조 추출
- 기존 Korean `PaddleOcrAdapter` page OCR 결과를 재사용하여 cell text assignment
- backend 내부 model cache 추가
- CUDA 가능 시 GPU 사용, 아니면 CPU fallback
- page 전체 OCR text를 별도 보관해 문서 유형 분류에 활용

의존성:

- DGX `.venv` 기준 `transformers`, `torch`, `paddleocr`는 이미 존재
- TATR 실행에 필요한 `timm`를 추가 설치

## 3. 검증

로컬 단위 테스트:

```bash
python -m pytest tests/test_hospital_receipt_ocr_backends.py tests/test_run_hospital_receipt_ocr_cli.py -q
```

결과:

```text
11 passed
```

로컬 compile 검증:

```bash
python -m compileall -q src/hospital_receipt_ocr scripts/run_hospital_receipt_ocr.py
```

결과: 통과

DGX 단위/회귀 테스트:

```bash
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_opencv_grid.py \
  tests/test_run_hospital_receipt_ocr_cli.py \
  tests/test_hospital_receipt_ocr_backends.py \
  -q
```

결과:

```text
21 passed
```

DGX compile 검증:

```bash
.venv/bin/python -m compileall -q src/hospital_receipt_ocr scripts/run_hospital_receipt_ocr.py
```

결과: 통과

## 4. 12장 실샘플 실행 결과

실행 요약:

```json
{
  "strategy": "tatr_ocr",
  "input_count": 12,
  "processed_documents": 12,
  "document_type_counts": {
    "medical_detail_statement": 9,
    "diagnosis_certificate": 1,
    "medical_bill_receipt": 1,
    "surgery_certificate": 1
  },
  "detail_row_count": 127,
  "verified_detail_row_count": 0,
  "claim_items_ready_count": 0,
  "validation_issue_count": 182,
  "human_task_count": 127,
  "ocr_degraded": false,
  "ocr_unavailable_reason": ""
}
```

평가:

- 12장 전체 처리 완료
- 문서 유형 분류는 기대한 분포와 일치
  - 세부산정내역 9장
  - 영수증 1장
  - 진단서 1장
  - 수술확인서 1장
- 세부 row 후보 127건 생성
- 검증 완료 row 0건
- 자동 보험금 계산 입력 승격 0건

## 5. 주요 품질 진단

`validation_report.json` 기준 이슈 분포:

- `단가/횟수/일수/총액 중 일부가 비어 산식 검증이 불완전합니다.`: 124건
- `총액을 파싱할 수 없습니다.`: 23건
- 나머지는 금액 구성 합계 불일치 또는 `단가 * 횟수 * 일수 != 총액`

severity 분포:

- warning 159건
- error 23건

대표 관찰:

1. 문서 분류는 성공했다.
2. table 구조는 일정 수준 잡혔지만, row별 핵심 text assignment가 충분히 복원되지 않았다.
3. 실제 detail row 초반부를 보면 `total_amount`만 남고 `item_text`, `code`, `unit_price`, `quantity`가 거의 비어 있다.
4. 따라서 산식 검증이 대부분 시작조차 되지 못한다.

즉, D안의 현재 병목은 문서 분류가 아니라 **cell alignment와 text assignment 품질**이다.

## 6. A안 대비 평가

동일 12장 샘플 기준:

| 전략 | 문서 분류 | detail rows | verified rows | validation issues | human tasks |
| --- | --- | ---: | ---: | ---: | ---: |
| A `opencv_paddle` | detail 9 / receipt 1 / diagnosis 1 / surgery 1 | 135 | 0 | 205 | 135 |
| D `tatr_ocr` | detail 9 / receipt 1 / diagnosis 1 / surgery 1 | 127 | 0 | 182 | 127 |

해석:

- D안은 A안과 동일한 문서 분류 성능을 냈다.
- validation issue 수는 A안보다 줄었다.
- 그러나 verified row는 여전히 0건이다.
- detail row 수 자체는 A안보다 적다.

따라서 D안은 A안을 대체하는 승리 전략이 아니라, **구조 인식 비교용 실험 backend**로 보는 것이 맞다.

## 7. 결론

현재 D안은 다음 수준까지 도달했다.

- DGX에서 실제 실행 가능
- 12장 샘플 처리 가능
- 공통 OCR 산출물 계약과 호환 가능
- 문서 유형 분류는 실용 수준

하지만 아직 다음 수준에는 도달하지 못했다.

- row별 코드/명칭/단가/횟수/일수 안정 복원
- 산식 검증 통과 row 생성
- 자동 보험금 계산 입력 승격

결론적으로 D안은 **채택 가능한 production backend가 아니라, 구조 인식 비교 실험 backend**다.

## 8. 다음 작업 권장

우선순위는 다음이 적절하다.

1. A안을 기준선으로 유지한다.
2. D안은 TATR row/column 구조를 A안 grid 보정에 부분 활용할지 검토한다.
3. D안 단독 후처리 wrapper를 계속 늘리는 것은 보류한다.
4. 자동 계산 품질을 올리려면 D안 확장보다 A안의 cell assignment와 숫자 열 복원 개선이 더 우선이다.

## 9. Ponytail 검토

이번 D안 diff에는 새 의존성 최소화, 기존 OCR adapter 재사용, 기존 runner 계약 유지 원칙을 적용했다.

과잉 설계 관점 결론:

```text
Lean already. Ship.
```
