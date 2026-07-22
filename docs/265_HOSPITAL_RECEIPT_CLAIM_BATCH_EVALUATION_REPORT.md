# Hospital Receipt Claim Batch Evaluation Report

## Summary

- 실행 기준 저장소: DGX `/srv/shared/projects/insurance-rag-chatbot`
- 앱 버전: `v1.0.22`
- 기본 LLM 서버: `sglang:qwen3-next-80b-a3b-instruct-fp8`
- 입력 파일: `data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json`
- 입력 항목 수: 155개
- 실행 결과 디렉터리: `reports/claim_batch/manual_20260609/20260707T163902_v1.0.22/`

이번 실행은 OCR 성능 평가가 아니라, 수동 검수된 병원 영수증 세부내역 입력 155개를 현재 보험금 계산 로직에 통과시켜 실무자 채점용 결과 파일을 만드는 테스트다.

## Runtime Check

기본 모델 기동 명령:

```bash
/srv/ai-ops/bin/insurance-rag-up --provider sglang --model qwen3-next-80b-a3b-instruct-fp8 --skip-prepare
```

확인 결과:

- SGLang `/v1/models`: `qwen3-next-80b-a3b-instruct-fp8`
- 앱 헬스: `http://127.0.0.1:18080/api/health` 정상
- 앱 모델 목록: `sglang:qwen3-next-80b-a3b-instruct-fp8`가 일반 질의 답변 주력 모델로 노출됨

앱 프로세스는 이미 떠 있어 재기동하지 않았고, LLM 서버만 기본 모델로 전환 확인했다.

## Output Files

생성된 파일:

- `input_payload.json`: 계산 엔진에 넘긴 정규화 입력
- `claim_response.json`: 전체 `CalculationResult`
- `line_results.csv`: 항목별 계산 결과 155행
- `practitioner_scoring.xlsx`: 실무자 채점용 엑셀
- `summary.json`: 실행 요약
- `README.md`: 결과 디렉터리 설명

`reports/`는 저장소에서 무시되는 runtime 산출물이다. 실무자 공유가 필요하면 위 결과 디렉터리만 별도 전달한다.

## Calculation Result

요약:

- 총 입력 항목: 155개
- 라인 결과: 155개
- 자동 계산 준비 표시 항목: 153개
- 예상 지급금액: 2,722,230원
- 공제/제외 합계: 2,102,258원
- 추가 검토 표시 라인: 38개
- 자동 계산 제외 라인: 13개

상태 분포:

| 상태 | 건수 |
| --- | ---: |
| calculated | 142 |
| human_task | 13 |

분류 분포:

| 분류 | 건수 |
| --- | ---: |
| 급여 | 120 |
| 비급여 | 15 |
| 미분류 비급여 | 13 |
| 3대비급여 | 7 |

## Practitioner Scoring Guide

실무자는 `practitioner_scoring.xlsx`에서 다음 컬럼을 채점하면 된다.

- `practitioner_grade`: 예: `pass`, `partial`, `fail`, `review`
- `practitioner_comment`: 판단 사유
- `corrected_payable_amount`: 정정 지급금액이 있을 때만 입력

특히 `requires_review=true` 또는 `calculation_status=human_task`인 항목은 우선 검토 대상이다.

## Validation

실행한 검증:

```bash
.venv/bin/python -m pytest tests/test_eval_hospital_receipt_claim_batch.py -q
.venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py tests/test_api_claim_calculation.py -q
.venv/bin/python scripts/eval_hospital_receipt_claim_batch.py
```

결과:

- 신규 배치 러너 테스트: 4 passed
- 기존 보험금 계산/API 회귀 테스트: 47 passed, 1 warning
- 배치 계산 실행: 성공
- CSV 행 수: 155
- XLSX 행 수: 헤더 포함 156행

## Notes

- 계산은 LLM이 아니라 기존 결정론적 보험금 계산 로직으로 수행했다.
- LLM 서버는 현재 앱 버전의 기본 런타임 준비 상태를 확인하기 위해 기동했다.
- 이번 결과는 실무자 채점 전 자동 계산 산출물이며, 정답 판정 결과가 아니다.
- `human_task` 13개와 `requires_review=true` 38개는 실무자 확인 후 룰/온톨로지/표준코드 연결 개선 후보로 사용할 수 있다.
