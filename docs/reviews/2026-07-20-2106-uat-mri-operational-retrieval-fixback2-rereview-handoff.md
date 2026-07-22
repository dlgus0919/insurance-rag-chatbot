# UAT MRI 운영 검색 fixback 2차 재검토 인계

## 대상

- Workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 원 후보: `53f658344dbb79d248a532b8109194b28a2f125b`
- Fixback 후보: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- 이전 판정: `docs/reviews/2026-07-20-203010-uat-mri-operational-retrieval-fixback-review.md`
- 구현 보고서: `docs/288_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK2_REPORT.md`

## 권한

읽기 전용 delta 재검토만 수행한다. protected main 통합·commit·push·restart, 운영 API 쓰기, GraphDB/온톨로지/active rule/운영 DB 변경을 금지한다.

## 필수 재검토

1. `계산해줘`, `청구하면`, `지급받을 수 있나요`, `보험금 판단`이 coverage/claim 경계를 유지하며, 순수 한도·횟수·기간·공제·비율 조회는 attribute lookup으로 남는지 일반 fixture로 재현한다.
2. `_CLAIM_DECISION_PHRASE_RX`가 불필요하게 넓거나 한국어 활용형을 놓치지 않는지 적대 표현으로 확인한다.
3. 내부 compact evidence와 public `display_evidence`의 분리가 결정적 답변을 깨지 않는지 확인한다.
4. API snippet/hover가 원문 공백과 선택 anchor·올바른 단위를 포함하며, 앞뒤 인접 행의 다른 금액이 대표 근거처럼 남지 않는지 확인한다. 특히 `_raw_display_window()`가 선택 수치 뒤 80자를 더 포함하는 영향도 검토한다.
5. `display_evidence`만 180자 제한을 우회하므로 길이 상한·payload/UI 안전성이 실제 bounded window 계약을 만족하는지 계측한다.
6. actual v2 read-only에서 4세대 p.71 300만원, 5세대 p.286 200만원, 비교 양쪽, 보장 판단 clarification을 재현한다.
7. focused/관련/전체 Python, 전체 Node, 문법·production build, diff-check, frozen hash와 protected main 불변을 확인한다.
8. 특정 의료명·세대·금액·문서·chunk 예외가 제품 코드에 새로 들어가지 않았는지 확인한다.

## 판정

새 immutable 보고서를 작성하고 `PASS` 또는 정확한 재현·영향·최소 수정안을 포함한 `CHANGES_REQUESTED`로 끝낸다.

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK2_PASS_NO_INTEGRATION_NO_PUSH`

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK2_CHANGES_REQUESTED_NO_INTEGRATION_NO_PUSH`
