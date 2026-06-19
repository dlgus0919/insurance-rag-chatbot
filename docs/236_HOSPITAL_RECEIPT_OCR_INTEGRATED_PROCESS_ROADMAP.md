# 236. Hospital Receipt OCR Integrated Process Roadmap

## 1. 목적

`docs/235_HOSPITAL_RECEIPT_CLAIM_REQUIRED_FIELDS.md`에서 정의한 병원 영수증/세부산정내역/진단서/수술확인서 필드 계약을 실제 OCR 실행기로 구현하기 위한 로드맵을 정의한다.

이번 로드맵의 목표는 A안~D안을 선택 실행할 수 있는 **통합 영수증 OCR 프로세스**를 만드는 것이다. 실행기는 여러 OCR/table extraction backend를 비교할 수 있어야 하지만, 출력 스키마와 검증/승격 기준은 하나로 고정한다.

## 2. 기본 원칙

기준 원칙:

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`의 source grounding과 하드코딩 지식 금지 원칙을 따른다.
- 병원 원본 문서는 민감정보를 포함할 수 있으므로 Git에 커밋하지 않는다.
- LLM/VLM은 보조 판독 또는 검수 제안에만 사용한다.
- 계산 입력은 원본 source cell, bbox, row id, 검증 상태가 있는 값만 승격한다.
- 병원 영수증 요약표만으로 세부 line item을 만들지 않는다.
- `ClaimItemInput.claimed_amount`에 세부내역 총액을 넣으면 `quantity=1`로 변환한다.
- 코드/금액/급여구분이 불확실하면 자동 계산 대신 Human Task로 보낸다.

실행 성격 구분:

- 기존 약관/실무가이드 OCR 추출은 정확한 DB화를 위해 수행한 1회성 또는 비지속적 배치 로직이다.
- 병원 영수증 OCR 실행기는 사용자가 신규 청구 서류를 넣을 때 반복 호출될 수 있는 지속 실행 로직이다.
- 따라서 기존 OCR 배치 스크립트의 편의적 전처리, 수동 보정 전제, 느슨한 실패 처리, 실험성 dependency 사용 방식을 그대로 가져오지 않는다.
- 기존 코드는 참고 가능한 구현 자산일 뿐이며, 병원 영수증 OCR에는 별도 runtime boundary, validation contract, 장애 격리, 민감정보 처리, 재시도/중단 정책을 둔다.
- 지속 실행 로직에서는 "가능하면 추출"보다 "불확실하면 승격하지 않음"을 우선한다.

지속 실행 전용 품질 게이트:

- 입력 검증: 지원 파일 형식, 파일 크기, 페이지 수, 해상도, 손상 파일 여부를 실행 초기에 검사한다.
- 재실행 안정성: 같은 입력과 같은 strategy로 재실행하면 동일한 run id 규칙, schema version, validation 결과를 재현할 수 있어야 한다.
- 멱등성: 같은 청구 문서를 중복 입력해도 계산 후보가 중복 승격되지 않아야 한다.
- 장애 격리: 한 페이지 또는 한 backend 실패가 전체 앱 프로세스를 중단시키지 않고, 해당 문서/페이지를 Human Task로 격리해야 한다.
- 시간/자원 제한: backend별 timeout, memory guard, page count limit, worker concurrency limit를 둔다.
- 민감정보 보호: 원본 이미지, crop preview, OCR raw text, 로그, 오류 메시지에 환자 식별정보가 노출되지 않도록 redaction/masking을 기본값으로 둔다.
- 검증 우선 승격: OCR confidence만으로 계산 입력에 승격하지 않고, 산식 검증과 source cell provenance를 함께 요구한다.
- 감사 가능성: 계산 입력으로 승격된 모든 값은 page, bbox, source text, normalization rule, validation id를 추적할 수 있어야 한다.
- 수동 보정 분리: 개발자가 수동으로 OCR 결과를 보정해 DB화했던 과거 예외를 지속 실행 로직의 정상 경로로 포함하지 않는다.
- 운영 중단 가능성: backend dependency 미설치, 모델 미기동, GPU 부족이 발생하면 명확한 degraded state와 사용자 안내를 반환한다.

망분리/온디바이스 기준:

- 1차 목표는 DGX 내부에서 실행 가능한 로컬 도구 조합이다.
- 외부 API 기반 CLOVA/OpenAI 경로는 기존 프로젝트 이력상 성능 기준선으로만 참고한다.
- 이번 병원 영수증 OCR 실행기 기본값은 외부 API 호출 없음이다.
- Gemma4 31B 등 DGX 로컬 VLM은 선택 backend 또는 검수 보조 backend로만 둔다.

## 3. 통합 실행기의 목표 형태

예상 CLI:

```bash
.venv/bin/python scripts/run_hospital_receipt_ocr.py \
  --input-dir /path/to/receipt_images \
  --output-dir data/hospital_receipts/sample_001 \
  --strategy opencv_paddle \
  --claim-manifest data/hospital_receipts/sample_001/claim_manifest.json \
  --redact-sensitive \
  --no-llm
```

공통 옵션:

| 옵션 | 의미 |
|---|---|
| `--strategy` | `opencv_paddle`, `ppstructure`, `surya`, `tatr_ocr`, `gemma4_assist` 등 실행 backend 선택 |
| `--input-dir` / `--input-file` | 병원 서류 이미지/PDF 입력 |
| `--output-dir` | 중간 산출물 저장 위치 |
| `--doc-type-mode` | `auto`, `detail_statement`, `receipt`, `diagnosis`, `surgery_certificate` |
| `--redact-sensitive` | 민감정보 필드 저장/출력 차단 |
| `--no-llm` | 로컬 VLM 호출 없이 deterministic OCR만 실행 |
| `--llm-backend` | `gemma4_31b` 등 로컬 VLM 보조 선택 |
| `--validate-only` | 기존 OCR 산출물에 검증/승격만 재실행 |
| `--export-claim-items` | `ClaimItemInput` 변환 후보 파일 생성 |
| `--fail-on-unverified` | 검증 실패 row가 있으면 exit code non-zero |

공통 산출물:

```text
output_dir/
  run_summary.json
  documents.jsonl
  page_artifacts/
  cell_artifacts/
  detail_rows.jsonl
  receipt_summary.json
  diagnosis_fields.json
  surgery_fields.json
  validation_report.json
  claim_manifest.json
  claim_items_ready.json
  human_tasks.jsonl
```

## 4. A안~D안 정의

### 4.1 A안: OpenCV Grid + PaddleOCR Cell OCR

전략 이름: `opencv_paddle`

개념:

- OpenCV로 문서 보정, 선 검출, 표 grid/cell 후보를 만든다.
- cell crop 단위로 PaddleOCR 또는 기존 local OCR 엔진을 호출한다.
- 행/열/셀 좌표가 명확하므로 계산용 provenance 확보가 쉽다.

장점:

- 외부 API 없이 DGX 내부 실행 가능성이 높다.
- 행/열 검증과 bbox 추적이 가장 명확하다.
- 보험금 계산에 필요한 숫자/열 위치 검증에 적합하다.

위험:

- 스캔이 휘거나 선이 끊긴 경우 grid detection이 실패할 수 있다.
- 병합 셀과 다단 header를 직접 처리해야 한다.
- 병원 양식 변형이 많으면 template-free grid normalization이 필요하다.

권장 위치:

- 1순위 MVP.
- 세부산정내역서처럼 강한 표 선이 있는 이미지에 우선 적용.

### 4.2 B안: PaddleOCR / PP-Structure 중심

전략 이름: `ppstructure`

개념:

- 기존 `src/parser` 계열의 OCR pipeline은 약관/실무가이드 DB화를 위한 배치 로직으로 본다.
- 병원 영수증 OCR에서는 그 구현 패턴과 유틸리티를 참고하되, 지속 실행 기준에 맞게 별도 backend boundary로 감싼다.
- PP-Structure/PaddleOCR 계열로 layout/table/text block을 추출한다.
- table block 결과를 병원 영수증 전용 row schema로 normalize한다.

장점:

- 프로젝트에 이미 OCR 전처리/추출/manifest 설계 경험이 있다.
- table/text/image block 산출물 구조를 참고해 병원 문서용 schema를 설계하기 쉽다.
- A안보다 범용 레이아웃 대응이 쉽다.

위험:

- 복잡한 병원 표의 병합 셀, 작은 글씨, 줄바꿈 코드 인식이 불안정할 수 있다.
- PP-Structure 결과만 믿으면 row/column shift를 놓칠 수 있다.
- 배치 OCR 코드 경로를 직접 runtime path에 연결하면 민감정보 처리, 장애 격리, 응답 시간 제어가 부족할 수 있다.

권장 위치:

- A안과 병렬 비교.
- A안의 grid 검출 실패 페이지에 fallback.

### 4.3 C안: Surya Table Recognition

전략 이름: `surya`

개념:

- Surya 계열 로컬 OCR/table recognition을 이용해 table row/column/cell 구조를 추출한다.
- 산출 cell 구조를 공통 `detail_rows.jsonl` schema로 변환한다.

장점:

- table recognition, OCR, layout을 한 계열에서 처리할 수 있다.
- 한국어와 표 구조를 동시에 다룰 가능성이 있다.
- 외부 API 없이 실행 가능하다.

위험:

- 운영 라이선스와 모델 weight 사용 조건을 별도 검토해야 한다.
- 현재 프로젝트 내 dependency가 아니므로 설치/고정/오프라인 반입 계획이 필요하다.
- 병원 영수증 표에서 A/B안보다 나은지 실측 전에는 알 수 없다.

권장 위치:

- 2차 비교 실험 후보.
- A/B안의 한계가 명확해진 뒤 도입한다.

### 4.4 D안: TATR Table Structure + OCR

전략 이름: `tatr_ocr`

개념:

- Table Transformer/TATR 계열로 table detection과 structure recognition을 수행한다.
- cell text는 PaddleOCR/docTR/기존 OCR 엔진으로 읽는다.
- 표 구조 모델과 OCR 모델을 분리한다.

장점:

- table structure recognition 전용 모델을 활용할 수 있다.
- OCR과 table structure 실패 원인을 분리해 분석하기 쉽다.

위험:

- 한국 병원 영수증 양식과 PubTables 계열 학습 분포가 다를 수 있다.
- 모델/라이브러리 반입, GPU/CPU 성능, 후처리 비용이 추가된다.
- OCR과 structure bbox alignment가 별도 과제가 된다.

권장 위치:

- 장기 fallback/benchmark 후보.
- A/B/C 결과가 부족할 때 구조 인식 비교용으로 사용한다.

## 5. 공통 파이프라인

모든 전략은 같은 단계를 따른다.

```text
입력 수집
  -> 파일 normalize
  -> 문서 유형 분류
  -> 페이지 전처리
  -> backend별 OCR/table extraction
  -> 병원 문서 schema normalize
  -> line/cell validation
  -> cross-document validation
  -> claim manifest 생성
  -> claim_items_ready 변환
  -> human_tasks 생성
```

### 5.1 입력 수집

지원 입력:

- 이미지: JPG, JPEG, PNG, TIFF
- PDF: 스캔 PDF 또는 이미지 PDF
- 향후: 사용자가 앱의 신규 파일 추가에서 선택한 파일

저장 원칙:

- 원본은 Git에 넣지 않는다.
- local runtime data path에만 둔다.
- 민감정보는 로그/문서/테스트 fixture에 출력하지 않는다.

### 5.2 문서 유형 분류

분류 대상:

- `medical_detail_statement`
- `medical_bill_receipt`
- `diagnosis_certificate`
- `surgery_certificate`
- `unknown`

분류 방법:

1. 제목 키워드 기반 deterministic classifier
2. 레이아웃 특징 기반 보조 classifier
3. 필요 시 로컬 VLM 보조 classifier

`unknown`은 자동 계산 파이프라인에서 제외하고 Human Task로 보낸다.

### 5.3 전처리

공통 전처리:

- EXIF orientation 보정
- grayscale/contrast normalization
- thresholding 후보 생성
- page boundary detection
- perspective correction
- skew correction
- table region crop 후보 생성

전처리 산출물은 `page_artifacts/`에 저장하되, 민감정보가 노출될 수 있는 preview는 Git 제외 대상이다.

### 5.4 OCR/table extraction backend

backend별 output은 다를 수 있으나 normalize 단계에 들어가기 전 다음 정보를 최대한 제공해야 한다.

```json
{
  "page_id": "p001",
  "source_file": "...",
  "document_type": "medical_detail_statement",
  "tables": [
    {
      "table_id": "p001_t001",
      "bbox": [0, 0, 100, 100],
      "cells": [
        {
          "row": 0,
          "col": 0,
          "rowspan": 1,
          "colspan": 1,
          "bbox": [0, 0, 10, 10],
          "text": "코드",
          "confidence": 0.98
        }
      ]
    }
  ],
  "text_blocks": []
}
```

### 5.5 병원 문서 schema normalize

공통 normalize 산출:

- `detail_rows.jsonl`
- `receipt_summary.json`
- `diagnosis_fields.json`
- `surgery_fields.json`

`detail_rows.jsonl`은 `docs/235`의 intermediate row schema를 따른다.

필수 normalize 규칙:

- 코드 셀 줄바꿈은 보존 후 병합 후보를 따로 저장한다.
- 금액은 원문 문자열과 normalized Decimal string을 모두 저장한다.
- `금액`, `횟수`, `일수`, `총액`은 검증 계층에 보존한다.
- `ClaimItemInput` 변환 전에는 `quantity`를 확정하지 않는다.
- 공단부담금은 환자 청구액으로 승격하지 않는다.

### 5.6 line/cell validation

필수 검증:

```text
unit_amount * count * days == total_amount
insured_copay_amount + insurer_paid_amount + full_self_pay_amount + nonpay_amount == total_amount
```

추가 검증:

- 금액 컬럼 numeric parse 가능 여부
- row/column header mapping confidence
- code normalization confidence
- duplicate row detection
- page row count consistency
- cell bbox overlap/ordering

### 5.7 cross-document validation

검증 항목:

- 세부내역 총액 합계 vs 영수증 진료비 총액
- 급여 본인부담 합계 vs 영수증 합계
- 공단부담 합계 vs 영수증 합계
- 전액본인부담 합계 vs 영수증 합계
- 비급여 합계 vs 영수증 합계
- 진단서 진단코드 vs 수술확인서 진단코드
- 진단서 치료 내용 vs 수술확인서 수술명
- 수술일 vs 세부내역 수술/처치 line 일자

검증 실패는 바로 계산 실패가 아니라, line별 `review_required` 또는 `human_task`로 분류한다.

### 5.8 claim manifest와 계산 입력 승격

`claim_manifest.json`은 다음 구조를 갖는다.

```json
{
  "schema_version": "hospital_receipt_claim_manifest.v1",
  "claim_document_id": "sample_001",
  "source_documents": [],
  "case_context_candidates": {},
  "detail_rows": [],
  "receipt_summary": {},
  "diagnosis_fields": {},
  "surgery_fields": {},
  "validations": [],
  "claim_items_ready": [],
  "human_tasks": []
}
```

`claim_items_ready` 변환 규칙:

- 검증 완료된 row만 변환한다.
- `claimed_amount`에는 기본적으로 세부내역 `total_amount`를 넣는다.
- 이 경우 `quantity="1"`을 넣는다.
- `insured_copay_amount`와 `nonpay_amount`도 이미 row 합계 금액이면 `quantity="1"`을 유지한다.
- 원본 `count`, `days`, `unit_amount`는 `extra_info` 또는 source metadata에 보존한다.
- 코드/분류가 불확실한 비급여는 `human_tasks`로 보낸다.

## 6. 평가 기준

### 6.1 필드 추출 지표

| 지표 | 목표 |
|---|---|
| 문서 유형 분류 정확도 | 100% 목표 |
| 세부내역 row recall | 99% 이상 목표 |
| 핵심 금액 exact match | 99% 이상 목표 |
| 코드 완전 일치율 | 95% 이상 목표 |
| row/column shift 검출률 | 100% 목표 |
| 진단코드/수술일 exact match | 99% 이상 목표 |

### 6.2 계산 승격 지표

| 지표 | 목표 |
|---|---|
| 검증 완료 row만 `claim_items_ready`로 승격 | 100% |
| 검증 실패 row가 자동 계산에 포함되지 않음 | 100% |
| 공단부담금이 청구금액에 포함되지 않음 | 100% |
| `quantity` 중복 곱셈 없음 | 100% |
| Human Task 사유가 source evidence와 함께 표시 | 100% |

### 6.3 전략 비교 산출물

전략별 비교 report:

```text
reports/hospital_receipt_ocr/
  sample_001_opencv_paddle_report.md
  sample_001_ppstructure_report.md
  sample_001_surya_report.md
  sample_001_tatr_ocr_report.md
  strategy_comparison.md
```

비교 항목:

- field accuracy
- line validation pass rate
- cross-document validation pass rate
- human_task rate
- runtime
- GPU/CPU memory usage
- dependency/offline readiness
- 민감정보 노출 위험

## 7. 구현 단계

### Phase 0. 테스트 데이터와 expected fixture 정의

목표:

- 샘플 원본 이미지를 runtime data로 둔다.
- Git에는 민감정보 없는 최소 fixture 또는 synthetic fixture만 둔다.
- 실제 샘플에 대한 expected values는 민감정보를 제거한 small JSON으로 관리한다.

작업:

1. `data/hospital_receipts/` runtime path 규칙 정의
2. `tests/fixtures/hospital_receipts/` synthetic sample 추가
3. 샘플 expected totals/diagnosis/surgery/candidate rows 작성
4. 민감정보 redaction helper 작성

검증:

- fixture에 환자명/주민번호/전화번호/카드번호가 없는지 테스트

### Phase 1. 공통 schema와 validator 구현

목표:

- backend와 무관한 공통 데이터 모델을 만든다.
- OCR 없이도 validator와 `ClaimItemInput` adapter를 테스트할 수 있게 한다.

예상 파일:

```text
src/hospital_receipt_ocr/models.py
src/hospital_receipt_ocr/validation.py
src/hospital_receipt_ocr/claim_adapter.py
tests/test_hospital_receipt_ocr_validation.py
tests/test_hospital_receipt_claim_adapter.py
```

검증:

- 산식 검증 pass/fail
- 합계 검증 pass/fail
- `claimed_amount=total_amount`, `quantity=1` 변환
- 공단부담금 제외
- 미분류 비급여 Human Task 분류

### Phase 2. A안 구현: OpenCV Grid + PaddleOCR Cell OCR

목표:

- 강한 표 선이 있는 세부산정내역서에서 row/cell extraction을 구현한다.

예상 파일:

```text
src/hospital_receipt_ocr/preprocess.py
src/hospital_receipt_ocr/backends/opencv_paddle.py
scripts/run_hospital_receipt_ocr.py
tests/test_hospital_receipt_opencv_grid.py
```

검증:

- synthetic table image cell detection
- row/column ordering
- code cell multiline merge
- numeric column parse
- sample 1~2페이지 smoke run

### Phase 3. 영수증 summary extractor

목표:

- `medical_bill_receipt`에서 총액/환자부담/급여/비급여 합계를 추출한다.

작업:

- 고정 table region 후보와 OCR cell extraction
- summary totals normalize
- 세부내역 합계와 cross-check

검증:

- 샘플 영수증의 `10,331,160`, `1,914,950`, `3,100,690`, `75,320`, `5,240,200` 검증
- 항목별 요약표만으로 계산 line을 만들지 않는 테스트

### Phase 4. 진단서/수술확인서 key field extractor

목표:

- 진단명, 질병분류기호, 진단 구분, 입원기간, 수술일, 수술명을 추출한다.

검증:

- checkbox 위치 기반 `임상적 추정`/`최종진단` 구분
- `S8352`, `S8329` 대조
- 수술명과 수술일 대조

### Phase 5. 통합 manifest와 Human Task 생성

목표:

- 공통 산출물을 `claim_manifest.json`, `claim_items_ready.json`, `human_tasks.jsonl`로 만든다.

검증:

- 검증 실패 row는 `claim_items_ready`에 없음
- Human Task는 원본 page/bbox/reason 포함
- `ClaimItemInput` adapter가 현재 계산 파이프라인과 호환

### Phase 6. B안 구현 및 A/B 비교

목표:

- 기존 `src/parser` OCR 패턴을 참고한 `ppstructure` backend를 추가하되, 기존 배치 스크립트를 직접 runtime path로 재사용하지 않는다.
- A안과 row/field accuracy를 비교한다.

검증:

- 동일 input에 대해 A/B report 생성
- strategy별 validation pass rate 비교
- A안 실패 page에 B안 fallback 가능성 평가
- backend timeout, partial failure, 민감정보 redaction, 산출물 schema 안정성 검증

### Phase 7. C/D안 실험 도입

목표:

- Surya/TATR은 바로 production dependency로 넣지 않고 plugin-like backend로 격리한다.
- 설치/라이선스/오프라인 반입 가능성을 검토한 뒤 실험한다.

검증:

- dependency import가 없어도 기본 실행기가 깨지지 않음
- 선택 strategy가 없을 때 친절한 오류
- 모델/weight가 Git에 포함되지 않음

### Phase 8. 계산 파이프라인 연동 smoke

목표:

- `claim_items_ready.json`을 `ClaimItemInput`으로 변환해 `run_claim_calculation()` smoke test를 수행한다.

검증:

- 계산 성공/보류/human_task 상태가 line별로 표시
- 지급예상액이 청구금액을 초과하지 않음
- 공단부담금 제외
- 검증 실패 row 제외
- 결과가 확정 지급액처럼 표현되지 않음

## 8. 테스트 계획

우선 실행 테스트:

```bash
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_claim_adapter.py \
  tests/test_claim_calculation_pipeline.py -q
```

backend별 smoke:

```bash
.venv/bin/python scripts/run_hospital_receipt_ocr.py \
  --input-dir /path/to/sample \
  --output-dir /tmp/hospital_receipt_ocr_a \
  --strategy opencv_paddle \
  --redact-sensitive \
  --no-llm
```

비교 report:

```bash
.venv/bin/python scripts/compare_hospital_receipt_ocr_strategies.py \
  --runs /tmp/hospital_receipt_ocr_a /tmp/hospital_receipt_ocr_b \
  --output reports/hospital_receipt_ocr/strategy_comparison.md
```

## 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| VLM이 그럴듯한 숫자를 생성 | source cell 없는 값 저장 금지, numeric coverage validation |
| row/column shift | cell bbox, header mapping, 산식 검증, 합계 검증 |
| 코드 줄바꿈 누락 | multiline cell 보존, code merge 후보와 사전 대조 |
| 공단부담금 포함 오류 | amount role schema 분리, 공단부담금 계산 입력 승격 금지 |
| `quantity` 중복 곱셈 | adapter test로 `total_amount -> claimed_amount, quantity=1` 고정 |
| 민감정보 노출 | redaction, log masking, raw data Git 제외 |
| 병원 양식 다양성 | strategy fallback, Human Task, template registry는 처리 기준만 보관 |
| 외부 API 의존 | 기본 strategy는 no external API, optional backend 격리 |
| dependency 과증가 | backend별 optional import, install guide 별도 |

## 10. 선택 기준

MVP 채택 기준:

1. A안 `opencv_paddle`을 먼저 구현한다.
2. B안 `ppstructure`를 fallback/비교 backend로 구현한다.
3. C/D안은 A/B 결과를 보고 실험 backend로 추가한다.
4. 기본 production path는 가장 높은 자동 승격률이 아니라, 가장 낮은 오승격률을 기준으로 선택한다.

자동 승격보다 중요한 기준:

- 잘못된 row를 계산에 넣지 않는 것
- 원본 근거와 bbox를 추적할 수 있는 것
- 검증 실패가 명확한 Human Task로 남는 것
- 기존 보험금 계산 로직의 deterministic rule layer를 침해하지 않는 것

## 11. 완료 기준

로드맵 전체의 완료 조건:

- A/B strategy가 동일 CLI에서 선택 실행된다.
- 공통 manifest와 validation report가 생성된다.
- 샘플 세부산정내역/영수증/진단서/수술확인서에서 필수 필드가 추출된다.
- 검증 통과 row만 `claim_items_ready`로 승격된다.
- `claim_items_ready`가 현재 계산 pipeline에 연결된다.
- 실패/불확실 row는 Human Task로 표시된다.
- 민감정보가 로그, Git 산출물, report에 노출되지 않는다.
- DGX 내부 no-external-API 경로로 재현 가능하다.
