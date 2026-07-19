# Release B fixback 2 개발 인계

- 작성 시각: 2026-07-19 06:39 KST
- 판정 근거: `docs/reviews/2026-07-19-063646-release-b-fixback-rereview.md`
- 대상 DGX 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 보호 저장소: `/srv/shared/projects/insurance-rag-chatbot` (`fa8d734d643d18d6983447978de2210819717bc6`)

## 현재 판정

공개 payload, 다중 assertion, schema v2는 닫혔다. 이번 fixback은 아래 safe-baseline P1 세 건에만 한정한다. 특정 탈모/수술명/문구/코드 하드코딩으로 우회하지 않는다.

## P1-1. prepared registry로 GraphDB를 빌드하지 않음

독립 재현에서 `_build_graph_builder`가 받은 prepared registry를 `build_graph()`에 넘기지 않아 raw/quarantined 기본 registry가 선택되었다. 이후 prepared metadata만 덮어써 Graph 내용과 provenance가 불일치할 수 있다.

필수 조치:

- `build_graph(..., ontology_registry=registry, strict=True)`로 prepared registry를 명시 주입한다.
- raw/quarantined 기본 registry가 선택되면 즉시 fail-closed한다.
- Graph 내부 build manifest와 외부 manifest의 registry hash/state/count/source가 prepared registry와 일치하는지 검증한다.
- capture 회귀에서 `ontology_registry`와 `strict=True`가 실제 호출 인자로 전달됨을 고정한다.

## P1-2. 손상된 GraphDB가 verify를 통과함

현재 verify는 GraphDB 파일 존재만 보고 SQLite 실체를 검사하지 않는다. `b"not-a-sqlite-graph"`로 교체한 파일도 valid로 통과했다.

필수 조치:

- GraphDB를 read-only로 연다.
- SQLite header/schema, 필수 테이블/내부 `graph_build_manifest`, registry hash/state/count, 외부 manifest 일치, 최소 node/edge integrity를 확인한다.
- 깨진 SQLite, 누락 schema/table, 내부/외부 manifest 불일치, count/hash/state 불일치는 verify와 publish 모두 거부한다.
- 검증 과정은 DB를 수정하지 않는다.

## P1-3. publish 결과를 production resolver가 소비하지 않음

publish된 runtime root가 실제 `get_default_ontology_registry()`/RAG 경로에 연결되지 않는다. 기본 resolver는 여전히 repository raw `concepts.json`을 선택해 quarantined 상태다. 또한 runtime root에는 active/provenance/Graph만 있고 safe loader가 요구하는 base manifest/lock이 준비되지 않는다.

필수 조치:

- 기존 설정 체계를 확장해 production resolver가 **명시적** safe-baseline runtime root를 소비하게 한다. 새 전역 프레임워크는 만들지 않는다.
- runtime root에는 active, provenance, 검증 가능한 base manifest/lock, Graph 세트가 모두 있어야 한다.
- 앱/RAG 시작 시 이 세트의 완전성·valid 상태·hash 일치를 확인한다.
- 명시 runtime root가 지정되었는데 누락/invalid/quarantined이면 raw fallback 없이 fail-closed한다.
- runtime root가 지정되지 않은 기존 개발/테스트 동작을 무분별하게 깨지 말고, 운영 safe-baseline 모드에서만 강제한다.
- 성공 publish 뒤 실제 `get_default_ontology_registry()` 및 RAG 경로가 trusted 49, state valid, pending 6 유지, approved profile 0인 active를 선택하는 통합 회귀를 추가한다.

## 필수 TDD/검증 순서

1. Graph builder 호출 인자 capture RED -> 최소 주입 -> GREEN.
2. 손상 SQLite 및 내부/외부 manifest 불일치 RED -> read-only 검증 -> GREEN.
3. 임시 runtime root publish 뒤 실제 production resolver/RAG 선택 RED -> 명시 config 연결 -> GREEN.
4. 임시 root에서 실제 CLI `prepare -> verify -> publish -> resolver active 49/valid/profile 0 -> Graph 손상 verify/publish 거부 -> explicit rollback` 통합 검증.
5. public payload, 다중 assertion, schema v2 및 기존 수술종수/수가코드/HIRA/MX122/계산/5세대/이력/모델/Graph 테스트 회귀.
6. 전체 pytest, Node, build, isolated Playwright, `git diff --check`.

## 경계

- 구현은 지정 DGX 격리 작업공간에서만 한다.
- 보호 저장소, 운영 active ontology/provenance/GraphDB/index/DB/account/chat/log를 변경하지 않는다.
- pending correction 6건을 승인/apply하지 않는다.
- stage, commit, push, merge, deploy, restart를 하지 않는다.
- 운영 18080에 쓰기 요청을 보내지 않는다.
- 테스트는 임시 root/loopback에서만 하고 산출물·listener·symlink를 정리한다.
- 닫힌 세 영역을 다시 설계하거나 지엽적 하드코딩을 추가하지 않는다.

## 산출물

- `docs/278_CONVERSATIONAL_EVIDENCE_RESOLUTION_FIXBACK2_REPORT.md`
- 실제 재현 명령과 결과, 변경 파일, 미적용 운영 항목을 기록한다.
- 완료 표식: `DEVELOPER_RELEASE_B_FIXBACK2_READY_FOR_REREVIEW`
