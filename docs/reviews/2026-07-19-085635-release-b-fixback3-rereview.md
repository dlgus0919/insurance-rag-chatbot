# Release B Fixback 3 독립 재검토

- 검토 시각: 2026-07-19 08:56 KST
- 대상 workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 후보 Developer 보고서: `docs/279_RELEASE_B_GRAPH_REFERENTIAL_INTEGRITY_FIXBACK3_REPORT.md`
- 직전 Review 보고서: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-19-081613-release-b-fixback2-rereview.md`
- 보호 main: `/srv/shared/projects/insurance-rag-chatbot`
- 보호 main HEAD: `fa8d734d643d18d6983447978de2210819717bc6`
- 검토 경계: read-only review. 제품 코드, 운영 active ontology/provenance/GraphDB/index, 계정, 로그를 변경하지 않았다. stage/commit/push/merge/deploy/restart를 수행하지 않았다.

## Findings

발견 사항 없음. 직전 P1의 orphan Graph 참조 결함은 공용 read-only 검증으로 닫혔고, 정상 artifact와 기존 ontology/runtime 경계도 비회귀로 확인되었다.

## 독립 최소 재현

로컬 `/tmp/release_b3_integrity.py`를 작성해 `scp`로 DGX `/tmp`에 전송하고, 후보 cwd에서 실행했다. 스크립트는 실제 `data/ontology/concepts.json`과 `data/ontology/policies/base_manifest.lock.json`을 사용하고 Graph 입력만 소형 fixture로 제한했다. 실행 직후 원격·로컬 스크립트와 stdout/stderr를 삭제했다.

```text
scp -i /Users/june_kim/.ssh/dgx_spark_ai_hang \
  /tmp/release_b3_integrity.py \
  ai-hang@100.88.5.57:/tmp/release_b3_integrity.py
ssh -i /Users/june_kim/.ssh/dgx_spark_ai_hang \
  ai-hang@100.88.5.57 \
  "cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719 && PYTHONPATH=. /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python /tmp/release_b3_integrity.py" \
  > /tmp/release_b3_integrity.stdout 2> /tmp/release_b3_integrity.stderr
```

실행 결과는 `exit_code=0`이며 stdout은 다음과 같다.

```text
projection raw=55 trusted=49 pending=6
normal_verify=pass
edge_node verify_reject= True publish_reject= True runtime_unchanged= True
alias_node verify_reject= True publish_reject= True runtime_unchanged= True
node_evidence verify_reject= True publish_reject= True runtime_unchanged= True
edge_evidence verify_reject= True publish_reject= True runtime_unchanged= True
source_evidence verify_reject= True publish_reject= True runtime_unchanged= True
integrity_check_non_ok verify_reject= True publish_reject= True runtime_unchanged= True
```

임시 runtime root에 대한 publish 호출은 거부 경로 검증에만 사용했으며 운영 artifact publish나 rollback은 수행하지 않았다.

## 필수 검토 항목

### Graph 참조 무결성

- `src/ontology/safe_baseline.py:217-278`이 `GraphStore(path, readonly=True)`로 열고, 필수 table을 확인한 뒤 `PRAGMA integrity_check`가 단일 `ok` 결과가 아니면 거부한다.
- 같은 경로에서 `PRAGMA foreign_key_check`의 row가 하나라도 있으면 거부한다.
- `graph_edges.source_evidence_id`는 schema FK가 없으므로 `src/ontology/safe_baseline.py:247-261`의 left join으로 `graph_evidence` 존재 여부를 별도 확인한다.
- `src/ontology/safe_baseline.py:310-341`의 공용 `_verify_prepared_release()`가 모든 검증을 수행한다. `verify_safe_baseline_release()`가 이를 직접 호출하고, `publish_safe_baseline_release()`도 검증 전에 같은 함수를 호출한다.
- 실제 fixture에서 edge source/target, alias, node-evidence, edge-evidence, 논리 source-evidence orphan을 각각 변조했을 때 verify와 publish가 모두 거부되었고, 기존 runtime tree bytes는 변하지 않았다.
- 정상 node/edge/evidence/alias artifact는 valid로 통과했다.

### 이전 경계 비회귀

- `scripts/prepare_ontology_safe_baseline.py:82-95`의 prepared registry 주입과 `strict=True` 계약은 유지된다. safe/Graph/CLI focused 실행에서 통과했다.
- `src/ontology/registry.py`와 `src/config.py`의 explicit safe runtime root resolver는 변경되지 않았고, 관련 focused 회귀에서 registry와 RAG/Graph가 같은 root를 소비하는 경로가 통과했다.
- 실제 raw projection은 `55 -> 49 trusted`, pending correction `6`이다. correction을 승인하거나 active/provenance/Graph/retrieval로 승격하지 않았다.
- raw/base `scripts/check_ontology_sync.py`는 `ontology integrity state is quarantined`로 `sync_exit_code=1`이었다. 이는 pending correction을 자동 적용하지 않는 의도된 배포 전 차단이다.
- 새 참조 무결성 계약에는 특정 질환·수술명·수가코드·concept ID 분기가 없으며, 일반 Graph artifact table/FK/논리 join 계약으로 구현되어 있다.

## 독립 검증 결과

| 범위 | 결과 |
| --- | --- |
| safe baseline / Graph / CLI / store focused | `36 passed` |
| 대화·근거·보험금·수가·수술종수·세션·관리자 Graph·모델 focused | `259 passed, 1 warning` |
| 전체 pytest, 임시 SQLite/users/logs | `1115 passed, 3 warnings` |
| Node `tests/*.mjs` | `45 passed, 0 failed` |
| frontend build + generated bundle syntax | 통과 |
| isolated Playwright, loopback `127.0.0.1:18783` | `13 passed (38.4s)` |
| `git diff --check` | 통과 |

격리 Playwright는 임시 root, SQLite, employee 계정, read-only standard-code DB reference를 사용했다. 후보 workspace의 Playwright `node_modules` symlink는 trap으로 제거되었고, port `18783`, listener, E2E process, 임시 root가 남지 않았다.

## 저장소·보호 경계

- 후보 HEAD는 기준 커밋 `b1c0b658a621552bb9b98a035d8883d6fba1dca2`이며, 의도된 dirty/uncommitted 상태를 보존했다. index는 clean이고 `docs/279...` 외 Fixback 3 제품 변경 파일은 없다.
- 보호 main은 clean이며 HEAD는 `fa8d734d643d18d6983447978de2210819717bc6`이다. 보호 `origin/master` ref와 실제 remote master는 `b1c0b658a621552bb9b98a035d8883d6fba1dca2`로 확인했지만 통합하지 않았다.
- 보호 서비스 PID `3996005`와 `127.0.0.1:18080` listener는 유지되었다. 보호 18080에는 요청을 보내지 않았다.
- active manifest/provenance, 운영 GraphDB/index, DB, 계정, 대화, 로그를 쓰지 않았고 서비스 재시작도 하지 않았다.

## 운영 전제 위험

지시대로 LLM 서버가 가동 중인 환경에서 5,781 chunks와 527,679 standard codes 전체 Graph 재빌드는 반복하지 않았다. 따라서 전체 데이터셋의 최종 node/edge 규모, 자원 사용량, 운영 root에서의 full publish 결과는 별도 자원 계획과 운영 승인 후 검증해야 한다. 이 미검증 항목은 현재 코드 계약의 기능 판정과 분리된 운영 전제 위험이다.

## Verdict

`PASS`

code promotion과 운영 active/provenance/Graph/index/service 반영은 별도 승인 후 수행해야 한다. 이번 Review Team은 제품 코드를 수정하지 않았다.

REVIEW_RELEASE_B_FIXBACK3_PASS
