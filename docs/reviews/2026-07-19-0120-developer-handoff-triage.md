# Developer handoff triage — Release A safe baseline and Release B conversation continuity

- 작성 시각: 2026-07-19T01:20:04+0900
- 라우팅 대상: Developer (`019eaf4a-6338-7812-bf3b-663df7d83d4f`)
- 작업 저장소: `/Users/june_kim/Projects/insurance-rag-chatbot`
- DGX 보호 checkout: `/srv/shared/projects/insurance-rag-chatbot`
- 검토 완료 Release A 후보: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- 검토 완료 Release A commit: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 상태: Developer 구현 라우팅

## 확인된 현재 상태

1. 원격 `master`는 Release A 후보 `b1c0b658...`까지 승격되었다.
2. 보호 checkout과 18080 서비스는 아직 `fa8d734d...`를 실행 중이므로 Release A 코드는 운영에 반영되지 않았다.
3. Release A 후보에서 실제 dry-run을 재실행한 결과는 `status=quarantined`, `valid=false`, trusted projection 49개, quarantine 6개, 승인 operation 0건이다.
4. quarantine 대상은 `cov.hair_loss`, `cond.age_related_hair_loss`, `cond.disease_related_hair_loss`, `cond.treatment_side_effect_hair_loss`, `cond.work_daily_life_impairment`, `cond.pay_nonpay_status`이다.
5. 사용자는 이 지식을 원문 근거 부족으로 승인하지 않았다. 따라서 이 6개를 승인하거나 active/Graph에 포함하는 해결은 금지한다.
6. Release B 계획은 active/provenance/Graph 무결성이 `valid`이고 quarantine count가 0일 때만 구현을 시작하도록 명시한다.

## 판정

Release A 코드는 독립 리뷰를 통과했으나 운영 safe baseline 산출물은 아직 없다. 현재 raw manifest의 미승인 delta를 그대로 두고 active projection만 만드는 방식은 active audit도 `quarantined`가 되므로 Release B 선행 조건을 충족하지 않는다. 미승인 지식은 검토 후보/포렌식 산출물로 보존하되, 운영이 신뢰하는 base/active 경계에서는 제외하는 일반화된 교정이 필요하다.

## Developer 구현 범위

1. `b1c0b658...`에서 새 격리 `muldae` 작업공간을 사용한다. 검토 완료 Release A 작업공간과 보호 checkout은 수정하지 않는다.
2. 먼저 Release A safe-baseline 교정을 구현한다.
   - 미승인 6개 payload는 pending correction candidate 또는 별도 불변 검토 산출물로 보존한다.
   - practitioner approval, 자동 승인, legacy 승인 추정은 하지 않는다.
   - 운영 base/active/provenance에는 reviewed trusted 49개만 들어가고 audit state가 `valid`, quarantine count가 0이어야 한다.
   - 특정 질환명/개념 ID를 runtime 분기 로직에 하드코딩하지 않는다. 사건별 ID는 데이터 교정 산출물과 테스트 fixture에서만 허용한다.
   - 기존 review log, active snapshot, GraphDB, 사용자 데이터는 삭제·축약하지 않는다.
   - temp/versioned 산출물에서 active/provenance 및 임시 GraphDB strict build/hash 검사를 수행하되 운영 파일은 건드리지 않는다.
3. 위 Release A 조건을 실제 명령으로 통과한 경우에만 `docs/superpowers/plans/2026-07-18-conversational-evidence-resolution.md`의 Release B를 TDD로 구현한다.
   - 사용자의 후속 진술을 session assertion으로 보존하고, 이미 답한 확인 질문을 반복하지 않는다.
   - 사용자 진술을 ontology/Graph/승인 의료지식으로 승격하지 않는다.
   - 승인 decision profile이 없으면 확정 판단을 생성하지 않는다.
   - 테스트 사례 문구나 탈모 전용 예외가 아닌 generic evidence/state transition 계약으로 해결한다.
4. `docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`에 변경, 실패 우선 테스트, 최종 검증, 비변경 범위와 잔여 위험을 기록한다.

## 필수 검증

- Release A audit: exit 0, state `valid`, quarantined concept count 0.
- active/provenance hash 일치 및 임시 GraphDB manifest의 ontology hash/integrity/quarantine metadata 일치.
- Release B focused Python suite와 전체 `pytest -q`.
- Node 관리자/채팅 회귀, `node --check`, frontend build.
- 격리 loopback + 임시 DB/계정/로그를 사용한 Playwright write E2E.
- 두 턴 대화에서 첫 답변의 확인 조건을 사용자가 제공하면 두 번째 답변이 해당 assertion을 반영하고 같은 질문을 반복하지 않는지 확인.
- 수술종수, HIRA 게이트, MX122 후보 선택 후 4세대 계산, 계산/일반질의 동일 스레드 연결, 채팅 이력, 관리자 Graph 회귀.
- LLM invocation 증가 없음, user assertion의 ontology/Graph 저장 0건, final-before-persist 0건, 중복 렌더링 0건.
- `git diff --check` 및 작업공간 임시 산출물 정리.

## 금지 범위

- 보호 checkout 수정, 18080 서비스 재시작/배포, 운영 active/Graph/index/DB 쓰기
- 미승인 6개 승인 또는 active 적용
- 테스트를 위한 skip/xfail/삭제
- stage, commit, push, merge
- 사용자 기존 변경이나 다른 문서 정리/삭제

Release A를 안전하게 `valid`로 만들 수 없으면 Release B 구현을 시작하지 말고 정확한 차단 증거와 함께 `DEVELOPER_BLOCKED_BY_RELEASE_A_INTEGRITY`로 종료한다. 두 단계와 모든 검증을 완료했으면 마지막 줄에 `DEVELOPER_RELEASE_B_IMPLEMENTATION_READY_FOR_REVIEW`를 남긴다.
