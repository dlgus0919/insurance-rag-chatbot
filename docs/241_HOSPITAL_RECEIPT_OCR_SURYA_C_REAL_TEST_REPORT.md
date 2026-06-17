# 241. 병원 영수증 OCR C안 Surya 실실행 결과 보고서

작성일: 2026-06-16  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`  
실행 결과 경로: `data/hospital_receipts/manual_20260609/runs/surya_real_12_background`

## 1. 목적

C안 `surya` backend가 DGX에서 실제 12장 병원 서류 세트를 처리할 수 있는지 확인했다. 목표는 자동 보험금 계산 적용이 아니라, source cell/bbox 기반 OCR 산출물과 검증 리포트를 생성하고 자동 승격 가능성을 평가하는 것이다.

외부 API와 LLM 서버는 사용하지 않았다. Surya가 자체 vLLM Docker server를 기동하는 경로만 사용했다.

## 2. 실행 상태

백그라운드 실행은 정상 종료됐다.

```text
exit_code.txt: 0
```

Surya vLLM 컨테이너는 실행 후 자동 정리됐고, 현재 남아 있는 `surya`/`vllm` 컨테이너는 없다.

## 3. 산출물

생성된 주요 파일:

- `run_summary.json`
- `documents.jsonl`
- `cell_artifacts/*.json`
- `detail_rows.jsonl`
- `receipt_summary.json`
- `validation_report.json`
- `claim_manifest.json`
- `claim_items_ready.json`
- `human_tasks.jsonl`

## 4. 결과 요약

`run_summary.json` 기준:

```json
{
  "strategy": "surya",
  "input_count": 12,
  "processed_documents": 12,
  "document_type_counts": {
    "unknown": 12
  },
  "detail_row_count": 0,
  "verified_detail_row_count": 0,
  "claim_items_ready_count": 0,
  "validation_issue_count": 20,
  "human_task_count": 1,
  "redact_sensitive": true,
  "llm_used": false,
  "ocr_degraded": true,
  "ocr_unavailable_reason": "Surya ran but did not return supported table HTML output."
}
```

평가:

- 입력 12장 처리 자체는 완료됐다.
- 문서 유형 분류는 12장 모두 `unknown`이다.
- 세부산정내역 row 추출은 0건이다.
- 검증 완료 row는 0건이다.
- 자동 보험금 계산 입력으로 승격된 `claim_items_ready`는 0건이다.
- `receipt_summary.json`은 빈 객체다.

## 5. Surya table artifact 확인

Surya는 일부 페이지에서만 table artifact를 생성했다.

| artifact | rows | cols | cells | nonempty cells |
| --- | ---: | ---: | ---: | ---: |
| `p001_p001_surya_t001.json` | 9 | 12 | 108 | 81 |
| `p004_p004_surya_t001.json` | 10 | 11 | 110 | 79 |
| `p006_p006_surya_t001.json` | 9 | 13 | 117 | 67 |
| `p007_p007_surya_t001.json` | 11 | 12 | 132 | 89 |
| `p008_p008_surya_t001.json` | 8 | 12 | 96 | 71 |

나머지 7장은 table artifact가 생성되지 않았다.

## 6. 실패 원인

이번 실행은 프로세스 실패가 아니라 품질 실패다.

주요 원인:

1. Surya가 12장 중 5장만 table로 인식했다.
2. 인식된 table도 병원 세부산정내역의 실제 행 단위가 아니라 페이지 전체를 거친 grid로 나눈 결과에 가깝다.
3. 현재 runner는 OCR table text를 만든 뒤 문서 유형을 분류하지만, Surya 결과의 text만으로는 `진료비 세부산정내역`, `진단서`, `수술확인서`, `영수증` 키워드 기준을 넘지 못했다.
4. 문서 유형이 `unknown`이므로 `medical_detail_statement` 전용 row 정규화가 실행되지 않았다.
5. 결과적으로 산식 검증과 `claim_items_ready` 승격까지 도달한 row가 없다.

`validation_report.json` 이슈 분포:

- warning 12건: 문서 유형 자동 분류 실패
- error 7건: Surya backend table 미검출
- error 1건: Surya 결과가 현재 지원하는 table HTML 출력 계약을 충족하지 않음

## 7. 결론

C안 `surya`는 DGX에서 실행은 가능하지만, 현재 병원 영수증 지속 실행 backend로 채택하기에는 부족하다.

현 시점 기준:

- 기본값으로 쓰면 안 된다.
- 자동 보험금 계산 입력으로 바로 연결하면 안 된다.
- 실무 적용 기준선은 여전히 A안 `opencv_paddle`이다.
- C안은 보조 실험 후보로 남기되, 문서 분류 fallback이나 row 후처리를 추가하기 전에 Surya table 구조 품질이 먼저 개선되는지 확인해야 한다.

## 8. 다음 작업 후보

우선순위는 다음이 적절하다.

1. A안 `opencv_paddle` 결과를 기준선으로 유지한다.
2. C안은 현재 결과를 실패 기준선으로 보관한다.
3. Surya를 계속 보려면 5개 artifact의 실제 cell 배열을 사람이 확인해 row 복원이 가능한지 먼저 판단한다.
4. 복원이 불가능하면 C안 후처리 코드를 늘리지 말고 보류한다.

현재 결과만으로는 C안에 추가 wrapper나 복잡한 보정 계층을 붙이는 것은 과잉 구현 위험이 크다.
