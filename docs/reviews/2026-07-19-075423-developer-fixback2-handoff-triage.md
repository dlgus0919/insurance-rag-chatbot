# Release B Fixback 2 독립 재검토 인계

- 인계일: 2026-07-19
- 구현 담당: Developer 스레드 `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- 검토 담당: Review Team 스레드 `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 격리 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 보호 메인: `/srv/shared/projects/insurance-rag-chatbot`
- 보호 메인 HEAD: `fa8d734d643d18d6983447978de2210819717bc6`
- Developer 보고서: `docs/278_CONVERSATIONAL_EVIDENCE_RESOLUTION_FIXBACK2_REPORT.md`
- 구현 완료 표식: `DEVELOPER_RELEASE_B_FIXBACK2_READY_FOR_REREVIEW`

## 보호 경계

- 검토는 읽기 전용으로 수행한다.
- 보호 메인, 운영 active ontology/provenance, GraphDB, 인덱스, 사용자·계정·대화·로그를 수정하지 않는다.
- stage, commit, push, merge, deploy, publish, rollback, 서비스 재시작을 수행하지 않는다.
- 보호된 `18080`에는 GET/HEAD 이외의 요청을 보내지 않는다.
- 쓰기 검증은 임시 DB·임시 계정·임시 루프백 포트·임시 runtime root만 사용하고 종료 후 제거한다.
- raw/base quarantine 6건은 승인·승격·수정하지 않는다.

## 독립 재검토 대상

### P1-1 prepared registry 주입

1. `prepare`가 Graph 생성 호출에 준비된 registry와 strict 모드를 실제 전달하는지 독립 캡처 테스트로 확인한다.
2. Graph 내부 manifest, 외부 manifest, prepared ontology metadata의 hash/state/count/source가 같은 projection을 가리키는지 확인한다.
3. raw/base 기본 registry가 암묵적으로 섞이는 경로가 남아 있지 않은지 확인한다.

### P1-2 GraphDB 읽기 전용 무결성

1. 정상 SQLite Graph를 readonly로 열어 필수 테이블과 내부 `graph_build_manifest`를 확인한다.
2. 깨진 SQLite 바이트, 필수 테이블 누락, 내부·외부 manifest 불일치, ontology hash/state/count 불일치, 최소 node/edge 무결성 실패를 각각 재현한다.
3. 위 실패가 verify와 publish 모두에서 쓰기 없이 fail-closed 되는지 확인한다.
4. publish 실패 시 기존 runtime tree가 바뀌지 않는지 확인한다.

### P1-3 실제 production resolver/RAG 소비

1. 임시 safe runtime root를 publish한 뒤 `get_default_ontology_registry()`와 실제 RAG/Graph 경로가 같은 root를 소비하는지 확인한다.
2. 기대 상태는 trusted concept 49, registry state `valid`, approved profile 0, pending correction 6 유지다.
3. 명시 safe root가 누락·불완전·손상된 경우 raw/base 또는 기존 Graph로 조용히 fallback하지 않고 초기화 단계에서 실패하는지 확인한다.
4. safe root 미설정 시 기존 개발·테스트 동작을 불필요하게 깨뜨리지 않는지 확인한다.
5. publish와 rollback이 complete artifact set과 동일한 계약을 복원하는지 확인한다.

## 필수 통합·회귀 검증

- 실제 raw ontology/base lock의 55→49 trusted projection을 사용한다.
- LLM 서버가 올라온 상태의 자원 여유를 고려해 전체 5,781 청크·527,679 표준코드 재빌드를 반복하지 않는다.
- Graph 제어 계약은 실제 청크 최소 입력과 격리 표준코드 스키마로 `prepare → verify → corrupt reject → publish → production resolver/RAG → rollback`을 독립 재현한다.
- Developer가 보고한 수치를 신뢰하지 말고 Review Team이 직접 재실행한다.
- 최소 검증 묶음:
  - safe baseline/Graph focused
  - 대화 맥락·근거 수렴·수가/수술종수·보험금·세션·관리자 Graph focused
  - 전체 pytest(운영 DB·계정·로그와 격리)
  - Node 회귀, frontend build/syntax
  - 격리 Playwright: 후보 선택, MX122 계산, 동일 스레드 후속 일반 질의, 새 채팅/기록 복원
  - raw quarantine 차단과 임시 safe baseline sync 분리 확인
  - `git diff --check`, 임시 listener/root/symlink/credential 산출물 cleanup

## 검토 결과 계약

- 새로운 불변 Review 보고서를 이 저장소의 `docs/reviews/` 아래 작성한다.
- 결론은 `PASS` 또는 `CHANGES_REQUESTED` 중 하나로 명시한다.
- 발견 사항은 심각도, 재현 명령/증거, 영향, 필요한 수정 범위를 포함한다.
- 전체 데이터 Graph 재빌드가 자원 때문에 생략되면, 그것을 기능 PASS와 분리된 운영 전제 위험으로 명시한다.
- PASS 시 표식: `REVIEW_RELEASE_B_FIXBACK2_PASS`
- 수정 필요 시 표식: `REVIEW_RELEASE_B_FIXBACK2_CHANGES_REQUESTED`
