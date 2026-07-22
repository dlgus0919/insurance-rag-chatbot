# UAT MRI 세대별 근거 정합성 PASS 후보 배포 triage

## 승인된 입력

- 보호 메인 기대 HEAD: `2ea0d81666bd121b9b52d7d40c2deca4f1122d87`
- Review PASS 후보: `51405559a92be7c7bb8daa19a0a5e466a5d0e233`
- Review 결과: 제품 코드 결함 없음, focused `92 passed`, Graph/대화/근거 `100 passed`,
  전체 `1154 passed` + 기존 `/tmp` lock 권한 실패 2건
- 보호 메인 경로: `/srv/shared/projects/insurance-rag-chatbot`
- 운영 safe baseline: `/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2`

## 배포 권한

후보 커밋 하나만 보호 메인에 cherry-pick하고, 운영과 동일한 safe-baseline 환경으로 검증한 뒤
API만 재기동한다. SGLang, GraphDB, ontology/safe baseline, 활성 계산 룰, 사용자 대화·계정
데이터는 변경하지 않는다. push는 하지 않는다.

## 사전 중지 조건

다음 중 하나라도 다르면 즉시 중단하고 보고한다.

- 보호 메인 HEAD가 기대값과 다름
- 후보 커밋의 부모가 `2ea0d816...`가 아님
- 보호 메인 tracked/staged 상태가 clean하지 않음
- 후보 6개 파일 외 충돌 또는 추가 변경 발생
- 계산 룰/처리 정책/r2 Graph SHA-256이 승인 기준과 다름

기존 운영 sidecar `insurance_chat.db-wal`(size 0)과 `insurance_chat.db-shm`은 삭제·수정하지 않는다.

## 적용 및 검증

1. 보호 메인 HEAD/status, API PID, SGLang PID, 모델명, runtime root, Graph/계산 hash를 기록한다.
2. `51405559...` 하나만 cherry-pick한다.
3. 다음 환경 경계를 명시해 검증한다.
   - `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT=/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2`
   - ontology rebuild lock은 테스트 전용 writable 임시 경로를 사용하고 종료 후 제거한다.
   - 채팅 DB는 테스트 전용 임시 SQLite 경로를 사용한다.
4. 핵심 3경계, 관련 회귀, 가능한 전체 pytest를 실행한다. 새 제품 실패가 있으면 재기동하지 않는다.
5. API만 재기동한다. SGLang PID/모델, Graph DB, safe baseline, 계산 hash는 유지한다.
6. health와 runtime metadata를 GET/읽기 전용으로 확인한다. 대화 저장을 유발하는 POST smoke는
   Planner의 Chrome UAT로 대신한다.
7. 보호 메인 tracked/staged 상태와 새 HEAD를 보고한다. push는 하지 않는다.

## 완료 표식

`DEVELOPER_UAT_MRI_RUNTIME_GROUNDING_DEPLOYED_API_ONLY_NO_PUSH`
