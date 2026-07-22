# UAT MRI 운영 검색 fixback 3차 triage

## 기준

- 현재 후보: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- 재검토: `docs/reviews/2026-07-20-211038-uat-mri-operational-retrieval-fixback2-rereview.md`
- 판정: `CHANGES_REQUESTED`

## 최소 수정

1. `지급 여부`, `지급되는지`, `보험금은?`, `보험금 지급 판단` 등 판단형 활용을 coverage/claim 경계로 보낸다.
2. 순수 보상한도·횟수한도·보장기간·공제금액·보상비율 명사형은 attribute lookup으로 유지한다.
3. public `display_evidence`와 API snippet은 기존 UI 계약인 최대 180자를 지킨다.
4. 180자 제한은 단순 후미 절단이 아니라 선택 anchor와 선택된 수치·단위를 중심으로 줄/문장 경계에서 적용한다. p.71의 300만원과 p.286의 200만원 및 원문 공백·페이지는 반드시 남긴다.
5. 인접 공제액·횟수가 대표 근거로 앞서지 않게 한다.

## 검증

- 일반 검사X 활용형/순수 명사형 적대 fixture
- actual v2 4th/5th/comparison/clarification
- API와 frontend source preview: `length <= 180`, 올바른 금액·원문 공백·page
- focused/관련/전체 Python, 전체 Node, build, diff-check, frozen hash

## 금지

특정 MRI/세대/금액/문서/chunk 하드코딩, protected main 통합·restart·push, 운영 API 쓰기, GraphDB/온톨로지/active rule/운영 데이터 변경을 금지한다.

완료 시 현재 후보 위에 최소 단일 commit을 만들고 다음 marker로 종료한다.

`DEVELOPER_UAT_MRI_RETRIEVAL_FIXBACK3_CANDIDATE_COMPLETE_NO_INTEGRATION_NO_PUSH`
