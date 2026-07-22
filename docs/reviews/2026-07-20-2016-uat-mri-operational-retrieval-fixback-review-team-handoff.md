# UAT MRI 운영 검색 fixback — Review Team 인계

## 1. 검토 대상

- Developer workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- Base: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`
- Candidate: `53f658344dbb79d248a532b8109194b28a2f125b`
- 구현 보고서: `docs/287_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK_REPORT.md`
- 원인 triage: `docs/reviews/2026-07-20-1931-uat-mri-operational-retrieval-fixback.md`

## 2. 권한과 금지 사항

- 읽기 전용 독립 검토만 수행한다.
- protected main 통합, commit, push, 서비스 재기동, 운영 API 쓰기 요청을 금지한다.
- GraphDB/온톨로지 재빌드, 활성 계산 룰·manifest·운영 DB·사용자/대화/감사 데이터 변경을 금지한다.
- 검증 쓰기는 별도 임시 DB·캐시·출력 경로로 격리한다.

## 3. 핵심 검토 질문

1. 제품 코드에 특정 MRI/MRA, 4·5세대, 300/200만원, 특정 문서·lane·chunk ID가 새 조건으로 하드코딩되지 않았는가.
2. `policy_attribute_lookup`이 한도·횟수·기간·공제·비율의 순수 약관 속성 질의에만 작동하고, 보상 가능 여부·청구·지급·계산 판단 질의는 기존 clarification/전용 경로를 유지하는가.
3. 직접 조항 회수는 선택/명시 세대와 허용 문서 범위 안에서만 동작하며 세대 중립 또는 다른 세대 근거를 섞지 않는가.
4. OCR 분절 anchor 순서 매칭과 금액·횟수·기간 단위 검증이 과도한 오탐을 만들지 않는가. 관련 없는 치료명, 짧은 약어, 동일 숫자가 많은 표를 포함한 적대 fixture로 확인한다.
5. 전체 `source_chunk_lookup` 순회가 요청당 성능·메모리·동시성에 수용 가능한가. 실제 규모에서 시간을 계측하고, 캐시/인덱스가 필요하다면 CHANGES_REQUESTED로 판정한다.
6. 직접 hit의 `document`가 compact substring이므로 최종 답변·호버 미리보기·출처 페이지 링크에 띄어쓰기 손실, 원문 왜곡, 잘못된 페이지가 없는가.
7. 4세대 300만원, 5세대 200만원, 비교 양쪽 근거, 보장 판단 clarification이 actual v2 read-only smoke에서 재현되는가.
8. 기존 provenance fail-closed, 내부 요약 비노출, 수술종수/시술 검색, 보험금 계산, 대화 이력·후속질의 연결에 회귀가 없는가.
9. 192줄 제품 변경과 5개 회귀가 최소 범위로 정당화되는가. 중복/도달 불가/불필요 분기가 없는가.

## 4. 필수 검증

- 후보 diff와 구현 보고서의 사실 일치 확인
- focused RED/GREEN 및 적대 fixture
- actual v2 읽기 전용 smoke 4종
- 관련 Graph/API/계산/세션 회귀
- 전체 pytest, 전체 Node, 문법·production build
- active rule/manifest/processing policy 및 safe-baseline Graph SHA 불변 확인
- candidate worktree clean, protected main `ba3426e...` 유지 확인

## 5. 판정 계약

- `PASS`: 위 범위가 독립 재현되고 운영 승격을 막는 결함이 없음
- `CHANGES_REQUESTED`: 파일·행·재현 명령·기대/실제·최소 수정안을 명시
- `BLOCKED`: 동일 외부 차단이 반복되어 더 진행할 수 없을 때만 사용

보고서는 새 immutable 파일로 작성하고 마지막 줄에 다음 marker 중 하나를 남긴다.

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK_PASS_NO_INTEGRATION_NO_PUSH`

`REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK_CHANGES_REQUESTED_NO_INTEGRATION_NO_PUSH`
