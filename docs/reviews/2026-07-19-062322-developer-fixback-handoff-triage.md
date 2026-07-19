# Release B fixback 재검토 인계

- 작성 시각: 2026-07-19 06:23 KST
- 검토 대상: DGX 격리 작업공간의 미커밋 Release B + fixback 전체 변경
- DGX 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 보호 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- 보호 저장소 HEAD: `fa8d734d643d18d6983447978de2210819717bc6`
- 개발자 완료 표식: `DEVELOPER_RELEASE_B_FIXBACK_READY_FOR_REREVIEW`

## 읽어야 할 자료

1. 이 인계 문서
2. `docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`
3. `docs/277_CONVERSATIONAL_EVIDENCE_RESOLUTION_FIXBACK_REPORT.md`
4. 이전 리뷰: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-19-044050-release-b-conversational-evidence-resolution-review.md`
5. fixback 요구: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-19-0444-developer-fixback-triage.md`

## 개발자 보고 검증 결과

- safe-baseline/CLI 계약: `11 passed`
- focused Python: `104 passed, 1 warning`
- Node 표시 계약: `5 passed`
- isolated Playwright: `13 passed`
- 전체 pytest: `1100 passed, 3 warnings`
- 프런트 build 및 `git diff --check`: 통과
- 보호 저장소 tracked 변경 없음
- 커밋, 푸시, 배포, 재시작, active ontology/GraphDB 변경 없음

위 결과를 신뢰 전제로 삼지 말고 리뷰 팀이 독립적으로 재현한다.

## 반드시 재검토할 이전 지적 4건

1. **공개 응답 경계**
   - SSE, source, session history/replay, export의 모든 공개 사본에서 내부 키가 재귀적으로 제거되는지 확인한다.
   - `chunk_id`, source/evidence chunk IDs, session assertions, conversation state, provenance 및 operation path, 저장 전용 metadata가 노출되지 않아야 한다.
   - 내부 저장/복원/idempotent retry에 필요한 서버 내부 상태는 손상되지 않아야 한다.

2. **operator-gated safe baseline**
   - `prepare`, `verify`, `publish`, `rollback`이 실제 운영자용 CLI로 연결되어 있는지 확인한다.
   - 명시적 runtime root와 정확한 확인 토큰 없이는 publish/rollback이 fail-closed인지 확인한다.
   - versioned candidate의 active manifest, provenance, Graph artifact가 함께 검증되는지 확인한다.
   - 준비 실패 시 현재 세트 불변, 두 번째 교체 실패 시 3종 전체 원복, 성공 publish 후 명시 rollback 복구가 임시 root에서 재현되어야 한다.
   - raw/quarantined base로의 묵시 fallback이 없어야 한다.

3. **다중 확인 상태 보존**
   - 하나의 요청에서 a를 확정한 뒤 b만 남았을 때 a assertion과 기존 request ID가 유지되는지 확인한다.
   - b 확인 후 resolved가 되고, 이미 답한 a/b를 반복 질문하지 않는지 확인한다.
   - history restore와 retry/idempotence에서도 동일해야 한다.

4. **schema v2 end-to-end 렌더 계약**
   - fixture가 아닌 실제 evaluator 결과가 `display.primary_text`를 갖는지 확인한다.
   - evaluator -> API renderability -> public payload -> frontend 구조화 렌더 경로가 동일 계약을 사용하는지 확인한다.
   - 직접 근거, 조건, 추가 질문이 보존되며 내부 식별자는 표시되지 않아야 한다.

## 추가 회귀 점검

- 000 원칙: 탈모 등 특정 사례명에 매몰된 하드코딩이나 키워드 예외가 없는지 확인한다.
- 기존 수술종수/수가코드 라우팅, MX122 계산, 채팅 이력/보험금 계산 연속성, 5세대 문서 선택, 모델 표시, 관리자 Graph 경로에 회귀가 없는지 관련 기존 테스트로 확인한다.
- 기본 `check_ontology_sync.py`의 quarantined 차단은 실패가 아니라 운영 publish 전 정상 차단으로 구분한다. 이를 우회한 코드가 없어야 한다.
- pending correction 6건이 승인/적용되지 않았는지 확인한다.
- 임시 listener, symlink, DB, 계정, Playwright 산출물이 남지 않았는지 확인한다.

## 리뷰 경계

- 코드를 수정하지 않는다.
- stage, commit, push, merge, deploy, restart를 하지 않는다.
- active ontology/provenance/GraphDB, 검색 인덱스, 운영 DB, 계정, 대화, 로그를 변경하지 않는다.
- 보호 `18080`에는 GET/HEAD 외 쓰기 요청을 보내지 않는다.
- 동적 쓰기 검증은 격리 loopback 및 임시 root에서만 수행한다.
- 리뷰 산출물만 로컬 `docs/reviews/`에 새 파일로 작성한다.

## 최종 판정

- 문제가 없으면 `REVIEW_RELEASE_B_FIXBACK_PASS`
- 문제가 있으면 `REVIEW_RELEASE_B_FIXBACK_CHANGES_REQUESTED`

판정에는 재현 명령, 실제 결과, 남은 운영 위험, 보호 상태를 포함한다.
