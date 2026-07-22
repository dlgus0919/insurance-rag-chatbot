# UAT MRI 운영 검색 fixback 2차 triage

## 판정 근거

- Review report: `docs/reviews/2026-07-20-203010-uat-mri-operational-retrieval-fixback-review.md`
- Review verdict: `CHANGES_REQUESTED`
- 대상 candidate: `53f658344dbb79d248a532b8109194b28a2f125b`

## 허용 범위

동일 격리 workspace에서 다음 두 결함의 최소 수정과 회귀 테스트·보고서 갱신만 허용한다.

1. 순수 약관 속성 조회와 청구·지급·계산·보험금 판단 의도를 일반 규칙으로 분리한다.
2. compact text는 매칭에만 쓰고, API/source hover에는 선택된 anchor와 올바른 단위를 포함하는 원문 공백 보존 근거 창을 전달한다.

## 구현 계약

- `검사X` 같은 일반 fixture로 RED/GREEN을 고정한다.
- 순수 한도·횟수·기간·공제·비율 명사형은 `policy_attribute_lookup`을 유지한다.
- `계산해줘`, `청구하면`, `지급받을 수 있나요`, `보험금` 판단 표현은 coverage/claim/calculation 경계를 유지한다.
- display evidence는 anchor와 선택된 금액·횟수·기간 단위를 모두 포함하고 원문 whitespace를 보존한다.
- 대표 snippet이 인접 행의 다른 수치만 보여 주어서는 안 된다.
- 특정 MRI/MRA, 4·5세대, 300/200만원, 문서·lane·chunk ID 예외를 금지한다.

## 검증 계약

- generic intent focused RED/GREEN
- actual v2 read-only: 4세대 300만원, 5세대 200만원, 비교 양쪽, 보장 판단 clarification
- API payload 및 frontend source preview 회귀
- 관련·전체 pytest, 전체 Node, 문법·production build, diff-check
- frozen rule/manifest/processing policy/Graph SHA 불변

## 금지 사항

protected main 통합·재기동·push, 운영 API 쓰기, GraphDB/온톨로지/active rule/운영 DB·사용자 데이터 변경을 금지한다.

완료 시 기존 후보 위에 최소 단일 fixback commit을 만들고 다음 marker로 종료한다.

`DEVELOPER_UAT_MRI_RETRIEVAL_FIXBACK2_CANDIDATE_COMPLETE_NO_INTEGRATION_NO_PUSH`
