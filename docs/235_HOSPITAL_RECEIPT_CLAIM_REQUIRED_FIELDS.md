# 235. Hospital Receipt Claim Required Fields

## 1. 목적

병원 영수증, 진료비 세부산정내역서, 진단서, 수술확인서 OCR 결과를 보험금 계산 로직에 연결하려면 어떤 정보가 필요한지 정의한다.

이 문서는 병원 서류 OCR 구현 명세가 아니라, **계산에 투입 가능한 구조화 데이터 계약**을 정한다. OCR 또는 Vision LLM이 읽은 값은 원본 문서의 page, row, cell, bbox, validation status를 가진 source evidence로 추적되어야 한다.

## 2. 적용 원칙

기준 문서:

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`
- `docs/97_CLAIM_PAYOUT_CALCULATION_PIPELINE_SPEC.md`
- `src/claim_calculation/models.py`
- `src/claim_calculation/pipeline.py`
- `src/claim_calculation/standard_matcher.py`
- `src/claim_calculation/deductible_rules.py`

필수 원칙:

- LLM/VLM은 수치, 지급 판단, 공제율, 한도, 면책 여부를 새로 만들지 않는다.
- 값은 원본 영수증/세부내역서/진단서/수술확인서의 source cell 또는 source text에서 읽는다.
- 계산기는 deterministic rule layer와 rule table을 실행한다.
- OCR confidence가 높더라도 산식·합계·코드 검증에 실패하면 자동 계산 입력으로 승격하지 않는다.
- 계산 결과는 확정 지급 보험금이 아니라 근거 기반 예상 또는 검토 결과로 표시한다.

## 3. 현재 계산 로직의 입력 계약

현재 보험금 계산 API와 내부 모델은 다음 구조를 요구한다.

### 3.1 ClaimCaseContext

| 필드 | 의미 | 원본 서류 후보 | 자동 계산 필요도 |
|---|---|---|---|
| `treatment_date` | 진료일 또는 대표 치료일 | 영수증 진료기간, 세부내역서 일자, 진단서 초진일/입퇴원일 | 높음 |
| `visit_type` | `hospitalization` 또는 `outpatient` | 영수증/세부내역서 병실, 입원기간, 요양기관 종류 | 매우 높음 |
| `coverage_topic` | 실손, 3대비급여, 비급여 등 계산 주제 | 항목명, 비급여 표준모델 매칭, 사용자 선택 | 중간 |
| `diagnosis_code` | 질병분류기호 | 진단서, 수술확인서 | 높음 |
| `diagnosis_name` | 진단명 | 진단서, 수술확인서 | 높음 |
| `accident_type` | 질병/상해/사고 구분 | 진단명, 청구 접수 정보, 사용자 입력 | 높음 |
| `policy_generation` | 4세대/5세대 실손 구분 | 사용자 보유 계약 정보 | 매우 높음 |
| `facility_type` | 의료기관 유형 | 영수증 요양기관 종류, 의료기관 정보 | 중간 |
| `facility_grade` | 의원/병원/종합병원/상급종합병원 | 영수증 요양기관 종류, 사업자/요양기관 정보 | 높음 |
| `situation_note` | 보상 상황 설명 | 사용자 입력, 진단서 치료 소견 | 중간 |

`policy_generation`, 계약 담보, 특약 가입 여부, 기존 지급 이력은 병원 서류만으로 확정되지 않는다. 병원 OCR이 제공할 수 없는 계약 정보는 사용자 입력 또는 계약 DB가 제공해야 한다.

### 3.2 ClaimItemInput

| 필드 | 의미 | 원본 서류 후보 | 자동 계산 필요도 |
|---|---|---|---|
| `line_id` | 계산 라인 고유 ID | OCR row id | 매우 높음 |
| `input_name` | 항목명 | 세부내역서 `명칭`, 영수증 항목명 | 매우 높음 |
| `input_code` | 수가/표준/진료 코드 | 세부내역서 `코드` | 높음 |
| `claimed_amount` | 해당 라인의 총 청구금액 | 세부내역서 `총액`, 영수증 합계 | 매우 높음 |
| `insured_copay_amount` | 급여 본인부담금 | 세부내역서/영수증 급여 본인부담금 | 높음 |
| `nonpay_amount` | 비급여 금액 | 세부내역서/영수증 비급여 | 높음 |
| `quantity` | 계산 API에서 `claimed_amount`에 곱하는 수량 | OCR 검증 완료 후 변환 규칙으로 산정 | 높음 |
| `user_category_hint` | 급여/비급여/3대비급여/처방약 등 | 세부내역서 항목, 비급여 표준모델 매칭, 사용자 확인 | 높음 |
| `extra_info` | 근거, 검증 상태, 보류 사유 | source metadata | 중간 |
| `is_prescription` | 처방약 여부 | 항목명/코드/약제 구분 | 중간 |

현재 파이프라인은 `insured_copay_amount`와 `nonpay_amount`가 있으면 급여 본인부담과 비급여를 분리 계산한다. 영수증 OCR은 가능하면 `claimed_amount` 단일 입력보다 이 분리 입력을 채워야 한다.

중요한 변환 규칙:

- 세부내역서의 `금액`, `횟수`, `일수`는 OCR 검증 계층의 산식 검증에 사용한다.
- `ClaimItemInput.claimed_amount`에 세부내역서 `총액`을 넣는 경우 `quantity`는 `1`로 넣는다.
- `ClaimItemInput.claimed_amount`에 세부내역서 `금액`을 넣는 경우에만 `quantity = 횟수 * 일수`를 넣을 수 있다.
- 급여/비급여 분리 입력에서는 `insured_copay_amount`, `nonpay_amount`도 현재 파이프라인에서 `quantity`가 곱해지므로, 이미 합계 금액을 넣는 경우 `quantity=1`을 유지한다.
- 권장 기본값은 **검증 완료된 total 금액 + `quantity=1`** 이다. 원본의 `횟수`, `일수`는 `extra_info` 또는 중간 manifest에 보존한다.

## 4. 병원 원본 서류별 추출 대상

분석 대상 원본:

- `CamScanner 2026. 6. 9. 15.00_1.jpg` ~ `_9.jpg`: 진료비 세부산정내역서
- `CamScanner 2026. 6. 9. 15.00_10.jpg`: 진단서
- `CamScanner 2026. 6. 9. 15.00_11.jpg`: 진료비 계산서·영수증
- `CamScanner 2026. 6. 9. 15.00_12.jpg`: 수술확인서

민감정보는 저장하지 않는다. 등록번호, 주민등록번호, 환자명, 주소, 전화번호, 카드번호, 승인번호 등은 계산에 직접 필요하지 않으며 source image 내부의 masked/redacted 영역 또는 별도 보안 저장소로 분리한다.

### 4.1 진료비 세부산정내역서

원본에서 확인되는 핵심 구조:

| 원본 컬럼 | 계산 입력 매핑 | 설명 |
|---|---|---|
| 항목 | `user_category_hint`, `extra_info` | 진찰료, 입원료, 투약/조제료, 주사료, 마취료, 처치 및 수술료, 검사료, 영상진단료 등 |
| 일자 | `treatment_date`, line evidence | 라인별 진료일 또는 기간 |
| 코드 | `input_code` | 줄바꿈된 코드는 같은 셀의 줄을 공백 없이 병합해야 함 |
| 명칭 | `input_name` | 표준모델/수가코드 매칭의 표시명 후보 |
| 금액 | unit amount evidence | 단가 |
| 횟수 | intermediate field | 단가 산식 검증에 필요. 총액 입력 시 API `quantity`에 직접 넣지 않음 |
| 일수 | intermediate field | 단가 산식 검증에 필요. 총액 입력 시 API `quantity`에 직접 넣지 않음 |
| 총액 | `claimed_amount` | `금액 * 횟수 * 일수` 검증 대상 |
| 급여 본인부담금 | `insured_copay_amount` | 급여 실손 계산 대상 |
| 급여 공단부담금 | 계산 제외 evidence | 환자 청구 대상 아님. 합계 검증에는 사용 |
| 전액본인부담금 | 별도 amount component | 약관/상품에 따라 처리 필요. 기본 자동 계산은 review 권장 |
| 비급여 | `nonpay_amount` | 비급여/3대비급여/중증/비중증 분류 필요 |

세부내역서 라인에는 최소 다음 값을 저장해야 한다.

```json
{
  "source_type": "medical_detail_statement",
  "source_file": "CamScanner 2026. 6. 9. 15.00_1.jpg",
  "page_label": "1 / 9",
  "row_id": "detail_p001_r0009",
  "bbox": null,
  "item_group": "투약 및 조제료",
  "service_date": "2026-03-24/2026-03-27",
  "raw_code": "J2000",
  "normalized_code": "J2000",
  "raw_name": "조제복약지도료(1일당)",
  "unit_amount": "2000",
  "count": "1",
  "days": "3",
  "total_amount": "6000",
  "insured_copay_amount": "1200",
  "insurer_paid_amount": "4800",
  "full_self_pay_amount": "0",
  "nonpay_amount": "0",
  "validation_status": "verified|review_required|rejected",
  "validation_reasons": []
}
```

주의: 위 예시는 구조 설명용이다. 실제 값은 OCR 결과가 아니라 source cell에서 검증된 값으로만 채워야 한다.

### 4.2 진료비 계산서·영수증

영수증 원본에서 확인되는 계산 관련 핵심 값:

| 원본 필드 | 관찰 값 | 계산상 의미 |
|---|---:|---|
| 진료기간 | `20260324 ~ 20260327` | 입원/진료 기간 후보 |
| 진료과목 | `정형외과3` | 참고 정보 |
| 병실 | `209호` | 입원 정황 |
| 환자구분 | `건강보험` | 급여 적용 정황 |
| 진료비 총액 | `10,331,160` | 세부내역 총액 검증 기준 |
| 환자부담 총액 | `7,230,470` | 환자 부담 범위 검증 기준 |
| 이미 납부한 금액 | `6,195,700` | 결제 잔액 검증 |
| 납부할 금액 | `1,034,770` | 결제 잔액 |
| 카드 결제액 | `1,034,770` | 결제 증빙 |
| 합계 급여 본인부담금 | `1,914,950` | 세부내역 합계 검증 |
| 합계 급여 공단부담금 | `3,100,690` | 세부내역 합계 검증 |
| 합계 전액본인부담금 | `75,320` | 세부내역 합계 검증 |
| 합계 비급여 | `5,240,200` | 세부내역 합계 검증 |

영수증 항목별 표는 세부내역서보다 행 수가 적고 요약 목적이다. 자동 계산 라인의 주 source는 세부내역서가 되어야 하며, 영수증은 다음 용도로 사용한다.

- 진료비 총액/환자부담 총액 검증
- 급여 본인부담/공단부담/전액본인/비급여 합계 검증
- 입원 여부, 건강보험 적용 여부, 요양기관 종류 보조 확인
- 결제 증빙 확인

영수증 항목별 요약표만으로 개별 보험금 계산 라인을 만들면 안 된다. MRI, 초음파, 제증명 등 요약 행은 세부내역서 row와 연결된 경우에만 계산 라인으로 승격한다.

### 4.3 진단서

원본에서 확인되는 계산 관련 핵심 값:

| 원본 필드 | 관찰 값 | 계산상 의미 |
|---|---|---|
| 진단 구분 | 임상적 추정에 체크 | 최종진단 여부 판단에 중요. OCR 오류 위험 높음 |
| 주상병 | 전십자인대의 파열, 우측 | 진단명 |
| 주상병 코드 | S8352 | 질병분류기호 |
| 부상병 | 내측 반달연골의 파열, 우측 | 진단명 |
| 부상병 코드 | S8329 | 질병분류기호 |
| 초진일 | 2026년 03월 23일 | 사고/진료 경과 확인 |
| 진단일 | 미상 | 불확실 필드 |
| 치료 내용 | 전십자인대재건술, 전외측인대재건술, 내측 반월연골판 봉합술 등 | 수술확인서와 대조 |
| 입원·퇴원 연월일 | 20260324-20260327 | 입원 여부와 기간 확인 |
| 발행일 | 2026년 03월 27일 | 문서 발행일 |

진단서는 다음 값을 claim context로 제공한다.

- `diagnosis_code`: `S8352`, `S8329`
- `diagnosis_name`: 주상병/부상병 명칭
- `visit_type`: 입원기간이 있으면 `hospitalization` 후보
- `accident_type`: 상해/질병 여부는 진단명만으로 확정하지 말고 사용자 또는 계약/사고 정보와 대조
- `situation_note`: 치료 내용 요약

진단 구분이 `임상적 추정`인지 `최종진단`인지는 보험금 판단에 영향을 줄 수 있으므로 반드시 원본 checkbox evidence를 별도 필드로 저장한다.

### 4.4 수술확인서

원본에서 확인되는 계산 관련 핵심 값:

| 원본 필드 | 관찰 값 | 계산상 의미 |
|---|---|---|
| 진단명 | 전십자인대 파열, 우측 / 내측 반달연골 파열, 우측 | 진단서와 대조 |
| 질병분류기호 | S8352 / S8329 | 진단서와 대조 |
| 수술일자 | 2026년 03월 25일 | 수술 담보/기간 검증 |
| 수술명 | 전십자인대재건술, 전외측인대재건술, 내측 반월연골판 봉합술 | 수술 담보/수술명 매칭 후보 |
| 발행일 | 2026년 03월 27일 | 문서 발행일 |

수술확인서는 `수술명`, `수술일`, `진단코드`를 제공하지만, 해당 수술이 어떤 담보에서 얼마를 지급하는지는 계약/약관/GraphDB/rule table에서 판단해야 한다.

## 5. 자동 계산에 필요한 최소 필드 세트

자동 계산을 시도하려면 최소한 다음 필드가 검증되어야 한다.

### 5.1 청구 건 단위

| 필드 | 필수 여부 | 없을 때 처리 |
|---|---|---|
| 계약 세대 `policy_generation` | 필수 | 사용자 선택 요청 |
| 입원/통원 `visit_type` | 필수 | 계산 보류 |
| 진료기간 또는 대표 치료일 | 필수 | 계산 보류 또는 사용자 확인 |
| 의료기관 등급 `facility_grade` | 통원 계산에서 중요 | 기본값 사용 금지, 확인 필요 |
| 진단명/진단코드 | 담보/수술/상해 판단에서 중요 | 수술/진단 관련 계산 보류 |
| 건강보험 적용 여부 | 특례 판단에서 중요 | 특례 미적용, 확인 필요 |

### 5.2 라인 단위

| 필드 | 필수 여부 | 없을 때 처리 |
|---|---|---|
| source row id/page/bbox | 필수 | 자동 계산 입력 불가 |
| 항목명 `input_name` | 필수 | 자동 계산 입력 불가 |
| 총액 `claimed_amount` | 필수 | 자동 계산 입력 불가 |
| 급여 본인부담/비급여 분리 | 권장 필수 | 단일 금액 계산은 review_required |
| 코드 `input_code` | 비급여 표준모델 매칭에 중요 | 항목명 fuzzy match만 사용, 모호하면 보류 |
| 횟수/일수 | 산식 검증에 필수 | 총액만 쓰되 산식 미검증 표시. API 변환 시 중복 곱셈 방지 |
| 급여/비급여/3대비급여 category | 필수 | 미분류 비급여는 Human Task |
| 약제/처방약 여부 | 처방약 계산에 중요 | 항목명/코드 보조 판단, 불확실 시 review |

## 6. 검증 규칙

### 6.1 라인 산식 검증

각 세부내역 row는 다음을 검증한다.

```text
unit_amount * count * days == total_amount
insured_copay_amount + insurer_paid_amount + full_self_pay_amount + nonpay_amount == total_amount
```

오차 허용은 반올림/원 단위 보정을 고려해 1원 또는 명시된 정산조정액 범위로 제한한다.

### 6.2 합계 검증

세부내역서 전체 합계는 영수증의 다음 값과 일치해야 한다.

```text
sum(total_amount) == 영수증 진료비총액
sum(insured_copay_amount) == 영수증 급여 본인부담금 합계
sum(insurer_paid_amount) == 영수증 급여 공단부담금 합계
sum(full_self_pay_amount) == 영수증 전액본인부담금 합계
sum(nonpay_amount) == 영수증 비급여 합계
```

원본 샘플에서는 정산조정액이 존재하므로 조정 전/후 금액을 분리 저장해야 한다.

### 6.3 코드 검증

세부내역서 코드는 다음 단계를 거친다.

1. 셀 내부 줄바꿈을 보존한다.
2. 같은 코드 셀의 줄을 공백 없이 병합한다.
3. 숫자/영문 코드 형식을 normalize한다.
4. 비급여 표준모델 또는 수가/약제/치료재료 코드 사전과 대조한다.
5. 코드가 불일치하면 항목명만으로 지급 판단하지 않는다.

### 6.4 문서 간 대조

| 대조 대상 | 검증 |
|---|---|
| 진단서 vs 수술확인서 | 진단명, 질병분류기호 일치 여부 |
| 진단서 vs 수술확인서 | 수술명/치료 내용 일치 여부 |
| 세부내역서 vs 영수증 | 진료기간, 병실, 건강보험 여부, 합계 금액 |
| 세부내역서 vs 진단/수술 문서 | 수술일과 수술·치료 line의 일자 일치 여부 |

## 7. 계산 입력 승격 기준

| 상태 | 조건 | 계산 처리 |
|---|---|---|
| `verified` | source cell 존재, 산식 통과, 합계 통과, 코드 또는 항목 매칭 통과 | 자동 계산 입력 가능 |
| `partial_verified` | 금액은 검증됐지만 코드/분류가 불확실 | 급여 본인부담 등 안전한 일부만 계산, 나머지 Human Task |
| `review_required` | 산식/합계/코드/분류 중 하나라도 불확실 | 자동 계산 보류 또는 부분 계산 |
| `rejected` | 행 이동, 숫자 자리수 오류, source 불명확 | 계산 입력 금지 |

## 8. 현재 샘플에서 확인되는 계산 가능/보류 예시

### 8.1 계산 입력 후보

- 입원 기간: `20260324~20260327`
- 건강보험 적용: `건강보험`
- 진단코드: `S8352`, `S8329`
- 수술일: `2026-03-25`
- 수술명: 전십자인대재건술, 전외측인대재건술, 내측 반월연골판 봉합술
- 영수증 합계: 진료비 총액 `10,331,160`, 비급여 합계 `5,240,200`

이 값들은 문서 간 대조에 유용하지만, 단독으로 지급액을 산출하지 않는다.

### 8.2 자동 계산 보류가 필요한 예시

- 영수증 요약표의 MRI/초음파/제증명 금액은 행명이 밀리면 세부내역 row 연결 전까지 계산 라인으로 쓰지 않는다.
- 진단서의 진단 구분 checkbox는 OCR에서 `임상적 추정`과 `최종진단`을 혼동할 수 있으므로 원본 bbox 확인 전까지 확정하지 않는다.
- 세부내역서 코드가 두 줄로 분리된 항목은 병합 검증 전까지 `input_code`로 쓰지 않는다.
- 비급여 금액이 있으나 표준모델 매칭 또는 담보 분류가 불확실하면 `미분류 비급여 Human Task`로 둔다.

## 9. 권장 구조화 스키마

병원 OCR 산출물은 계산 API에 바로 넣지 말고 다음 중간 manifest를 먼저 만든다.

```json
{
  "claim_document_id": "hospital_receipt_sample_20260327",
  "documents": [
    {
      "source_file": "CamScanner 2026. 6. 9. 15.00_11.jpg",
      "document_type": "medical_bill_receipt",
      "page_label": "receipt",
      "extracted_fields": {},
      "validation_status": "review_required"
    }
  ],
  "case_context_candidates": {},
  "line_items": [],
  "summary_totals": {},
  "cross_document_checks": [],
  "claim_items_ready": []
}
```

`claim_items_ready`에 들어간 항목만 `ClaimItemInput`으로 변환한다.

## 10. 구현 시 금지 사항

- 영수증 항목명 문자열만 보고 공제율이나 지급률을 적용하지 않는다.
- VLM이 생성한 금액을 source cell 없이 저장하지 않는다.
- 영수증 요약표 금액만으로 세부 line item을 생성하지 않는다.
- 공단부담금을 환자 청구금액으로 포함하지 않는다.
- 등록번호, 주민번호, 환자명, 주소, 전화번호, 카드번호를 일반 로그나 Git 산출물에 저장하지 않는다.
- 병원 OCR 품질 문제를 LLM 추론으로 메우지 않는다.

## 11. 다음 개발 단위

1. 병원 서류 document type classifier
2. 진료비 세부산정내역서 row/cell extractor
3. 영수증 summary total extractor
4. 진단서/수술확인서 key field extractor
5. line 산식 검증기
6. 영수증 합계 교차 검증기
7. 코드 normalize 및 표준모델/수가코드 매칭기
8. `claim_items_ready` -> `ClaimItemInput` 변환기
9. Human Task UI: 원본 crop, OCR 값, 검증 실패 사유 표시
