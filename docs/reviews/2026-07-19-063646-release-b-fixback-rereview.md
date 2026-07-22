# Release B Fixback 독립 재검토

- 검토 시각: 2026-07-19 06:36:46 KST
- handoff: `docs/reviews/2026-07-19-062322-developer-fixback-handoff-triage.md`
- 대상: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- Developer marker: `DEVELOPER_RELEASE_B_FIXBACK_READY_FOR_REREVIEW`
- 보호 메인: `/srv/shared/projects/insurance-rag-chatbot` at `fa8d734d643d18d6983447978de2210819717bc6`
- 경계: read-only review. 제품 코드·운영 데이터·active ontology/provenance·GraphDB·index·계정·로그를 수정하지 않았고, stage/commit/push/merge/deploy/restart 및 protected `18080` 접근을 수행하지 않음.

## Findings

### P1. 준비된 registry가 아닌 raw 기본 registry로 GraphDB를 빌드함

`scripts/prepare_ontology_safe_baseline.py:78-93`의 `_build_graph_builder`는 준비된 `registry`를 받지만 `build_graph(...)`에 `ontology_registry=registry`와 `strict=True`를 전달하지 않는다. `src/graph/build.py:104-120`은 이 경우 `get_default_ontology_registry()`를 사용한다. 후보 workspace의 기본 resolver는 `data/ontology/concepts.json`을 선택하며 현재 상태는 `quarantined`이다.

독립 capture 결과:

```text
{'ontology_registry_kwarg': None,
 'strict': None,
 'captured_kwargs': ['active_source_chunks_path', 'canonical_manifest_path',
                     'rebuild', 'rule_links_path', 'source_mode']}
```

이후 `:94-104`에서 prepared registry의 metadata를 GraphDB와 외부 manifest에 덮어쓰므로, 실제 추출은 raw/quarantined registry로 수행하면서 manifest에는 safe baseline의 valid metadata가 기록될 수 있다. 이는 Graph 내용과 ontology provenance의 경계를 깨뜨리는 직접적인 결함이다.

필수 최소 수정: `build_graph(..., ontology_registry=registry, strict=True)`로 prepared active registry를 주입하고, build 내부 manifest와 외부 manifest가 같은 registry/hash/state인지 검증해야 한다. raw 기본 registry로 build가 시작되면 즉시 fail-closed해야 한다.

### P1. GraphDB가 손상되어도 `verify`가 valid로 통과함

`src/ontology/safe_baseline.py:191-209`의 `_verify_prepared_release`는 active/provenance registry와 외부 Graph manifest 값만 확인하고, GraphDB는 `is_file()` 여부만 검사한다. SQLite schema, 내부 `graph_build_manifest`, node/edge integrity 또는 외부 manifest와의 일치 여부를 읽기 전용으로 확인하지 않는다.

독립 재현:

1. 임시 release root에서 valid active/provenance/Graph artifact를 `prepare`한다.
2. prepared `insurance_graph.sqlite`를 `b"not-a-sqlite-graph"`로 교체한다.
3. 동일 release에 `verify_safe_baseline_release()`를 실행한다.

```text
{'verify_after_graph_corruption': 'accepted',
 'state': 'valid',
 'graph_file_size': 18}
```

따라서 publish 전에 손상되거나 다른 GraphDB로 바뀐 artifact가 검증을 우회할 수 있다. 필수 최소 수정은 GraphDB를 `readonly=True`로 열어 schema와 내부 manifest 필수값, registry metadata, integrity/count 검사를 수행하고 하나라도 불일치하면 verify/publish를 거부하는 것이다.

### P1. publish된 runtime root가 실제 앱의 기본 resolver에 연결되지 않음

새 `load_safe_baseline_runtime_registry()`는 `src/ontology/safe_baseline.py:218-234`에 있지만 production 호출자는 없고 테스트에서만 사용된다. 실제 RAG 경로는 `src/api/rag_service.py:344-350`에서 `get_default_ontology_registry()`를 호출한다. `src/ontology/registry.py:622-633`의 resolver는 환경변수, repository의 `concepts.active.json`, 아니면 raw `concepts.json`만 본다. `runtime_root`를 읽지 않으며, publish CLI도 resolver 환경 설정을 하지 않는다.

독립 결과:

```text
{'default_manifest': '.../data/ontology/concepts.json',
 'state': 'quarantined',
 'concept_count': 49,
 'quarantined': 6,
 'approved_profiles': 0}
```

또한 publish 직후처럼 active/provenance/Graph만 있는 임시 runtime root에 `load_safe_baseline_runtime_registry()`를 호출하면 다음과 같이 실패한다.

```text
SafeBaselineError: safe baseline runtime artifacts are unavailable; raw fallback is not allowed
```

`publish_safe_baseline_release()`는 `src/ontology/safe_baseline.py:371-413`에서 active/provenance/graph 세트만 교체하며 base manifest/lock을 runtime root에 준비하거나 앱 resolver를 그 root로 전환하지 않는다. 결과적으로 운영 publish가 성공해도 실제 앱은 raw/quarantined base를 읽을 수 있고, 안전 baseline 선택이 검증되지 않는다.

필수 최소 수정: publish가 사용하는 runtime root와 production resolver를 명시적 configuration으로 연결하고, active/provenance/base lock/Graph 세트가 모두 존재하고 valid일 때만 앱을 기동하도록 한다. 누락·quarantined 상태는 raw fallback 없이 fail-closed해야 한다. 성공 publish 후 실제 `get_default_ontology_registry()`/RAG 경로가 `49/valid/profile 0`을 선택하는 통합 회귀를 추가해야 한다.

## 이전 네 지적의 fixback 확인

- **공개 payload**: explicit allowlist가 `src/api/public_payloads.py:58-307`에 추가되었고 chat SSE, history, export가 이를 사용한다. 실제 evaluator payload와 nested 내부 키를 함께 넣은 독립 결과는 `renderable=True`, `public_forbidden_keys=[]`였다. `tests/test_public_payloads.py` 및 관련 focused 테스트가 통과했다.
- **다중 assertion**: `src/rag/conversation_context.py:617-639`가 기존 request ID와 assertion을 보존한다. 두 slot에서 `a=yes` 후 `b`만 남긴 독립 결과는 `multi_assertions_after=['a']`, `multi_request_id='req'`였고 새 회귀가 통과했다.
- **schema v2**: `src/rag/evidence_assessment.py:297-313`가 `display.primary_text`를 실제 evaluator 결과에 포함하고, `src/api/rag_service.py:1038-1044`가 이를 renderable로 인식한다. 실제 evaluator→public payload 결과에서 표시 text가 유지되고 structured path가 선택되었다.
- **pending/승인 경계**: safe baseline은 raw 55 중 trusted 49, pending correction 6을 유지하며 pending을 승인/apply하지 않았다. registry의 승인 profile은 여전히 valid active provenance operation path가 있을 때만 노출된다. 새 production 코드에 특정 탈모·문구·concept ID·수술명·HIRA/MX122 예외 하드코딩은 확인되지 않았다.

## Safe baseline CLI 독립 검증

임시 root와 보호 표준코드 DB read-only 참조로 실제 CLI `prepare`와 `verify`를 실행했다.

```text
prepare: state=prepared, release_id=rel-a
verify: state=verified, trusted_concept_count=49
```

임시 runtime에서 CLI `publish`와 `rollback`도 실행했다.

```text
missing confirmation: exit 2
publish: exit 0, rollback snapshot created
rollback: exit 0, all previous artifact bytes restored=True
```

기존 exception injection 회귀인 `test_publish_second_swap_failure_restores_all_runtime_artifacts`도 focused suite에 포함되어 통과했다. 다만 위 세 P1 때문에 정상적인 함수-level publish/rollback 통과만으로는 운영 안전성을 입증하지 못한다. 특히 Graph build registry 주입과 GraphDB 실체 검증, production resolver 연결이 먼저 고정되어야 한다.

## 독립 검증 결과

| 검증 | 결과 |
| --- | --- |
| Release B/fixback focused Python | `147 passed, 1 warning` |
| 전체 pytest, 임시 DB/user/log, E2E flag 미주입 | `1100 passed, 3 warnings` |
| isolated flag 충돌 표본 | `1 passed, 2 failed`; candidate의 기존 flag 충돌 재현 |
| Node tests | `45 passed, 0 failed` |
| frontend build 및 bundle syntax | 통과; 임시 build hash와 후보 bundle hash 일치 |
| isolated Playwright | 임시 symlink/root/user/secret, loopback `127.0.0.1:18779`에서 `13 passed` |
| `git diff --check` | exit 0 |

focused 범위에는 대화 상태, public payload, safe baseline, chat/history/retry, 수술종수·수가코드, HIRA, MX122, 계산, 5세대, 세션, Graph 및 모델 표시 관련 기존 회귀가 포함되었다. 전체 pytest와 Node 회귀도 통과했지만, 이는 P1의 production resolver/Graph artifact 경계를 대신하지 않는다.

Playwright 종료 후 후보 `node_modules` symlink, 18779 listener, E2E process, 임시 root가 남지 않았다. 후보는 HEAD `b1c0...`의 detached unstaged/uncommitted 상태이며 16 tracked changes와 13 untracked text/JSON/Python artifacts가 있다. staging 없음, debug breakpoint/private key/binary 없음.

보호 메인은 clean, HEAD `fa8d...`, `origin/master`와 실제 remote master `b1c0...`로 확인했다. 보호 port `18080`에는 접근하지 않았고 기존 uvicorn 외 서비스는 건드리지 않았다.

## 최소 Developer fixback 범위

```text
1. scripts/prepare_ontology_safe_baseline.py의 Graph builder가 prepared registry를 build_graph에 전달하고 strict=True를 사용하게 하십시오. raw/quarantined default registry로 build한 뒤 metadata만 덮어쓰지 마십시오.
2. verify가 GraphDB를 read-only로 열어 schema, 내부 graph_build_manifest, registry hash/state/count integrity를 검증하도록 하십시오. 깨진 SQLite/불일치 DB는 valid로 통과시키지 마십시오.
3. safe-baseline publish 결과를 실제 production resolver가 소비하도록 runtime root/config를 연결하십시오. active/provenance/base lock/Graph가 완전하고 valid일 때만 기본 RAG가 시작되고, 누락/invalid/quarantined면 raw fallback 없이 fail-closed해야 합니다.
4. 임시 root에서 실제 CLI prepare -> verify -> publish -> runtime resolver active 49/valid/profile 0 -> 의도적 Graph 검증 실패 원복 -> explicit rollback을 다시 검증하십시오. pending 6개와 보호 운영 환경은 변경하지 마십시오.
```

## Verdict

`CHANGES_REQUESTED`

REVIEW_RELEASE_B_FIXBACK_CHANGES_REQUESTED
