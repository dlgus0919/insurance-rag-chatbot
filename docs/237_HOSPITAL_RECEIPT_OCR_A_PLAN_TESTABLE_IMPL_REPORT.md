# 237. Hospital Receipt OCR A-Plan Testable Implementation Report

## 1. 구현 요약

`docs/235_HOSPITAL_RECEIPT_CLAIM_REQUIRED_FIELDS.md`, `docs/236_HOSPITAL_RECEIPT_OCR_INTEGRATED_PROCESS_ROADMAP.md` 기준으로 A안 `opencv_paddle`의 테스트 가능 구현을 추가했다.

이번 구현 범위는 보험금 계산 자동 적용이 아니라, 병원 서류 이미지 묶음을 입력받아 다음 산출물을 만드는 것이다.

- OpenCV/Pillow-numpy 기반 grid/cell bbox 후보
- PaddleOCR text box를 cell bbox에 배정한 cell artifact
- 진료비 세부산정내역 row 후보
- 산식/구성 금액 검증 리포트
- 검증 통과 row만 `ClaimItemInput` 후보로 변환하는 adapter
- 실패/불확실 row의 Human Task 분리

LLM/VLM 및 외부 API는 호출하지 않는다.

## 2. 변경 파일

추가:

- `src/hospital_receipt_ocr/`
- `scripts/run_hospital_receipt_ocr.py`
- `tests/test_hospital_receipt_ocr_validation.py`
- `tests/test_hospital_receipt_opencv_grid.py`
- `tests/test_run_hospital_receipt_ocr_cli.py`

runtime 산출물:

- `data/hospital_receipts/manual_20260609/`

위 runtime 경로는 `.gitignore`의 `data/*` 정책으로 Git 추적 대상이 아니다.

## 3. 핵심 설계

- 기존 약관/실무가이드 OCR 배치 스크립트는 직접 runtime path로 재사용하지 않았다.
- `PaddleOcrAdapter`는 monkeypatch 가능한 얇은 boundary로 분리했다.
- `cv2` import 실패 시에도 grid 검출이 완전히 중단되지 않도록 Pillow/numpy projection fallback을 둔다.
- `--redact-sensitive`가 켜진 경우 주민등록번호, 전화번호, 카드번호 패턴을 cell artifact 저장 전에 마스킹한다.
- 세부 row는 검증 통과 전에는 계산 입력으로 승격하지 않는다.
- `ClaimItemInput` 변환은 `claimed_amount=total_amount`, `quantity=1`을 고정한다.
- OCR backend dependency 오류는 프로세스 전체 실패가 아니라 `validation_report.json`과 `human_tasks.jsonl`에 degraded 상태로 기록한다.

## 4. 검증 결과

실행한 테스트:

```bash
pytest tests/test_hospital_receipt_ocr_validation.py \
  tests/test_hospital_receipt_opencv_grid.py \
  tests/test_run_hospital_receipt_ocr_cli.py \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable \
  tests/test_claim_calculation_pipeline.py::test_split_receipt_standard_opinion_excludes_only_nonpay_part \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_unresolved_split_nonpay_is_human_task_excluded_from_totals -q
```

결과:

```text
11 passed
```

문법 검증:

```bash
python -m py_compile src/hospital_receipt_ocr/*.py \
  src/hospital_receipt_ocr/backends/*.py \
  scripts/run_hospital_receipt_ocr.py
```

결과: 통과.

## 5. 실샘플 Smoke

입력:

- `data/hospital_receipts/manual_20260609/input/`
- 12개 이미지

실행:

```bash
python scripts/run_hospital_receipt_ocr.py \
  --input-dir data/hospital_receipts/manual_20260609/input \
  --output-dir data/hospital_receipts/manual_20260609/runs/opencv_paddle \
  --strategy opencv_paddle \
  --redact-sensitive \
  --no-llm \
  --export-claim-items
```

최종 요약:

- 입력 12건, 처리 12건
- `medical_detail_statement` 8건
- `diagnosis_certificate` 1건
- `unknown` 3건
- cell artifact 12건 생성
- 세부내역 row 후보 122건 생성
- 검증 통과 row 0건
- `claim_items_ready` 0건
- validation issue 220건
- human task 123건

## 6. 진단

현재 로컬 Mac 환경에서는 PaddleOCR 의존성 일부가 macOS 코드서명 정책으로 간헐적으로 실패한다.

관측된 오류 유형:

- `scipy`
- `skimage`
- `stringzilla`
- `shapely`
- `paddle`

이 때문에 OCR이 일부 페이지만 동작했고, 일부 페이지는 text cell이 비어 `unknown`으로 남았다.

자동 승격 0건의 직접 원인은 다음이다.

- 작은 `횟수`/`일수` 셀 OCR 누락
- 금액 열 위치 밀림
- 코드 줄바꿈/숫자 OCR 오류
- `금액 * 횟수 * 일수 == 총액` 검증 실패 또는 검증 불완전
- amount component 합계 불일치

자동 계산 입력 승격을 막은 것은 정상 guardrail 동작이다.

## 7. 남은 작업

- DGX `.venv`에서 PaddleOCR 의존성 오류 없이 같은 smoke를 재실행해야 한다.
- row/column alignment를 개선해야 한다.
- `횟수`/`일수`처럼 작은 숫자 셀은 cell crop OCR 또는 숫자 전용 OCR pass를 별도로 두는 것이 필요하다.
- 영수증/수술확인서 문서 유형 분류는 제목 외 보조 패턴을 더 추가해야 한다.
- 검증 통과 row가 생긴 뒤에만 계산 파이프라인 smoke를 수행한다.
