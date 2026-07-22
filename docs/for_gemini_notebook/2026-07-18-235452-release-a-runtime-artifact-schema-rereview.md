# Release A runtime artifact schema fixback 독립 재검토

- 검토 시각: 2026-07-18 23:54 KST
- 검토 유형: Review Team 독립 read-only re-review
- Developer marker: `DEVELOPER_RELEASE_A_RUNTIME_ARTIFACT_SCHEMA_FIXBACK_READY_FOR_REVIEW`
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- protected main: `/srv/shared/projects/insurance-rag-chatbot`
- expected base: `fa8d734d643d18d6983447978de2210819717bc6`
- 최종 판정: **PASS**

## Findings

없음. 이번 fixback의 요청 경계에서 재현 가능한 blocking finding은 확인되지 않았다.

## 필수 경계 재현

- `src/ontology/manifest_schema.py:27-111,145-156`은 repository manifest와 active provenance를 각각 strict JSON Schema로 검증한다. 모듈은 JSON/`jsonschema`만 의존하고 `approval_integrity`·`registry`를 역참조하지 않아 순환 의존성이 없다.
- `src/ontology/approval_integrity.py:40-45`의 `manifest_content_hash()`는 `version`만 제거한다. version만 변경하면 hash가 유지되고, rogue top-level field를 추가하면 hash가 달라졌다.
- base/active의 rogue top-level field, required field 누락, malformed concept row는 `build_trusted_base_projection()`와 `audit_active_manifest()`에서 `ValueError`로 거부됐다. `src/ontology/approval_integrity.py:639-646,911-922`가 base/active/provenance의 공통 검증 경계다.
- 동일 변조를 `OntologyRegistry`에 주입하면 `stale`, concept `0`건으로 종료됐다. active input/schema 오류는 `src/ontology/registry.py:293-323`에서 fail-closed 처리된다.
- provenance의 schema 0, required field 누락, unknown top-level field, malformed operation row, recomputed hash 변조는 direct audit에서 모두 거부되고 Registry는 `stale/0 concepts`가 됐다. 현재 merge가 생성하는 정상 provenance는 validator를 통과하고 `valid`로 로드됐다.
- `BaseManifestLock.from_dict()`는 `src/ontology/approval_integrity.py:110-147`에서 원래 모든 concept-hash row를 검증한다. valid row에 empty key/hash 또는 non-string key/hash를 섞은 lock은 전체 거부됐고, 정상 `to_dict()` round-trip은 유지됐다.
- 이전 drift, malformed/in-memory ApprovalPatch, stale candidate/evidence/base, unsupported approval path, Graph required metadata key 검사는 독립 표본 `13 passed`로 재검증됐다. 정상 승인 operation은 merge 1건, audit/Registry `valid`, Graph metadata 오류 없음이었다.

## 정상 경로 및 실제 dry-run

- 실제 raw manifest는 55개, trusted projection은 49개, quarantine은 6개다.
- trusted projection과 lock hash는 `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`로 일치했다. raw 전체 hash가 다른 것은 lock 밖 6개가 원본에 남아 있기 때문이다.
- `scripts/ontology_review.py --apply --dry-run --base data/ontology/concepts.json --base-lock data/ontology/policies/base_manifest.lock.json` 결과: `status=quarantined`, `valid=false`, approval operations `0`, concept diffs `0`, `graph_rebuild_required=false`.
- quarantine IDs는 `cov.hair_loss`, `cond.age_related_hair_loss`, `cond.disease_related_hair_loss`, `cond.treatment_side_effect_hair_loss`, `cond.work_daily_life_impairment`, `cond.pay_nonpay_status`이며 pending correction artifact는 승인·적용하지 않았다.
- 변경된 production source/script에서 특정 질환·질문·concept ID 하드코딩, payout 판단, 자동 승인 범위 확대는 확인되지 않았다. policy는 field-group approval path를 선언하고, runtime properties는 explicit new-concept path에만 있다. 개발 자동 승인 대상은 policy의 low-risk type과 test/evidence/dev metadata 조건으로 제한된다.

## 검증 증거

- focused pytest: `147 passed, 1 warning`.
- stale/patch/Graph 표본 pytest: `13 passed, 43 deselected`.
- top-level drift/Graph metadata 표본 pytest: `4 passed, 54 deselected`.
- full pytest: `1085 passed, 3 warnings`.
- Node admin/Graph frontend: `24 passed, 0 failed`; `node --check frontend/js/modules/admin.js frontend/js/pages/admin.js` 통과.
- isolated frontend build: 성공. `app.min.js` hash `5d81416261d1545f43285811f0db9a0e04ab94fdb9947fc8c6626156bc2253de`, `graph-viz.min.js` hash `ad17e2fc878320c85c4c9f6f3ca0edf8fce5713ab25b988db47b7616ea7dd80e`.
- isolated Playwright write E2E: `1 passed (4.1s)`, 임시 DB·계정·로그·root와 loopback `18192`만 사용했다. 첫 preflight 실패는 존재하지 않는 standard-code 경로를 지정한 명령 오류였고, 실제 DB 경로로 재실행한 테스트는 통과했다.
- isolated `check_ontology_sync.py`: `RC=1`, quarantine 상태를 성공으로 오인하지 않았다.
- protected Graph read-only `check_graph_index.py` 및 `check_graph_vector_sync.py --limit 1`: 각각 `RC=1`, 새 ontology metadata 부재를 검출했다. protected `18080`에는 접근하지 않았다.

## 범위·운영 무결성

- isolated status는 정확히 40 paths: tracked 32개 수정 + untracked 8개 추가. staged 없음, `git diff --check` 통과.
- untracked artifact는 JSON/Markdown/Python/HTML 텍스트뿐이며 private-key marker, 임시 binary, review용 temp root/listener는 남지 않았다.
- protected HEAD와 `origin/master`는 모두 `fa8d734d643d18d6983447978de2210819717bc6`이다.
- protected hash는 raw ontology `c8cb89f0a5eb0749755441f0ffd0d9f06922542caa990e48050089fb2858b60e`, Graph `1c3da6a6f3a9a814163c655476d560b5ef3999b455a3ea5a3845175b7a1487d2`, standard-code DB `c8b830a8927023ccbeb24ea63f4868e9bd8a64f13a1d8d44efed5eb92168ce03`로 검토 전 증거와 일치한다.
- protected에는 기존 `insurance_chat.db-wal`·`insurance_chat.db-shm`만 untracked로 남아 보존됐다. 기존 uvicorn PID `3996005` 외 검토 프로세스나 isolated listener는 남지 않았다.
- 구현 파일 수정, candidate 승인/apply, active/provenance promotion, GraphDB rebuild/reindex, service restart, protected 운영 DB·계정·로그 쓰기, stage/commit/push/deploy는 수행하지 않았다.

## 후속 승인 게이트

이번 판정은 code promotion 준비 상태를 의미할 뿐 통합·push를 승인하지 않는다. 다음 단계는 별도 승인 하에 code promotion을 수행하고, 6개 ontology correction의 practitioner approval을 별도로 받은 뒤 active manifest/provenance, GraphDB/index, service 반영을 각각 검증하는 절차다. practitioner approval·active/Graph/index/service 운영 적용은 이번 code review와 분리한다.

REVIEW_TEAM_RELEASE_A_RUNTIME_ARTIFACT_SCHEMA_REREVIEW_COMPLETE
