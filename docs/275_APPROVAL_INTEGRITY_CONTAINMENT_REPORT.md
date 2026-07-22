# 온톨로지 승인 무결성 및 운영 격리 구현 보고서

- 작성일: 2026-07-18
- 범위: Release A - 온톨로지 승인 무결성 및 운영 격리
- 격리 작업 기준: `fa8d734d643d18d6983447978de2210819717bc6`
- 신뢰 기준 원본: `7d4d08af1cf04077484c80fec8a2377826ddff09`의 승인 전 온톨로지

## 결론

승인 범위와 출처를 재현할 수 없는 온톨로지 변경은 운영 지식으로 승격하지 않고 격리하는 경계를 구현했다. 이번 작업은 후보를 승인하거나 active manifest, GraphDB, 검색 인덱스에 반영하지 않았다. 현재 원시 온톨로지에만 존재하는 6개 미검증 delta는 dry-run에서 quarantine되며, 그 결과 운영 반영 경로는 fail-closed로 중단된다.

## 구현 내용

### 1. 신뢰 기준과 해시 잠금

- `data/ontology/policies/base_manifest.lock.json`에 승인 전 기준 manifest의 canonical hash와 source revision을 기록했다.
- `src/ontology/approval_integrity.py`가 canonical JSON hash, 기준 잠금 검증, 신뢰 projection, quarantine 결과를 계산한다.
- 현재 원시 `concepts.json`의 55개 중 기준 49개는 신뢰하고, 다음 6개는 legacy 승인 provenance가 없어 quarantine한다.
  - `cov.hair_loss`
  - `cond.age_related_hair_loss`
  - `cond.disease_related_hair_loss`
  - `cond.treatment_side_effect_hair_loss`
  - `cond.work_daily_life_impairment`
  - `cond.pay_nonpay_status`

### 2. 후보 control/runtime 분리와 field-level 승인

- review store는 lifecycle, reviewer, 승인 경로 같은 control field와 실제 온톨로지 payload를 분리한다.
- 후보의 승인 hash에는 control field가 포함되지 않는다.
- `ApprovalPatch`는 명시적으로 승인된 field path만 merge하도록 제한하고, legacy 후보처럼 field-level provenance를 재현할 수 없는 경우 `legacy_unverifiable`로 fail-closed 처리한다.
- CLI, 로컬 검토 UI, 관리자 API는 같은 승인 경로 정책을 사용한다.

### 3. 운영 반영 전 검증 경계

- manifest merge는 trusted projection과 승인 patch만 병합하고 provenance sidecar를 생성한다.
- apply dry-run, candidate audit, registry, graph build/check 경로가 모두 base lock과 provenance를 검증한다.
- registry는 검증되지 않은 concept를 runtime에서 노출하지 않고 quarantine 상태를 반환한다.
- GraphDB build는 검증된 registry만 seed하며, graph manifest에 ontology hash, integrity state, quarantine count를 기록하도록 강화했다.
- 관리자 지식 진단 API와 화면은 무결성 aggregate를 읽기 전용으로 표시한다.

### 4. 교정 후보와 운영 경계

- `docs/review_artifacts/2026-07-18-hair-loss-full-payload-correction-candidate.json`에 전체 payload, 근거, 직접 pin을 담은 교정 후보를 준비했다.
- 후보 ID는 `practitioner.cov.hair_loss.full-payload-correction.20260718`이며 `status: pending`, `test_candidate: false`다.
- 후보는 실무자 명시 승인 전까지 active apply, GraphDB rebuild, 재인덱스 대상이 아니다.

## 실제 dry-run 결과

다음은 격리 작업공간에서 수행한 비변경 dry-run이다.

```bash
PYTHONPATH=$PWD $PYTHON scripts/ontology_review.py --apply --dry-run \
  --base data/ontology/concepts.json \
  --base-lock data/ontology/policies/base_manifest.lock.json
```

- 상태: `quarantined`
- 검증 결과: `valid: false`
- trusted/active projection hash: `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`
- quarantine concept 수: 6
- 승인 operation 수: 0
- manifest diff 수: 0
- legacy 승인 추정 수: 0
- JSON artifact SHA-256: `9131f10cd4893a1a7a6e4dd16e61337e11a96be03a79012b8039a231383e79cc`

보호 GraphDB는 읽기 전용으로 비교만 수행했다. 향후 승인된 projection을 별도 통제 절차로 적용하면 GraphDB에서 위 6개 ontology node와 연결된 21개 registry alias가 신뢰 projection과 달라질 수 있다. 이번 작업에서는 rebuild나 교체를 하지 않았다.

## fail-closed 검사 결과

현재 운영 GraphDB와 raw source는 새 승인 무결성 metadata를 아직 가지지 않으므로 아래 검사는 의도대로 non-zero로 종료했다.

| 검사 | 결과 | 의미 |
| --- | --- | --- |
| `scripts/check_ontology_sync.py` | `RC=1` | registry state가 `quarantined`라서 운영 동기화를 통과로 오인하지 않음 |
| `scripts/check_graph_index.py --graph <read-only-graph>` | `RC=1` | graph manifest에 expected ontology hash, integrity state, quarantine count가 없어 사용을 차단 |
| `scripts/check_graph_vector_sync.py --graph <read-only-graph>` | `RC=1` | 같은 graph manifest 불일치로 vector sync 이전에 중단 |

이는 결함이 아니라 unapproved delta가 있는 상태에서 운영 지식과 GraphDB를 정상으로 선언하지 않도록 하는 정책 결과다.

## 검증

모든 Python 검증은 임시 대화 DB, 사용자 파일, 로그 경로를 명시적으로 주입했고 종료 후 제거했다. 운영 계정, 대화, 계산 이력, 감사 로그에는 쓰지 않았다.

| 검증 | 결과 |
| --- | --- |
| 승인 무결성 focused suite | `87 passed, 1 warning` |
| full pytest | `1033 passed, 3 warnings` |
| 수술종수, HIRA 게이트, 도수치료, 계산 스레드, 세션, 관리자 Graph 회귀 | `123 passed, 1 warning` |
| historical source-grounded/Graph fixture 회귀 | `27 passed` |
| Node 관리자 지식 화면 테스트 | `15 passed` |
| `node --check frontend/js/pages/admin.js` | 통과 |
| `npm run build` | 통과 |
| isolated Playwright write E2E | `1 passed` |
| protected `18080` GET-only Playwright smoke | `1 passed` |
| `git diff --check` | 통과 |

격리 Playwright E2E는 loopback 임시 포트와 임시 DB·테스트 계정만 사용했다. `도수치료` 후보 선택 후 `MX122`를 전송하고, 4세대·통원·산정특례 미확인·비급여 500,000원에서 공제 150,000원, 예상 지급 350,000원, 검토 필요 상태와 동일 스레드 후속 질의 연결을 확인했다. 보호 앱 `18080`은 health, 실행 LLM 상태, 로그인 화면만 GET으로 확인했다.

프런트 빌드는 격리 checkout에 의존성을 새로 설치하지 않고, 검증 중에만 읽기 전용 기존 Playwright/Node 의존성을 참조했다. 임시 `node_modules` 링크와 Playwright artifact 루트은 모두 제거했다.

### Whole-manifest lock fixback

검토에서 lock이 `schema_version`, `description`, `concepts` 전체를 hash로 기록하지만 trusted projection은 개념 hash만 확인한다는 누락이 확인됐다. 따라서 개념은 모두 그대로 둔 채 설명 또는 schema version만 바꾸면 base registry와 active audit이 유효로 보일 수 있었다.

- trusted projection을 다시 canonical manifest hash로 계산한다.
- 모든 locked concept이 일치한 상태에서 이 hash가 lock과 다르면 `BASE_MANIFEST_HASH_MISMATCH`를 기록하고 상태를 `stale`로 전환한다.
- base registry는 이 전역 stale 상태에서 concept를 하나도 노출하지 않는다. active audit도 provenance가 내부적으로 일관되더라도 같은 mismatch를 유효로 처리하지 않는다.
- 현재 사건의 6개 extra untrusted concept은 여전히 개별 quarantine이다. trusted 49개 projection hash는 lock과 일치하므로 전역 outage로 확대되지 않는다.

실패 우선 회귀는 description/schema version drift와 active audit, registry 차단을 포함해 수정 전 `5 failed`였고 수정 후 `5 passed`가 됐다. 실제 raw manifest dry-run은 `status: quarantined`, trusted projection hash `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`, quarantine 6건, approval operation 0건, manifest diff 0건을 유지했다.

| fixback 검증 | 결과 |
| --- | --- |
| approval-integrity focused batch | `65 passed, 1 warning` |
| 수술종수, HIRA, MX122, 계산, 세션, source-grounded, 관리자 Graph 회귀 | `139 passed, 1 warning` |
| 관리자 Node 회귀 및 `node --check frontend/js/pages/admin.js` | `24 passed` |
| isolated Playwright MX122 후보 선택·동일 스레드 후속 질의 E2E | `1 passed` |
| 전체 pytest | `1038 passed, 3 warnings` |

이 검증은 임시 DB·사용자·로그 경로로만 실행했고, active manifest, GraphDB, 검색 인덱스, 운영 서비스와 운영 데이터를 변경하지 않았다.

## 변경 파일

### 정책, 승인, registry, graph

- `data/ontology/ontology_manifest.schema.json`
- `data/ontology/policies/base_manifest.lock.json`
- `data/ontology/policies/review_policy.json`
- `src/ontology/__init__.py`
- `src/ontology/approval_integrity.py`
- `src/ontology/manifest_merge.py`
- `src/ontology/policy.py`
- `src/ontology/registry.py`
- `src/ontology/review_store.py`
- `src/graph/build.py`
- `src/graph/extractors.py`
- `src/ingest/knowledge_apply.py`

### 검토, 진단, API, 화면

- `scripts/audit_ontology_approval_integrity.py`
- `scripts/build_graph_index.py`
- `scripts/check_graph_index.py`
- `scripts/check_graph_vector_sync.py`
- `scripts/check_ontology_sync.py`
- `scripts/ontology_review.py`
- `scripts/ontology_review_local_ui.py`
- `src/api/routes/admin.py`
- `src/api/routes/knowledge.py`
- `src/api/schemas/knowledge.py`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`
- `frontend/dist/app.min.js`

### 회귀 테스트

- `tests/test_ontology_approval_integrity.py`
- `tests/test_ontology_review_cli.py`
- `tests/test_ontology_review_local_ui.py`
- `tests/test_ontology_review_store.py`
- `tests/test_ontology_manifest_merge.py`
- `tests/test_ontology_registry.py`
- `tests/test_graph_build_active_sources.py`
- `tests/test_knowledge_apply.py`
- `tests/test_api_admin.py`
- `tests/test_api_admin_knowledge.py`
- `tests/test_admin_knowledge_frontend.mjs`
- `tests/test_source_grounded_answers.py`
- `tests/test_graph_query_planner.py`

역사적 source-grounded 동작을 검증하는 테스트는 raw historical manifest를 명시적으로 주입하는 forensic fixture를 사용한다. 이는 production registry의 quarantine 경계를 약화하지 않는다.

## 운영 비변경 증거

- `data/ontology/concepts.json`은 diff가 없다.
- active ontology manifest, active provenance sidecar, active review 산출물은 이 격리 작업에서 생성하거나 수정하지 않았다.
- active rule 및 data index 경로에는 diff가 없다.
- 보호 checkout의 HEAD와 `origin/master`는 모두 `fa8d734d643d18d6983447978de2210819717bc6`이다.
- 보호 checkout의 유일한 untracked 파일은 live SQLite runtime sidecar인 `insurance_chat.db-wal`, `insurance_chat.db-shm`이며, DB와 같은 runtime owner의 regular file임을 읽기 전용으로 확인했다. 삭제, checkpoint, rename, ignore 처리를 하지 않았다.
- API/LLM 서비스 재시작, GraphDB rebuild, BM25/Chroma 재인덱스, candidate apply, commit, push를 수행하지 않았다.
- 최종 preflight에서 보호 HEAD와 `origin/master`가 모두 `fa8d734d643d18d6983447978de2210819717bc6`임을 재확인했고, 격리 작업용 `/tmp` 루트와 임시 서버 프로세스가 남아 있지 않음을 확인했다.

## 남은 위험과 다음 승인

1. 교정 후보의 field-level 승인 범위와 근거를 실무자가 검토해야 한다.
2. 승인 후에만 trusted projection을 active manifest/provenance로 원자 적용하고, 임시 GraphDB rebuild 및 hash/integrity 검증을 수행해야 한다.
3. 그 다음에만 보호 앱을 통제된 방식으로 재시작하고, 실제 검색과 관리자 진단 smoke를 별도 승인 하에 실행해야 한다.
4. 현재 6개 delta가 quarantine된 상태이므로 해당 개념을 runtime에서 사용해야 하는 운영 요구는 승인 절차 완료 전까지 보류된다.

## Self-inspection

- 범위 밖의 보험 지식 분기나 candidate 승인 로직을 추가하지 않았다.
- active ontology, GraphDB, 검색 인덱스, 운영 DB, 서비스에 쓰기 작업을 하지 않았다.
- 임시 테스트 서버, Playwright artifact, pytest 루트를 정리했다.
- 이 보고서는 격리 작업공간의 미커밋 변경과 검증 결과만 기록한다.

## 최종 artifact boundary fixback

재검토에서 승인 산출물과 manifest metadata 경계에 세 가지 우회 가능성이 확인됐다. 모두 특정 보험 개념이나 후보 ID가 아닌 범용 artifact 검증 경계에서 수정했다.

1. active manifest가 trusted base와 `schema_version` 또는 `description`만 달라져도, provenance의 `active_content_hash`를 새 값으로 다시 계산하면 유효처럼 보일 수 있었다.
2. lock/patch JSON 파서는 일부 불완전 metadata, 지원하지 않는 schema, malformed array row, 빈 operation을 충분히 거부하지 않았고, 직접 만든 in-memory patch는 parse 경계를 거치지 않을 수 있었다.
3. Graph manifest의 expected 값이 빈 문자열인 경우 required metadata key 자체가 빠져도 무결성 검사가 통과할 수 있었다.

### 수정 계약

- active audit은 trusted base와 active manifest의 top-level `schema_version`, `description`을 별도로 비교한다. 차이가 있으면 provenance hash가 내부적으로 일치해도 `UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA`로 stale 처리하며 active registry는 concept를 0건 노출한다.
- `BaseManifestLock`과 `ApprovalPatch`는 schema version 1만 허용한다. hash, reviewer, reviewed_at 등 필수 metadata와 배열 row의 형태를 검증하며 빈 operation은 parse와 apply 경계 모두에서 거부한다.
- merge/apply 직전에도 patch invariant를 다시 검증하므로 직접 생성된 in-memory artifact도 파서 우회를 통해 적용될 수 없다.
- Graph manifest는 expected 값이 빈 문자열이더라도 모든 required metadata key의 존재를 먼저 확인한다.
- raw 55개 중 trusted 49개와 extra untrusted 6개 quarantine 계약은 그대로 유지했다. 실제 dry-run은 approval operation 0건, manifest diff 0건을 유지했고 pending 교정 후보는 적용하지 않았다.

### red-to-green 및 최종 검증

새 회귀를 먼저 추가한 뒤 아래 approval-integrity 세 파일을 실행했다.

| 단계 | 결과 |
| --- | --- |
| 수정 전 `test_ontology_approval_integrity.py`, `test_ontology_registry.py`, `test_ontology_manifest_merge.py` | `24 failed, 29 passed` |
| 최소 수정 후 같은 suite | `54 passed` |
| approval/review-store/merge/registry/Graph/API 및 수술종수·HIRA·MX122·계산·세션 focused suite | `240 passed, 1 warning` |
| 전체 pytest (임시 DB·사용자·로그 root) | `1064 passed, 3 warnings` |
| Node 관리자 회귀 | `15 passed, 0 failed` |
| `node --check frontend/js/modules/admin.js`, `node --check frontend/js/pages/admin.js` | 통과 |
| frontend build | 통과. 격리 workspace에 의존성을 설치하지 않고 보호 checkout의 읽기 전용 Node dependency 경로만 검증 시 참조 |
| isolated Playwright write E2E | `1 passed` |
| `git diff --check` | 통과 |

full pytest의 3개 warning은 기존 라이브러리 deprecation (`passlib` 1건, Pillow 2건)이며 실패는 없었다. 실행 종료 뒤 별도 확인으로 pytest와 Playwright의 `/tmp` root가 모두 제거된 것을 확인했다.

실제 `ontology_review.py --apply --dry-run`은 `quarantined`, trusted projection hash `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`, quarantine 6건, approval operation 0건, manifest diff 0건을 반환했다. `check_ontology_sync.py`는 이 미승인 quarantine 상태에서 의도대로 non-zero로 fail-closed 했다.

### 최종 경계 확인

- `data/ontology/concepts.json`, active ontology/rule manifest, GraphDB, 검색 인덱스, 운영 DB·계정·대화·감사 로그는 변경하지 않았다.
- 보호 checkout은 `fa8d734d643d18d6983447978de2210819717bc6`이며 `origin/master`와 일치한다. tracked/staged diff는 없고 live SQLite WAL sidecar 두 개만 기존 그대로 보존했다.
- 격리 workspace의 변경은 unstaged/uncommitted 상태로 남겼다. 이번 작업에서 `git add`, commit, push, deploy, 서비스 재시작, candidate apply, GraphDB rebuild, reindex는 수행하지 않았다.

## Runtime artifact schema 및 lock 원형 검증 fixback

재검토에서 manifest hash와 runtime 경계가 아직 두 방식으로 우회될 수 있음이 확인됐다.

1. `manifest_content_hash()`가 알려진 세 top-level field만 선택해 hash하므로, 향후 또는 임의의 다른 선언 field가 변경되어도 hash가 바뀌지 않았다.
2. direct base/active load와 active provenance audit은 repository manifest schema 및 provenance schema를 충분히 검증하지 않았다. provenance hash를 변조된 값으로 다시 계산하면 rogue top-level field 또는 malformed row를 정상처럼 보이게 할 여지가 있었다.
3. `BaseManifestLock.from_dict()`가 concept hash row를 문자열로 강제 변환하거나 누락 row를 건너뛰어 malformed lock 입력을 조용히 약화할 수 있었다.

### 최소 수정과 계약

- `src/ontology/manifest_schema.py`에 repository ontology manifest schema와 strict active provenance schema를 공용 validator로 두었다. base/active runtime load, active audit, merge 전 provenance 생성이 같은 validator를 사용한다.
- canonical manifest hash는 생성용 `version`만 제외하고 나머지 전체 top-level content를 canonical JSON hash에 포함한다. 따라서 `version` 단독 변경은 안정적이고, description이나 향후 선언 field 변경은 hash drift로 처리된다.
- invalid base/active/provenance artifact는 direct audit에서 명확히 거부되며, registry에서는 stale 상태와 concept 0건으로 fail-closed 한다.
- `BaseManifestLock`은 schema version 1, non-empty string metadata, 그리고 non-empty string key/value만 가진 concept hash map을 원형 그대로 요구한다. malformed row 하나라도 있으면 lock 전체를 거부한다.
- 정상 raw 55개 중 trusted 49개와 extra untrusted 6개 quarantine 계약은 유지했다. trusted projection hash는 `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`로 기존 lock과 일치한다.

### 실패 우선과 최종 검증

새 runtime schema/lock 회귀를 먼저 추가한 상태에서 관련 suite는 `20 failed, 41 passed`로 실패했다. 최소 수정 후 같은 핵심 suite는 `61 passed`, direct active audit 경계를 포함한 확장 suite는 `79 passed`가 됐다.

| 검증 | 최종 결과 |
| --- | --- |
| approval/merge/registry/review/Graph/API focused pytest | `197 passed, 1 warning` |
| 전체 pytest (임시 DB·사용자·로그 root) | `1085 passed, 3 warnings` |
| Node 관리자 화면 회귀 | `15 passed, 0 failed` |
| `node --check frontend/js/modules/admin.js`, `node --check frontend/js/pages/admin.js` | 통과 |
| frontend build | 통과. 격리 checkout의 임시 dependency link는 즉시 제거 |
| isolated Playwright MX122 후보 선택·동일 스레드 후속 질의 E2E | `1 passed` |
| `git diff --check` | 통과 |

전체 pytest warning 3건은 기존 의존성 deprecation(`passlib` 1건, Pillow 2건)이며 실패는 없었다. isolated E2E는 임시 loopback port, 임시 DB·테스트 계정·로그와 read-only standard-code reference만 사용했으며, 종료 후 listener 0건과 임시 root 제거를 확인했다.

실제 `ontology_review.py --apply --dry-run`은 `quarantined`, trusted projection hash `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`, quarantine 6건, approval operation 0건, manifest diff 0건을 반환했다. `check_ontology_sync.py`는 이 미승인 quarantine 상태에서 `RC=1`로 fail-closed 했다. 이는 active apply가 수행되지 않았다는 정상 경계 결과다.

### 이번 fixback의 비변경 범위

- `data/ontology/concepts.json`, active ontology/provenance/rule manifest, GraphDB, 검색 인덱스, 운영 DB·계정·대화·감사 로그를 변경하지 않았다.
- 후보 승인·apply, GraphDB rebuild/reindex, API·LLM·서비스 재시작, 보호 main 수정, stage/commit/push/deploy를 수행하지 않았다.
- 격리 작업공간의 변경은 여전히 unstaged/uncommitted이며, 다음 단계는 Review Team의 재검토다.
