# 219. Ontology Hold Reason Feedback Report

## Summary

온톨로지 후보 승인 UI의 `보류` 결정을 구조화했다. 실무자는 보류 시 원문 근거 문제, 승인 대상 표현 문제, target concept 재배정 필요, 문장 조각, 범위 과다, 소유권 충돌, 추가 근거 필요, 지급/면책/계산 위험, 기타 중 하나 이상을 선택할 수 있다.

## Implementation

- `src/ontology/hold_feedback.py`
  - 보류 사유 코드, 표시 문구, 설명, alias 차단 대상 코드를 정의했다.
  - 이전 보류 후보에서 alias blocklist와 review hint를 생성하는 helper를 추가했다.
- `src/ontology/review_store.py`
  - `hold` 결정 시 `properties.review_feedback`와 `review_log.jsonl`에 `hold_reason_codes`를 저장한다.
- `scripts/ontology_review_local_ui.py`
  - 실무자 승인 화면에 보류 사유 체크박스를 추가했다.
- `scripts/ontology_review.py`
  - CLI 결정 명령에 `--hold-reason-code` 반복 옵션을 추가했다.
- `src/ontology/candidate_extractor.py`
  - 기존 review candidates를 읽어 다음 후보 추출에 반영한다.
  - alias 자체가 문제인 보류 사유는 동일 concept의 동일 alias 재생성을 차단한다.
  - 근거/대상 concept 확인이 필요한 보류 사유는 다음 후보 metadata의 `extraction.prior_hold_feedback`에 남긴다.
- `src/ontology/candidate_display.py`
  - 보류 사유 분류 기준과 이전 보류 피드백을 실무자 검토 화면에 표시한다.

## Validation

```bash
python -m pytest tests/test_ontology_review_store.py tests/test_ontology_candidate_display.py tests/test_ontology_candidate_extractor.py -q
```

Result: `15 passed`.

## Notes

이 변경은 보류 후보를 자동으로 운영 manifest에 병합하지 않는다. 보류 사유는 다음 후보 추출과 다음 실무자 검토 품질을 개선하는 feedback loop로 사용된다. 운영 반영은 기존과 동일하게 승인된 후보에 대해서만 별도 `--apply` 및 GraphDB rebuild 단계에서 수행한다.
