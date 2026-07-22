# UAT MRI 세대별 한도 회귀 Review Team handoff

## 검토 목적

Chrome 실사용 UAT에서 확인된 4세대 MRI/MRA 연간 한도 누락 및 최종 말풍선 내부 경로 문구 노출을 수정한 격리 후보를 독립 검토한다. 특정 테스트 문장에 매몰된 예외 처리가 아닌 일반 질의 계약 수준의 수정인지 확인한다.

## 후보

- 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-generation-regression-20260720`
- 브랜치: `codex/uat-mri-generation-regression-20260720`
- 후보 커밋: `e5156781f878c00db6a6dfc0b0f96521af7c6b9d`
- 부모: `bae2daca935139953b8342a906ac76acffe59b43`
- Developer 완료 표식: `DEVELOPER_UAT_MRI_GENERATION_REGRESSION_CANDIDATE_COMPLETE_NO_INTEGRATION_NO_PUSH`

## 변경 파일

- `config/clause_detail_lookup_policy.json`
- `src/rag/pipeline.py`
- `src/api/rag_service.py`
- `tests/test_pipeline.py`
- `tests/test_api_rag_service_payload.py`
- `docs/284_UAT_MRI_GENERATION_REGRESSION_FIX_REPORT.md`

## 독립 검토 항목

1. 제품 코드에 MRI, 4·5세대, 300만원·200만원 또는 UAT 질문 문자열 하드코딩이 없는지 확인한다.
2. `세대 + 보장 항목 + 한도·횟수·기간 속성 질의`를 원문 수치 근거로 답하는 일반 계약이 과도하게 넓거나 모호한 질문까지 잘못 확정하지 않는지 확인한다.
3. 보상 가능성 질의와 직접 한도 조회가 구별되어 기존 확인 질문 흐름이 유지되는지 확인한다.
4. 내부 snake-case 경로 표식 및 단독 구분선 제거가 정상 사용자 텍스트나 구조화 패널을 훼손하지 않는지 확인한다.
5. 4세대 300만원, 5세대 200만원, 두 세대 비교, 5세대 보상 가능성 변형, 최종 말풍선 내부 문구 미노출 회귀를 독립 재현한다.
6. 수술종수·수가코드·보험금 계산·대화 이력·출처 링크 관련 기존 계약에 회귀가 없는지 확인한다.
7. active 계산 룰, rule links, 처리 정책, ontology/GraphDB, safe-baseline artifact가 후보에서 불변인지 확인한다.
8. 후보 worktree가 clean하고 보호 메인에는 후보가 통합되지 않았는지 확인한다.

## Developer 보고 검증값

- 신규 RED: `4 failed`
- 수정 후 신규 회귀: `4 passed`
- 관련 상위 회귀: `156 passed, 1 warning`
- 전체 pytest: `1153 passed, 3 warnings`
- JSON 파싱 및 `git diff --check`: 통과
- 보호 메인: `bae2daca935139953b8342a906ac76acffe59b43`
- 보호 메인의 기존 `insurance_chat.db-wal`, `insurance_chat.db-shm`은 삭제·수정 금지

## 금지 사항

- 보호 메인 통합, 커밋, push
- 운영 API/LLM 재기동
- active 계산 룰 승인 또는 변경
- GraphDB·온톨로지·safe baseline 재빌드 또는 쓰기
- 운영 사용자 DB·계정·대화·로그 변경
- 보호 `18080`에 대한 쓰기성 검증

## 판정 형식

- `PASS`: 통합 후보로 승인 가능
- `CHANGES_REQUESTED`: 파일/행/재현 근거와 최소 수정 요구 제시
- `BLOCKED`: 독립 검증에 필요한 외부 조건과 미확인 범위 명시

완료 표식: `REVIEW_TEAM_UAT_MRI_GENERATION_REGRESSION_REVIEW_COMPLETE`
