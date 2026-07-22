# Release B Fixback 2 독립 재검토

- 검토 시각: 2026-07-19 08:16 KST
- 대상 workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 보호 main: `/srv/shared/projects/insurance-rag-chatbot`
- 보호 main HEAD: `fa8d734d643d18d6983447978de2210819717bc6`
- 인계 문서: `docs/reviews/2026-07-19-075423-developer-fixback2-handoff-triage.md`
- Developer 보고서: `docs/278_CONVERSATIONAL_EVIDENCE_RESOLUTION_FIXBACK2_REPORT.md`
- 검토 경계: read-only review. 제품 코드·운영 데이터·active ontology/provenance·GraphDB·index·계정·로그를 수정하지 않았고, stage/commit/push/merge/deploy/publish/rollback/restart를 수행하지 않았다.

## Findings

### [P1] Graph edge의 참조 무결성을 `verify`/`publish`가 검사하지 않음

**근거**

- 후보 `src/ontology/safe_baseline.py:217-254`는 SQLite를 read-only로 열고 필수 테이블, `graph_build_manifest`, 네 개의 row count만 읽는다.
- 후보 `src/ontology/safe_baseline.py:257-283`의 후속 검사는 ontology metadata와 내부·외부 manifest 값, node/edge/evidence/alias count만 비교한다. `PRAGMA integrity_check`, `PRAGMA foreign_key_check` 또는 node/edge/link의 참조 무결성 검사가 없다.
- Graph schema에 foreign key 선언은 있지만 `src/graph/store.py:79-90`, 이미 만들어진 DB를 read-only로 검증할 때 orphan row를 거부하는 검사는 별도로 실행되지 않는다.

**독립 재현**

실제 후보 `data/ontology/concepts.json`과 `data/ontology/policies/base_manifest.lock.json`으로 `raw=55`, trusted projection `49`, pending `6`인 임시 release를 만들었다. 임시 GraphDB에는 node 2개와 `n1 -> n2` edge 1개를 넣은 뒤, 별도 SQLite 연결에서 `n2`를 삭제하고 내부·외부 `node_count`를 실제 row 수인 `1`로 맞췄다. 이때 edge는 존재하지 않는 target node를 계속 가리킨다.

검토용 스크립트를 로컬 `/tmp`에 작성해 DGX `/tmp`로 `scp` 전송하고 후보 cwd에서 실행했다. 후보와 보호 저장소에는 파일을 만들지 않았다. 실행 직후 원격·로컬 임시 파일을 삭제했다.

관찰 결과:

```text
exit_code=2
verify_orphan_edge_accepted
publish_orphan_edge_accepted
```

즉, `verify_safe_baseline_release()`가 통과했고, 같은 artifact가 `publish_safe_baseline_release(..., operator_acknowledged=True)`도 통과했다. 손상 SQLite, 필수 테이블 누락, 내부·외부 count, 내부 ontology hash/state 변조는 별도 독립 재현에서 모두 거부되었으나, row count만 맞춘 orphan edge는 거부되지 않았다.

**영향**

참조 대상 node가 없는 GraphDB가 valid release로 간주되어 publish와 runtime 소비 경계까지 통과할 수 있다. 이후 Graph retrieval/admin Graph가 깨진 경로 또는 누락된 node를 기준으로 결과를 만들 수 있다. 이는 handoff의 `node-edge 불일치` fail-closed 계약 위반이다.

**필수 최소 fixback**

`src/ontology/safe_baseline.py`의 read-only Graph 검증에 SQLite `PRAGMA integrity_check`와 `PRAGMA foreign_key_check`를 추가하고, 결과가 `ok`가 아니거나 foreign-key 위반 row가 하나라도 있으면 `SafeBaselineError`로 거부하십시오. verify와 publish 양쪽에서 같은 검증을 재사용하고, orphan node/edge, node/edge-evidence, alias 참조를 포함하는 회귀를 추가하십시오. 검증은 계속 read-only여야 하며 runtime tree를 변경하지 않아야 합니다. 기존 hash/state/count/manifest 검증과 prepared registry 주입은 유지하십시오.

## 이전 P1 재검증

### P1-1 prepared registry 주입: 닫힘

- `scripts/prepare_ontology_safe_baseline.py:82-95`가 `build_graph(..., ontology_registry=registry, strict=True)`를 실제 호출한다.
- `tests/test_prepare_ontology_safe_baseline_cli.py:76-127`의 capture 회귀를 포함한
  `tests/test_safe_baseline.py`, `tests/test_prepare_ontology_safe_baseline_cli.py`,
  `tests/test_graph_build_active_sources.py`, `tests/test_graph_store.py` 실행 결과는
  `27 passed`였다.
- `src/ontology/safe_baseline.py:286-311`은 prepared registry의 ontology metadata와 외부·내부 Graph manifest 및 실제 count를 재검증한다.
- raw/base 기본 registry를 Graph builder가 암묵적으로 선택하는 이전 재현은 현재 코드와 capture test에서 닫혔다. 다만 위 P1의 참조 무결성 누락 때문에 이 경계의 전체 판정은 여전히 CHANGES_REQUESTED이다.

### P1-2 GraphDB read-only 무결성: 부분 개선, 위 P1로 미종결

독립 최소 검증에서 다음은 모두 reject되었다.

- 깨진 SQLite bytes
- 필수 table 누락
- 내부 manifest count 불일치
- 외부 manifest count 불일치
- 내부 ontology manifest hash 불일치
- 내부 ontology integrity state 불일치
- 손상 DB의 verify 및 publish 재검증

손상 DB publish 시 기존 임시 runtime tree bytes는 그대로였다. 그러나 orphan edge 재현은 통과했으므로 이 P1은 미종결이다.

### P1-3 명시 safe runtime root 소비: 닫힘

- `src/ontology/registry.py:625-649`는 `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT`가 설정되면 raw/base resolver 대신 `load_safe_baseline_runtime_registry()`를 사용한다.
- `src/config.py:359-380`은 같은 root의 `graph/insurance_graph.sqlite`를 선택한다.
- `src/rag/pipeline.py:1842-1850`은 safe root 설정 시 registry를 먼저 검증해 초기화 단계에서 실패시키고, GraphRetriever에도 같은 root 경로를 전달한다.
- `src/ontology/safe_baseline.py:320-336`은 base/lock/active/provenance/Graph manifest/DB가 모두 없거나 invalid하면 raw fallback 없이 실패한다.
- focused suite의 published-root, raw fallback, corrupt Graph startup, RAG Graph path 회귀가 통과했다. safe root 미설정 경로도 기존 default resolver를 유지한다.

실제 raw projection은 독립 실행에서 `55 -> 49 trusted`, `6 pending`으로 확인했다. 승인 operation을 적용하거나 pending correction을 active/Graph/retrieval로 승격하지 않았다. focused fixture의 approved profile은 `0`이었다.

## 일반화·회귀·운영 경계 점검

- 새 safe-baseline/evidence/conversation 코드에서 특정 탈모·질환·concept ID·수술명·수가코드에 종속된 production 예외는 발견하지 못했다. 사용자 assertion과 clarification은 session-local 상태로만 처리된다.
- 기존 Release B의 `source_grounded_answers.py` 대체/테스트 축소를 포함한 전체 dirty diff를 읽었고, 이번 fixback에서 새 domain-specific 우회는 확인하지 못했다. focused/full/Node/E2E 회귀로 기능 은닉 또는 테스트 전면 약화의 추가 증거는 없었다.
- raw/base `scripts/check_ontology_sync.py`는 `ontology integrity state is quarantined`로 실패했다. 이는 pending 6건을 자동 적용하지 않는 배포 전 정상 차단이다.
- `git diff --check`: 통과.
- 후보 status는 기준 커밋 `b1c0b658a621552bb9b98a035d8883d6fba1dca2`의 unstaged/uncommitted 상태를 유지했고 staging은 비어 있었다. 임시 `node_modules` symlink, E2E root, port `18782`, listener와 process는 실행 후 제거되었다. 비밀·credential·`.sqlite`·log·`__pycache__` 임시 산출물은 후보 status에 남지 않았다.
- 보호 main은 clean, HEAD는 `fa8d734d643d18d6983447978de2210819717bc6`, 보호 checkout의 `origin/master` ref와 실제 remote master는 `b1c0b658a621552bb9b98a035d8883d6fba1dca2`였다. 통합·push는 수행하지 않았다.
- 기존 보호 서비스 PID `3996005`와 `127.0.0.1:18080` listener는 그대로 확인했다. 보호 18080에는 접근하지 않았다.

## 독립 검증 결과

| 범위 | 결과 |
| --- | --- |
| safe baseline / prepared Graph / readonly Graph focused | `27 passed` |
| 대화·근거·보험금·수가·수술종수·세션·관리자 Graph·모델 focused | `253 passed, 1 warning` |
| 전체 pytest, 임시 SQLite/users/logs | `1109 passed, 3 warnings` |
| Node `tests/*.mjs` | `45 passed, 0 failed` |
| frontend build + generated bundle syntax | 통과 |
| isolated Playwright, loopback `127.0.0.1:18782` | `13 passed (35.3s)` |
| raw/base ontology sync | quarantined reject |
| actual raw projection | `55 -> 49 trusted, pending 6` |
| full Graph rebuild | 수행하지 않음 |

## 운영 전제 위험

지시대로 5,781 청크와 527,679 표준코드 전체 Graph 재빌드는 반복하지 않았다. 따라서 전체 데이터셋의 최종 node/edge 규모, 자원 사용량, 운영 root publish 결과는 별도 자원 계획과 승인 후 검증해야 한다. 이 운영 전제 위험은 위에서 재현된 orphan-edge 기능 결함과 별개이며, 현재는 code promotion이나 운영 active/Graph 반영을 진행할 수 없다.

## Verdict

`CHANGES_REQUESTED`

Developer fixback은 orphan edge 및 foreign-key 참조 무결성을 read-only verify/publish에서 fail-closed하도록 최소 수정한 뒤, 동일 임시 fixture에서 `verify reject`, `publish reject`, `runtime tree unchanged`를 재현해 Review Team 재검토를 요청해야 한다. Review Team은 제품 코드를 수정하지 않았다.

REVIEW_RELEASE_B_FIXBACK2_CHANGES_REQUESTED
