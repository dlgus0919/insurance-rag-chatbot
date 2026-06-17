# 243. 온디바이스 병원 영수증 OCR A~D안 종합 평가 보고서

작성일: 2026-06-17  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`  
샘플 경로: `data/hospital_receipts/manual_20260609`

## 1. 목적

병원 영수증/진료비 세부산정내역서/진단서/수술확인서 12장 샘플에 대해 온디바이스 OCR 방식 A~D안을 비교하고, 이 결과만으로 보험금 계산에 필요한 구조화 입력을 만들 수 있는지 평가한다.

평가 대상은 다음 네 가지다.

| 구분 | 전략 | 핵심 방식 |
| --- | --- | --- |
| A안 | `opencv_paddle` | OpenCV grid/cell 검출 + Korean PaddleOCR |
| B안 | `ppstructure` | PaddleOCR PP-Structure/TableSystem + Korean OCR 보강 |
| C안 | `surya` | Surya table recognition/OCR |
| D안 | `tatr_ocr` | Table Transformer 구조 인식 + PaddleOCR text assignment |

## 2. 보험금 계산 투입 기준

`docs/235_HOSPITAL_RECEIPT_CLAIM_REQUIRED_FIELDS.md` 기준으로 자동 계산 입력은 다음 조건을 만족해야 한다.

- 값은 원본 문서의 source cell/source text에서 읽혀야 한다.
- page, row, cell, bbox, validation status를 추적할 수 있어야 한다.
- 세부내역 row는 `금액 * 횟수 * 일수 == 총액` 또는 구성 금액 합계 검증을 통과해야 한다.
- 검증 실패 row는 `claim_items_ready`에 들어가면 안 된다.
- OCR confidence만으로 계산 입력에 승격하면 안 된다.
- LLM/VLM 또는 코드가 수치, 지급 판단, 공제율, 한도, 면책 여부를 생성하면 안 된다.

따라서 이 보고서에서 "활용 가능"은 단순히 글자를 일부 읽었다는 뜻이 아니라, 보험금 계산 파이프라인에 자동 투입 가능한 `ClaimItemInput` 후보를 만들 수 있다는 뜻이다.

## 3. 샘플 데이터

입력은 12장 병원 서류 이미지다.

| 파일군 | 문서 유형 |
| --- | --- |
| `_1.jpg` ~ `_9.jpg` | 진료비 세부산정내역서 |
| `_10.jpg` | 진단서 |
| `_11.jpg` | 진료비 계산서·영수증 |
| `_12.jpg` | 수술확인서 |

테스트 산출물은 각 전략별 `run_summary.json`, `documents.jsonl`, `detail_rows.jsonl`, `validation_report.json`, `claim_manifest.json`, `claim_items_ready.json`, `human_tasks.jsonl`, `cell_artifacts/`를 기준으로 평가했다.

## 4. 결과 요약

최종 비교 기준 런은 다음이다.

| 구분 | 결과 경로 | 문서 분류 | detail rows | verified rows | claim items | validation issues | human tasks | degraded |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| A안 | `runs/opencv_paddle_dgx_improved3` | detail 9 / receipt 1 / diagnosis 1 / surgery 1 | 135 | 0 | 0 | 205 | 135 | false |
| B안 | `runs/ppstructure_korean_ocr_dgx` | unknown 12 | 0 | 0 | 0 | 12 | 0 | false |
| C안 | `runs/surya_real_12_background` | unknown 12 | 0 | 0 | 0 | 20 | 1 | true |
| D안 | `runs/tatr_ocr_12_gpu` | detail 9 / receipt 1 / diagnosis 1 / surgery 1 | 127 | 0 | 0 | 182 | 127 | false |

공통 결론:

- 모든 방식에서 `verified_detail_row_count = 0`이다.
- 모든 방식에서 `claim_items_ready_count = 0`이다.
- 따라서 네 방식 중 어떤 것도 현재 샘플 기준으로 자동 보험금 계산 입력을 만들지 못했다.

## 5. A안 평가: OpenCV Grid + PaddleOCR

A안은 현재 네 방식 중 가장 실용적인 기준선이다.

장점:

- 12장 문서 유형 분류를 기대값으로 맞췄다.
- 세부산정내역 row 후보 135건을 생성했다.
- deterministic path이며 외부 API와 LLM/VLM을 쓰지 않는다.
- source cell/bbox 기반 산출물 구조를 만들 수 있다.

한계:

- 검증 완료 row가 0건이다.
- 작은 `횟수`, `일수` 열이 자주 누락된다.
- 우측 금액 열과 비급여/본인부담 금액이 잘리거나 밀린다.
- 금액 자릿수 오류와 row/column shift가 발생한다.
- `금액 * 횟수 * 일수 == 총액` 검증을 통과하지 못한다.

평가:

A안은 후보 생성과 Human Task 작성에는 쓸 수 있다. 그러나 자동 계산 투입에는 부족하다. 현재 품질에서 계산 입력으로 승격하면 잘못된 금액을 넣을 위험이 높다.

## 6. B안 평가: PP-Structure

B안은 실행 가능한 backend 형태는 만들었지만 실샘플 품질이 낮았다.

장점:

- PaddleOCR 계열 안에서 table/layout 인식을 시도할 수 있다.
- 기존 OCR dependency 계열과 맞춰 관리할 수 있다.

한계:

- 최종 런에서 12장 모두 `unknown`으로 분류됐다.
- 세부 row 후보가 0건이다.
- PP-Structure table path가 병원 세부산정내역의 행/열을 안정적으로 복원하지 못했다.
- 현재 DGX 설치본에서는 한국어 병원 영수증 표에 직접 맞는 구조 인식 품질을 보이지 못했다.

평가:

B안은 단독 backend로는 보험금 계산에 사용할 수 없다. A안 grid 후보의 보조 sanity check 정도로 제한해야 한다.

## 7. C안 평가: Surya

C안은 실제 Surya 실행까지 확인했지만 결과는 계산에 연결할 수 없었다.

장점:

- DGX에서 실행 자체는 가능했다.
- 일부 페이지에서 table artifact를 생성했다.

한계:

- 12장 모두 `unknown`으로 분류됐다.
- 세부 row 후보가 0건이다.
- `claim_items_ready`가 0건이다.
- 실제 table artifact도 12장 중 일부에만 생성됐다.
- 생성된 table도 병원 세부산정내역의 실제 행 단위와 잘 맞지 않았다.
- vLLM/Docker server 성격의 실행 경로가 있어 지속 실행 로직으로 쓰기에는 운영 부담이 있다.

평가:

C안은 현재 결과만으로는 채택하기 어렵다. 성능 개선이 확인되기 전까지 후처리 코드를 늘리는 것은 과잉 구현이다.

## 8. D안 평가: TATR + PaddleOCR

D안은 A안과 함께 문서 분류는 성공했지만, row 내부 값 정합성은 부족했다.

장점:

- 12장 문서 유형 분류가 기대값과 일치했다.
- 세부 row 후보 127건을 생성했다.
- validation issue 수는 A안보다 적었다.
- Table Transformer 구조 인식을 통해 A안과 다른 구조 신호를 얻을 수 있다.

한계:

- 검증 완료 row가 0건이다.
- `claim_items_ready`가 0건이다.
- 많은 row에서 `total_amount`만 남고 `item_text`, `code`, `unit_price`, `quantity`가 비어 있다.
- 병목은 table detection보다 cell alignment와 OCR text assignment에 있다.

평가:

D안은 구조 인식 비교용 backend로는 의미가 있다. 하지만 단독으로 자동 계산 입력을 만들 수 없고, A안을 대체할 수준도 아니다.

## 9. 앙상블 가능성

A~D안 결과만으로 단순 앙상블을 해도 자동 계산 입력을 만들기는 어렵다.

이유:

- A/D 모두 문서 분류는 맞지만 검증 완료 row가 없다.
- B/C는 row 후보 생성 자체가 거의 실패했다.
- 서로 다른 backend가 같은 row의 `code`, `item_text`, `unit_price`, `quantity`, `days`, `total_amount`, 금액 구성값을 동시에 확증해 주지 못한다.
- 한 backend의 누락값을 다른 backend 값으로 채우면 source cell provenance가 약해진다.
- 추정 보정으로 값을 채우면 "원본 source에서 읽은 값만 계산에 투입"한다는 원칙을 깨게 된다.

가능한 제한적 활용:

- A안 row 후보를 기준으로 D안 구조 신호를 참고해 Human Task 우선순위를 정한다.
- A/D가 같은 문서 유형을 맞춘 경우 문서 분류 confidence를 올린다.
- 영수증 총액 후보는 세부내역 합계 검증의 참고값으로만 둔다.
- 자동 계산 입력이 아니라 수동 검토 화면의 보조 evidence로 사용한다.

불가능한 활용:

- 누락된 `횟수`, `일수`, 금액을 추정해 자동 계산에 넣기
- 영수증 요약 총액만으로 세부 line item 만들기
- OCR confidence만으로 `claim_items_ready` 생성하기
- LLM/VLM이 수치나 지급 판단을 새로 생성하게 하기

## 10. 최종 결론: 온디바이스 OCR 활용 불가능 판단 근거

현재 샘플과 현재 구현 기준에서, 온디바이스 OCR은 **병원 영수증 자동 보험금 계산 입력 생성 용도로 활용 불가능**하다고 결론 내리는 것이 타당하다.

근거:

1. 네 방식 모두 `verified_detail_row_count = 0`이다.
2. 네 방식 모두 `claim_items_ready_count = 0`이다.
3. A/D는 문서 분류와 row 후보 생성은 가능하지만, 계산에 필요한 row 단위 금액 정합성을 통과하지 못했다.
4. B/C는 현재 샘플에서 문서 분류와 row 후보 생성 단계부터 실패했다.
5. 실패 원인은 단순 후처리 문제가 아니라 작은 숫자 열, 우측 금액 열, row/column shift, cell text assignment, 금액 자릿수 오류가 결합된 구조적 문제다.
6. 이 상태에서 값을 보정해 자동 계산에 넣으면 source grounding과 하드코딩 금지 원칙을 위반할 위험이 크다.
7. 병원 영수증 OCR은 지속 실행 로직이므로, 약관/실무가이드 OCR처럼 개발자가 수동 보정하는 예외 경로를 정상 운영 경로로 삼을 수 없다.

따라서 온디바이스 OCR은 현재 프로젝트에서 다음 용도로만 남기는 것이 안전하다.

- 샘플 분석과 연구용 기준선
- 수동 검토 화면의 보조 evidence 생성
- 향후 외부 OCR/API 또는 더 강한 전용 문서 인식 엔진과 비교하기 위한 baseline

자동 보험금 계산의 기본 경로로는 채택하지 않는다.

## 11. Ponytail Review

불필요한 확장 제안, 장기 로드맵, 구현 세부 반복 설명을 제외하고 결과/근거 중심으로 정리했다.

```text
Lean already. Ship.
```
