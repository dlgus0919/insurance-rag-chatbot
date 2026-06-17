# 240. 병원 영수증 OCR B/C Backend 구현 및 검증 보고서

작성일: 2026-06-16  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 범위

`docs/236_HOSPITAL_RECEIPT_OCR_INTEGRATED_PROCESS_ROADMAP.md`와 A안 개선 결과를 기준으로 B안 `ppstructure`, C안 `surya` backend를 개발하고 DGX 실샘플 12장으로 smoke 검증했다.

이번 작업의 목표는 자동 보험금 계산 승격이 아니라, 동일한 `OcrTable/OcrCell` 산출물 계약으로 backend를 바꿔 실행하고 품질을 비교할 수 있는 상태를 만드는 것이다. LLM/VLM 호출은 사용하지 않았다.

## 2. 구현 내용

### 공통 table HTML 변환

- `src/hospital_receipt_ocr/backends/table_html.py` 추가
- PP-Structure/Surya 계열이 반환하는 table HTML을 `OcrTable/OcrCell`로 변환한다.
- 실제 cell bbox가 없을 때는 table bbox 안에서 deterministic synthetic bbox를 생성한다.

### B안: `ppstructure`

- `src/hospital_receipt_ocr/backends/ppstructure.py` 추가
- 초기 구현에서 `PPStructure` 전체 파이프라인이 formula/LaTeX OCR 모델 다운로드를 시도해 중단했다.
- 이후 지속 실행 경로에 맞춰 `TableSystem` 단일 경로로 축소했다.
- 설치된 PaddleOCR의 PP-Structure 계열은 `korean` layout/det를 지원하지 않아 `ch` table system을 사용한다.
- 한글 OCR 품질 보완을 위해 PP-Structure `cell_bbox`를 우선 사용하고, cell text는 기존 Korean `PaddleOcrAdapter` page OCR 결과를 bbox에 할당하도록 보강했다.

### C안: `surya`

- `src/hospital_receipt_ocr/backends/surya.py` 추가
- Surya는 DGX 현 환경에 설치되어 있지 않고, 공식 실행 경로상 VLM/server 성격의 추론을 시작할 수 있으므로 기본값은 no-inference degraded로 둔다.
- `--allow-experimental-surya-inference`를 명시한 경우에만 실험 inference 경로를 열 수 있게 했다.

### Runner/CLI

- `scripts/run_hospital_receipt_ocr.py`
  - `--strategy opencv_paddle|ppstructure|surya`
  - `--allow-experimental-surya-inference`
- `src/hospital_receipt_ocr/runner.py`
  - backend 선택 구조 추가
  - `unknown` 문서 자동 분류 실패도 validation issue로 기록
  - 기존 산출물 파일 계약 유지

## 3. 검증 결과

DGX 단위/회귀 테스트:

```bash
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_opencv_grid.py \
  tests/test_run_hospital_receipt_ocr_cli.py \
  tests/test_hospital_receipt_ocr_backends.py \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_standard_opinion_excludes_only_nonpay_part \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_unresolved_split_nonpay_is_human_task_excluded_from_totals \
  -q
```

결과: `20 passed`

추가 B/C backend 테스트 후:

```bash
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_opencv_grid.py \
  tests/test_run_hospital_receipt_ocr_cli.py \
  tests/test_hospital_receipt_ocr_backends.py \
  -q
```

결과: `18 passed`

Compile 검증:

```bash
.venv/bin/python -m compileall -q src/hospital_receipt_ocr scripts/run_hospital_receipt_ocr.py
```

결과: 통과

## 4. 실샘플 Smoke 비교

입력: `data/hospital_receipts/manual_20260609/input` 12장

| 전략 | 출력 폴더 | 문서 분류 | detail rows | verified rows | validation issues | human tasks | 평가 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| A `opencv_paddle` | `runs/opencv_paddle_dgx_improved3` | detail 9, receipt 1, diagnosis 1, surgery 1 | 135 | 0 | 205 | 135 | 현재 기준 최선. 문서 분류와 row 후보 생성은 가능하나 산식 검증은 대부분 실패 |
| B `ppstructure` | `runs/ppstructure_korean_ocr_dgx` | unknown 12 | 0 | 0 | 12 | 0 | 실행은 가능하나 실샘플 품질 미달 |
| C `surya` | `runs/surya_dgx_diag` | unknown 12 | 0 | 0 | 25 | 1 | 기본값에서는 의도적으로 degraded. inference 미실행 |

## 5. 품질 분석

### A안

A안은 여전히 가장 실용적인 기준선이다. OpenCV grid 검출과 Korean PaddleOCR 조합이 문서 유형 분류와 row 후보 생성에는 성공했다. 다만 `횟수/일수`, 작은 금액, 우측 금액 열 누락 때문에 `단가 * 횟수 * 일수 == 총액`과 금액 구성 합계 검증을 통과한 row가 0건이다.

### B안

B안은 PP-Structure table path를 실행 가능한 상태로 만들었지만, 현재 DGX 설치본의 PP-Structure 계열이 병원 영수증 스캔본의 한글 표 OCR에는 적합하지 않았다.

관측된 근거:

- `PPStructure` 전체 파이프라인은 formula/LaTeX OCR 모델까지 다운로드하려고 했다.
- `TableSystem` 축소 경로는 실행되지만, table bbox/cell bbox가 병원 세부산정내역의 실제 행/열을 안정적으로 재구성하지 못했다.
- PP-Structure `cell_bbox`에 Korean PaddleOCR text를 다시 할당해도 비어 있는 cell이 많고 핵심 문서 분류 키워드가 충분히 복원되지 않았다.

따라서 B안은 현재 상태에서 A안을 대체할 수 없다. 향후에는 PP-Structure를 전체 page에 적용하기보다 A안 grid 후보의 보조 검증 또는 특정 crop 영역의 table sanity check로 제한하는 것이 적절하다.

### C안

C안은 backend 경계와 안전한 degraded 동작을 구현했다. Surya가 설치되어 있지 않고, 기본 정책에서 inference를 허용하지 않기 때문에 table artifact는 생성되지 않았다. 이는 실패라기보다 의도한 안전 동작이다.

Surya를 실제 비교 대상으로 삼으려면 별도 작업에서 다음을 먼저 확정해야 한다.

- Surya 설치와 모델 캐시 위치
- VLM/server 기동 여부와 지속 실행 정책 적합성
- 오프라인/망분리 환경에서 모델 다운로드 없이 재현 가능한 배포 방식

## 6. 결론

현재 병원 영수증 OCR의 실무 기준선은 A안 `opencv_paddle`이다. B안과 C안은 선택 가능한 backend로 개발되었지만, 실샘플 12장 기준으로 자동 보험금 계산 입력으로 승격할 품질은 아니다.

다음 개선은 B/C 확장보다 A안의 row reconstruction 품질 개선에 집중하는 것이 낫다.

우선순위:

1. A안에서 작은 숫자 열(`횟수`, `일수`)과 우측 금액 열을 보강한다.
2. OpenCV grid cell과 OCR text box의 assignment를 다중 후보/row context 기반으로 개선한다.
3. B안은 보조 table sanity checker로 제한한다.
4. C안은 Surya 설치/모델 캐시/서버 기동 정책 검토 후 별도 실험으로 분리한다.

## 7. 참고 자료

- PaddleOCR PP-StructureV3 documentation: https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PP-StructureV3.html
- Surya repository: https://github.com/VikParuchuri/surya
