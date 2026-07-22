# UAT MRI 세대별 한도 회귀 배포 triage

## 승인 상태

- Developer 최초 후보: `e5156781f878c00db6a6dfc0b0f96521af7c6b9d`
- Review fixback: `da4bd90bd8a2ce9c0a551a8be0c1996c40d26573`
- 부모 기준선: `bae2daca935139953b8342a906ac76acffe59b43`
- Review Team 최종 판정: `PASS`

## 배포 범위

1. 보호 메인이 정확히 `bae2daca935139953b8342a906ac76acffe59b43`이고 tracked/staged 변경이 없는지 확인한다.
2. 운영 중 생길 수 있는 `insurance_chat.db-wal/.db-shm`은 삭제·변경하지 않는다. 예상 밖 tracked 변경이 있으면 중단한다.
3. 승인된 두 커밋만 순서대로 cherry-pick한다.
   - `e5156781f878c00db6a6dfc0b0f96521af7c6b9d`
   - `da4bd90bd8a2ce9c0a551a8be0c1996c40d26573`
4. focused, 관련 상위, 가능한 전체 pytest, JSON 파싱, `git diff --check`를 실행한다.
5. active 계산 룰·rule links·processing policy, Graph DB와 safe baseline hash가 통합 전후 동일한지 확인한다.
6. 현재 r2 safe baseline 경로와 SGLang 모델을 유지한 채 API만 표준 절차로 재기동한다. LLM은 재기동하지 않는다.
7. health, 실제 API PID/환경, 모델 표시, Graph 경로·hash, 반복 Graph 조회 후 r2 WAL/SHM 0건을 확인한다.
8. 보호 메인 상태와 운영 상태를 보고한다. push는 수행하지 않는다.

## 운영 불변 경계

- safe baseline: `/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2`
- Graph SHA-256: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`
- 모델: `sglang:qwen3-next-80b-a3b-instruct-fp8`
- 계산 룰/연결/처리 정책 변경 금지
- ontology/GraphDB/safe baseline 재빌드·쓰기 금지
- 사용자 DB·계정·대화·로그 삭제 또는 초기화 금지
- 출처 링크 기능·보험금 계산·수술종수 경로 변경 금지

## 중단 조건

- 보호 메인 HEAD 불일치 또는 예상 밖 tracked 변경
- cherry-pick 충돌
- focused/상위 회귀 실패
- frozen hash 또는 Graph hash 불일치
- API health 실패 또는 SGLang 모델 변경
- r2 Graph WAL/SHM 생성

## 완료 표식

`DEVELOPER_UAT_MRI_GENERATION_REGRESSION_DEPLOYMENT_COMPLETE_NO_PUSH`
