# Developer Handoff Triage — Approval Integrity Release A

- 작성 시각: 2026-07-18 16:09 KST
- route: Developer
- project: `/Users/june_kim/Projects/insurance-rag-chatbot`
- protected DGX checkout: `/srv/shared/projects/insurance-rag-chatbot`
- required development location: 최신 `origin/master` 기반 `/srv/shared/workspaces/muldae/insurance-rag-chatbot-<task>` 격리 작업공간
- local planning HEAD: `91ae5514102123b10d398c2fa02726428b77765b`
- local `origin/master` observation: `fa8d734d643d18d6983447978de2210819717bc6`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f` (`idle`, cwd 일치 확인)

## Authoritative documents

1. 설계: `docs/superpowers/specs/2026-07-18-approval-safe-conversational-evidence-resolution-design.md`
2. 이번 구현 범위: `docs/superpowers/plans/2026-07-18-ontology-approval-integrity-containment.md`
3. 후속 릴리스 계획(이번에는 구현 금지): `docs/superpowers/plans/2026-07-18-conversational-evidence-resolution.md`
4. 최상위 원칙: `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`

## Evidence and root cause

- `src/ontology/manifest_merge.py`는 base 전체를 먼저 복사한 뒤 candidate reinforcement를 더하므로, field-level 승인을 증명하지 못하는 base delta도 active manifest로 유입될 수 있다.
- `src/ontology/review_store.py`의 현재 로그에는 base/candidate/evidence hash와 승인 path가 충분히 남지 않고, candidate lifecycle metadata와 runtime payload의 경계도 약하다.
- `src/ontology/registry.py`는 active manifest를 선호하지만 concept별 provenance 무결성 실패를 quarantine하는 공통 검사 계약이 없다.
- 현재 `data/ontology/concepts.json`에는 승인되지 않은 payload가 직접 들어간 이력이 있어, 현재 base 전체를 신뢰 기준으로 자동 승격하면 사용자가 거절한 지식이 다시 운영 경로에 들어갈 수 있다.
- 따라서 특정 질환명이나 테스트 문장을 차단하는 지엽적 수정이 아니라 canonical hash, trusted base lock, semantic field approval patch, provenance sidecar, concept-level quarantine를 공통 계약으로 구현해야 한다.

## Selected scope

이번 handoff에서는 Release A만 수행한다.

- canonical JSON/hash와 trusted base lock
- candidate control metadata와 runtime payload 분리
- semantic JSON path 단위 `ApprovalPatch`
- trusted projection + approved operations 병합
- 실제 expected diff를 만드는 dry-run과 integrity audit
- runtime registry quarantine
- GraphDB seed/hash 검증 연계
- 현재 incident correction은 **pending evidence 기반 dry-run만** 생성
- 실패 우선 회귀 테스트, 전체 회귀, `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md`

Release B의 대화 상태, EvidenceAssessment, SSE 저장 순서, frontend 단일 출력 변경은 Release A 리뷰와 safe baseline 판정 전까지 시작하지 않는다.

## Mandatory stop rules

다음 중 하나라도 발생하면 추정하거나 우회하지 말고 변경을 보존한 채 중단·보고한다.

1. 보호 메인이 dirty이거나 원격 기준이 작업 시작 후 변동됨
2. trusted baseline을 재현할 Git 근거가 없거나 base lock의 source revision을 증명할 수 없음
3. legacy 승인 로그의 승인 범위를 field-level로 증명할 수 없음
4. 승인 path 밖 delta가 expected active diff에 나타남
5. active/provenance/Graph hash가 불일치함
6. 기존 승인 로그·운영 데이터의 삭제 또는 재작성 없이는 구현할 수 없음
7. production 코드에 특정 질환·질문·concept id 분기가 필요해짐
8. 관련 focused 또는 전체 회귀가 실패함

## Explicit exclusions

- `concepts.active.json` 운영 교체 금지
- pending 후보 승인 또는 적용 금지
- GraphDB 운영 재구축·교체 금지
- BM25/Chroma 재인덱싱 금지
- API/LLM/서비스 재기동 금지
- 운영 DB·사용자 계정·대화·로그 변경 금지
- DGX protected main 직접 개발 금지
- `git add`, commit, push, protected main 반영 금지
- Release B 착수 금지
- 기존 review/applied JSONL 축약·정리·삭제 금지

## Required execution discipline

1. 최신 remote와 보호 메인 상태를 읽기 전용으로 기록한다.
2. 최신 `origin/master`에서 새 `muldae` 격리 작업공간을 만든다.
3. 계획의 각 task를 `superpowers:test-driven-development` 방식으로 실패 테스트부터 수행한다.
4. ignored local review JSONL과 운영 산출물은 fixture 또는 임시 경로로 격리한다.
5. correction dry-run은 운영 파일을 쓰지 않고 temp output과 보고서만 만든다.
6. `superpowers:verification-before-completion`으로 focused, full pytest, ontology sync, diff 검사, 비밀값·임시 산출물 점검을 끝낸다.
7. 변경은 격리 작업공간에 unstaged 상태로 남겨 Review Team이 그대로 검사할 수 있게 한다.

## Acceptance gates

- 계획 Task 1~10 체크리스트가 모두 충족됨
- approval path 밖 delta가 active 예상 diff에 없음
- unverified/legacy-unverifiable concept가 runtime과 Graph seed에서 fail-closed 됨
- current incident의 미승인 full payload가 active 예상 diff에 없음
- 기존 procedure grade, HIRA, MX122, claim calculation, session history, admin Graph 계약 회귀가 없음
- 전체 `pytest -q`와 계획의 focused 명령이 통과함
- `git diff --check` 통과
- 운영 active/Graph/index/service/data에 변경 없음
- 보고서에 정확한 파일 목록, 테스트 수치, dry-run artifact/hash, 남은 위험이 기록됨

## Self-review result

계획 1회 재검토 결과 `PASS_WITH_CORRECTIONS`이다. 실제 코드와 어긋난 다음 항목을 수정했다.

- 기존 CLI가 subcommand가 아닌 flag 기반임을 반영
- 실제 테스트 파일명과 admin approval surface를 반영
- active manifest가 없는 환경의 dry-run 분기 추가
- conversation plan의 타입 선언 순서와 legacy restore 반환 계약 정정
- Graph clarification을 실제 `selections` 배열 계약으로 정정
- `RagPipeline`에 존재하지 않는 `self.index_mode` 참조 제거
- JSON metadata 예제에 고정 `query_scope` 추가

Release A는 독립 구현 가능하며 위 경계를 지키면 Developer handoff가 가능하다. Release B는 이 triage의 실행 범위가 아니다.

## Completion contract

Developer 최종 보고는 변경 파일, 실행 명령과 수치, dry-run 결과, 미실행·남은 위험, 격리/보호 상태를 포함하고 마지막 줄을 정확히 다음과 같이 끝낸다.

```text
DEVELOPER_RELEASE_A_IMPLEMENTATION_READY_FOR_REVIEW
```
