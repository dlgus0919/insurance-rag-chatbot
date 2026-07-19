# Release B 개발자 인수 트리아지

- 작성 시각: 2026-07-19 04:17 KST
- 검토 대상: 대화형 근거 확인 및 안전 기준선 구현
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 개발자 보고서: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719/docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`
- 보호 메인: `/srv/shared/projects/insurance-rag-chatbot` @ `fa8d734d643d18d6983447978de2210819717bc6`
- 보호 메인 원격 기준: `origin/master` @ `b1c0b658a621552bb9b98a035d8883d6fba1dca2`

## 인수 판정 전제

이 문서는 Review Team에 전달할 변경 집합을 고정하는 트리아지이며 PASS 판정이 아니다. Review Team은 제품 코드나 데이터에 쓰지 않고 별도 불변 리뷰 보고서만 작성한다. 리뷰 전후로 보호 메인, 18080 서비스, 운영 DB·계정·대화·로그, active ontology/provenance, GraphDB, 검색 인덱스, rule manifest를 변경해서는 안 된다.

## 개발자 완료 표식

`DEVELOPER_RELEASE_B_IMPLEMENTATION_READY_FOR_REVIEW`

개발자는 stage, commit, push, deploy, candidate apply, practitioner 승인, GraphDB rebuild, reindex를 수행하지 않았다.

## 변경 집합

### 추적 파일 수정

- `frontend/dist/app.min.js`
- `frontend/js/pages/chat.js`
- `playwright.isolated.config.js`
- `src/api/rag_service.py`
- `src/api/routes/chat.py`
- `src/api/schemas/chat.py`
- `src/graph/retriever.py`
- `src/ontology/registry.py`
- `src/rag/pipeline.py`
- `src/rag/source_grounded_answers.py`
- `tests/e2e/chat.spec.js`
- `tests/e2e/isolated-claim-flow.spec.js`
- `tests/test_api_chat_stream.py`
- `tests/test_frontend_assistant_display.mjs`
- `tests/test_source_grounded_answers.py`

### 새 파일

- `docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`
- `docs/review_artifacts/2026-07-19-untrusted-base-correction-bundle.json`
- `scripts/prepare_ontology_safe_baseline.py`
- `src/ontology/safe_baseline.py`
- `src/rag/conversation_context.py`
- `src/rag/evidence_assessment.py`
- `tests/test_conversation_context.py`
- `tests/test_evidence_assessment.py`
- `tests/test_safe_baseline.py`

`git diff --check`는 통과했다. 격리 workspace의 임시 `node_modules` symlink와 18767 E2E 리스너는 제거된 상태다.

## 구현 요약

- 사용자의 후속 진술을 승인 지식이 아닌 세션 assertion으로만 보존한다.
- 확인 항목을 schema v1 상태로 유지하며 해결된 항목과 미해결 항목을 구분한다.
- 승인 provenance가 확인된 decision profile과 직접 조항 chunk가 함께 있을 때만 결론을 만들도록 일반화했다.
- 같은 `turn_id` 재시도는 저장된 결과를 재생하고, 저장 실패 시 완료 이벤트를 보내지 않는다.
- 확인 선택은 첫 응답이 확정한 `session_id`를 보존해 같은 스레드의 두 번째 요청으로 이어진다.
- 공개 SSE의 graph payload에서 내부 chunk 식별자를 제거한다.
- 기존 `apply_policy_clause_decision` 공개 계약과 GraphRetriever의 기존 호출 시그니처를 호환 유지한다.
- lock-exact safe baseline 생성기와 pending correction artifact를 추가하되 미승인 6개 concept를 승인·active apply하지 않는다.

## 개발자 검증 증거

- API 호환 회귀: `27 passed`
- Release B focused/domain 회귀: `214 passed`
- 전체 pytest: `1090 passed, 3 warnings`
- Node 회귀: `18 passed`
- 프런트엔드 build 및 bundle syntax: 통과
- isolated Playwright: `13 passed`
- `git diff --check`: 통과
- raw/base 기본 sync: `quarantined`, exit 1 — 배포 전 의도된 차단
- 임시 safe projection: trusted 49, pending 6, state valid
- 임시 GraphDB: 2,540 nodes, 10,128 edges, integrity error 0

전체 pytest의 선행 `1087 passed, 3 failed` 중 Release B 회귀 1건은 수정했다. 나머지 2건은 `INSURANCE_RAG_ISOLATED_E2E=1`을 일반 전체 테스트에 주입한 경우 기준 커밋에서도 동일 재현되는 환경 충돌로 보고됐으며, 최종 전체 테스트는 해당 E2E 전용 flag 없이 임시 DB·사용자·로그 경로로 통과했다.

## Review Team 필수 검토 항목

1. **000 원칙 및 일반화**
   - 특정 질환, 질문 문구, concept ID, 수술명, 코드에 종속된 production 분기가 없는지 확인한다.
   - `source_grounded_answers.py`의 대규모 삭제와 테스트 축소가 단순 숨김/약화가 아닌 일반 엔진 교체인지 diff와 기준 테스트로 확인한다.

2. **승인 경계**
   - 6개 제외 concept가 모두 `pending`이며 승인 operation, active manifest, Graph seed, retrieval knowledge로 승격되지 않는지 확인한다.
   - 사용자 자유 텍스트와 clarification choice가 ontology/GraphDB/approved profile로 승격되지 않는지 확인한다.
   - decision profile이 실제 active provenance의 applied operation path와 일치할 때만 사용되는지 확인한다.

3. **운영 적용 가능성**
   - safe baseline 생성이 임시 `concepts.safe.json` 검증에 그치지 않고, production active manifest/provenance/GraphDB를 versioned temp 경로에서 검증한 뒤 원자 교체할 수 있는 실제 절차와 계약을 갖는지 확인한다.
   - runtime 기본 경로가 여전히 `data/ontology/concepts.json`인 상황에서 배포 후에도 raw quarantined 상태를 잘못 읽지 않는지 확인한다.
   - hash, provenance, Graph manifest가 동일 projection을 가리키며 실패 시 기존 active/Graph로 rollback 가능한지 확인한다.

4. **대화 상태·영속성**
   - 다중 clarification에서 한 항목 해결 후 다른 미해결 항목이 사라지지 않는지 확인한다.
   - 이미 해결한 질문을 반복하지 않는지, 주제 전환과 동일 스레드 후속 질문이 자연스러운지 확인한다.
   - 같은 turn retry가 중복 메시지를 만들지 않고, persistence 실패 시 완료로 오인하지 않는지 확인한다.
   - 채팅 이력 재열기 후 상태 복원과 계산→일반 질의 연속성이 유지되는지 확인한다.

5. **외부 노출 경계**
   - 브라우저 DOM/SSE/저장 메시지에 내부 chunk ID, provenance operation path, 내부 상태 식별자가 노출되지 않는지 확인한다.
   - UI는 답변 아래 한 개의 확인 질문과 선택지만 표시하고 내부 상태 JSON은 표시하지 않는지 확인한다.

6. **회귀**
   - 수술종수 질문이 HIRA 수가코드 답변으로 오도되지 않는지 확인한다.
   - HIRA 직접 코드 질의, MX122 선택 후 4세대 산정특례 모름 계산, 보험금 계산과 일반 질의 연속성, 채팅 이력, 관리자 Graph 시각화가 유지되는지 확인한다.
   - 로그인 모델 표시는 실제 기동 모델만 반영하는 기존 계약을 깨지 않는지 확인한다.

7. **테스트·산출물 진정성**
   - 전체 1090, focused 214, Node 18, Playwright 13 결과를 격리 workspace에서 재현하거나 로그·명령을 검증한다.
   - E2E가 운영 18080·운영 DB·계정에 쓰지 않았는지 확인한다.
   - 생성된 `frontend/dist/app.min.js`가 현재 source와 일치하고 임시 symlink, 서버, DB, 영상 등 산출물이 git status에 남지 않았는지 확인한다.

## Review Team 출력 계약

- 별도 불변 보고서: `docs/reviews/<timestamp>-release-b-conversational-evidence-resolution-review.md`
- 최종 판정은 `PASS` 또는 `CHANGES_REQUESTED` 중 하나만 사용한다.
- `CHANGES_REQUESTED`이면 파일·행·재현·위험·필수 수정 범위를 구체적으로 적는다.
- `PASS`이면 보호 메인 통합과 운영 데이터 원자 적용 전제, 잔여 위험, 실사용 smoke 항목을 명시한다.
