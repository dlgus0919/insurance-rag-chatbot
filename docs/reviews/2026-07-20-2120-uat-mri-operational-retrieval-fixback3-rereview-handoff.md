# UAT MRI 운영 검색 fixback 3차 재검토 인계

- Workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 이전 후보: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- 재검토 후보: `a988ef14ce988dfb1163b1897ba740e4249c8169`
- 이전 판정: `docs/reviews/2026-07-20-211038-uat-mri-operational-retrieval-fixback2-rereview.md`
- 구현 보고서: `docs/289_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK3_REPORT.md`

읽기 전용 delta 검토만 수행한다. 통합·commit·push·restart·운영 API 쓰기·Graph/ontology/rule/data 변경을 금지한다.

## 필수 판정 항목

1. 지급 여부·지급되는지·보험금은?·보험금 지급 판단은 coverage/claim으로, 순수 지급한도·지급기간 등 명사형은 attribute lookup으로 남는가.
2. public display evidence/API/frontend preview가 항상 180자 이하이며 anchor·선택 수치·단위·원문 공백을 보존하는가.
3. prefix + ellipsis + suffix 방식이 선택 수치를 잃거나 앞뒤 인접 금액·횟수·비율을 대표 근거로 남기지 않는가.
4. API 방어 상한의 prefix/suffix 재절단이 정상 pipeline evidence 및 외부/비정상 metadata에서도 안전한가.
5. actual v2 p.71 300만원, p.286 200만원, 비교, clarification을 독립 재현하는가.
6. focused/관련/전체 Python, 전체 Node, build, diff-check, frozen hash와 protected main 불변을 확인한다.
7. 특정 의료명·세대·금액·문서·chunk 예외나 불필요한 범위 확장이 없는가.

새 immutable 보고서와 다음 marker 중 하나로 종료한다.

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK3_PASS_NO_INTEGRATION_NO_PUSH`

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK3_CHANGES_REQUESTED_NO_INTEGRATION_NO_PUSH`
