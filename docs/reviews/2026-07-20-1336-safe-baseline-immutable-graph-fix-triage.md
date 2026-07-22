# Safe-baseline immutable Graph runtime fix triage

- Timestamp: 2026-07-20 13:36:07 +0900
- Cycle: safe-baseline-immutable-graph-fix-20260720-1336
- Planner thread: `019f635f-f9e1-7c21-bc89-50d7fc59d4ee`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`

## Reported

- MRI 연간 한도 패치는 DGX 보호 메인 `e32f56ee29fdf974976ecbec3b70d8f533bfa01d`에 정확히 반영됐다.
- 안전한 byte-copy Graph 기준에서 planner 23, chat 44, Graph/API/계산 상위 191 회귀가 통과했다.
- API-only 재기동 직전, 운영 safe-baseline Graph 옆의 SQLite `-wal`/`-shm` sidecar 때문에 새 프로세스의 fail-closed 검증이 실패한다는 사실이 확인됐다.

## Observed

- `load_safe_baseline_runtime_registry()`는 sidecar가 하나라도 존재하면 런타임을 거부한다.
- safe-baseline 검증은 `GraphStore(..., readonly=True, immutable=True)`를 사용한다.
- 실제 일반 질의 Graph 검색은 `GraphRetriever.retrieve()`에서 `GraphStore(..., readonly=True)`만 사용하고 `immutable=True`를 전달하지 않는다.
- SQLite WAL 형식 DB를 non-immutable read-only로 여는 동작은 빈 WAL/SHM sidecar를 만들 수 있다. v1.2.0 승격 기록에도 읽기 검증 중 빈 sidecar가 생성된 사례가 남아 있다.
- 현재 API는 health 정상이며 기존 프로세스가 계속 서비스 중이다. 운영 Graph, 대화 DB, 계산 룰/링크/처리 정책은 변경되지 않았다.

## Findings

### P0 — safe-baseline 계약과 실제 Graph 검색 연결 모드가 모순됨

safe-baseline은 불변 스냅샷이며 시작 시 sidecar를 금지하지만, 런타임 검색 연결은 non-immutable read-only 모드라 sidecar를 다시 만들 수 있다. 따라서 한 번 정상 활성화된 프로세스가 다음 API 재기동을 스스로 차단한다.

이는 MRI 문구나 특정 질의와 무관한 공통 런타임 경계 결함이다. sidecar를 단순 삭제하는 조치만으로는 재발한다.

## Decision

`DEVELOPER_FIXBACK`

## Required implementation

1. safe-baseline runtime root를 사용하는 Graph 검색 연결만 SQLite immutable read-only로 연다.
   - mutable/local Graph 경로의 기존 동작은 유지한다.
   - 질환명, MRI 문구, 특정 테스트 문장을 조건으로 사용하지 않는다.
2. safe-baseline 모드에서 Graph 질의를 반복해도 WAL/SHM이 생성되지 않는 회귀 테스트를 추가한다.
3. 기존 safe-baseline fail-closed 검증을 약화하지 않는다. sidecar 허용 또는 자동 삭제로 우회하지 않는다.
4. 기존 MRI 패치 6개 파일과 계산 룰/온톨로지/Graph 데이터는 변경하지 않는다.
5. 격리 workspace에서 focused 및 상위 회귀를 실행하고 커밋 후보를 만든다. 보호 메인 반영, API 재기동, push는 Review Team PASS 전 금지한다.

## Post-review deployment design

Review Team PASS 뒤에는 현재 운영 root를 제자리 수정하지 않는다.

1. 기존 v1.2.0의 검증된 ontology/Graph 파일만 새 versioned runtime root로 byte-copy한다.
2. 새 root는 원본과 inode가 달라야 하며 sidecar 0, Graph SHA-256/integrity/FK/manifest/ontology 검증을 모두 통과해야 한다.
3. API만 중지한 뒤 기존 프로세스가 Graph 파일을 잡고 있지 않은지 확인한다.
4. offline env의 safe-baseline root만 새 versioned root로 원자 전환하고 API만 시작한다.
5. 새 API가 immutable Graph 연결을 사용하고, health/모델/Graph/계산 룰/사용자 데이터 지문이 유지되며 sidecar가 재생성되지 않는지 확인한다.
6. 실패 시 env를 기존 root로 복원하고 API-only rollback한다. 기존 runtime root와 sidecar는 삭제하거나 변경하지 않는다.

## Stop rules

- LLM/SGLang, 전체 스택, Graph rebuild, ontology rebuild, active rule promotion 금지.
- 기존 runtime WAL/SHM 삭제·rename·truncate 금지.
- 사용자 계정·대화·로그 생성 또는 변경 금지.
- Review Team PASS 전 보호 메인 반영 금지.
- 원격 push/tag/release 금지.
