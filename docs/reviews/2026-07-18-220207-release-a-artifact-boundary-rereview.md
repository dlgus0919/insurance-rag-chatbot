# Release A artifact-boundary fixback 독립 재검토

- 검토 시각: 2026-07-18 22:02 KST
- 검토 유형: Review Team 독립 read-only re-review
- Developer marker: `DEVELOPER_RELEASE_A_ARTIFACT_BOUNDARY_FIXBACK_READY_FOR_REVIEW`
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- protected main: `/srv/shared/projects/insurance-rag-chatbot`
- expected base: `fa8d734d643d18d6983447978de2210819717bc6`
- 최종 판정: **CHANGES_REQUESTED**

## Findings

### [P1] manifest와 provenance의 schema 경계가 runtime audit에서 fail-open임

`src/ontology/approval_integrity.py:35-43`의 `manifest_content_hash()`는
`schema_version`, `description`, `concepts`만 hash하고 `version` 외의 top-level
field를 모두 무시한다. 동시에 `src/ontology/registry.py:230-238`의 manifest
loader는 object와 `concepts` list만 확인하며 manifest schema를 검증하지 않는다.
`src/ontology/approval_integrity.py:884-910`의 active audit도 provenance
`schema_version`이나 unknown top-level field를 검사하지 않는다.

독립 재현:

```text
active에 rogue top-level field 추가 + active hash 재계산 -> audit valid, issues={}
동일 active를 OntologyRegistry로 로드              -> state=valid, concepts=1
base에 rogue top-level field 추가                  -> projection valid, issues={}
provenance schema_version=0/누락/unknown field     -> audit valid, issues={}
```

동일 payload는 `validate_manifest_schema()`에서는 거부됐다. 즉 merge/CLI의
일부 schema 검증만으로는 충분하지 않고, runtime registry와 direct audit가
승인되지 않은 manifest/provenance artifact를 노출할 수 있다. canonical hash는
생성 version만 제외한 전체 manifest content를 반영하고, base/active runtime
load와 audit에서 manifest schema 및 provenance schema/필수 구조를 fail-closed로
검증해야 한다. provenance hash를 새 값으로 다시 계산한 경우도 포함하는 회귀
테스트가 필요하다.

### [P2] BaseManifestLock이 부분적으로 손상된 concept hash entry를 조용히 제거함

`src/ontology/approval_integrity.py:101-121`의 `BaseManifestLock.from_dict()`는
`concept_hashes` comprehension에서 빈 concept ID/hash entry를 필터링한다.
유효 entry가 하나라도 남으면 `validate()`를 통과하므로, 손상된 lock이 원래
선언한 concept set과 다른 lock으로 수용된다.

독립 재현:

```text
valid lock + concept_hashes["cond.bad"] = ""
-> BaseManifestLock.from_dict() accepted, concept_hashes count=1
```

모든 lock row는 원형을 보존해 검증하고, 하나라도 비문자열·빈 key·빈 hash이면
전체 lock을 거부해야 한다. `schema=0`, 누락 source metadata, 빈 concept hash
전체는 이번 fixback에서 거부됐지만, 유효 row와 malformed row를 섞은 경우는
아직 닫히지 않았다.

## 이전 CHANGES_REQUESTED 재현 결과

- active `description` drift와 `schema_version` drift에 provenance active hash를
  재계산해도 `state=stale`, issue
  `UNAPPROVED_ACTIVE_MANIFEST_METADATA_DELTA`, Registry `0 concepts`.
- BaseManifestLock schema 0 및 source metadata 누락: `ValueError`.
- ApprovalPatch schema 0, reviewer/reviewed_at 누락, malformed row, empty
  operation: `ApprovalPatchError` 또는 `ValueError`.
- 직접 변조한 in-memory patch의 schema/reviewer/time/empty operation:
  merge 직전 `ApprovalPatchError`, active 파일 미생성.
- expected provenance hash가 빈 문자열이어도 Graph required key 누락:
  `ontology_provenance_content_hash: expected <empty>, got <missing>`.
- 정상 승인 operation: merge 1건, Registry `valid/1`, Graph metadata 오류 없음.

## 비회귀 및 범위 검토

- 실제 raw manifest 55개, trusted 49개, quarantine 6개.
- trusted projection/lock hash:
  `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`.
- 실제 dry-run: `status=quarantined`, `valid=false`, approval operations `0`,
  manifest diffs `0`, Graph rebuild `false`.
- quarantine은 6개 concept에 한정됐고 trusted 49개가 전역 outage로 차단되지
  않았다.
- evidence-tag 정상 승인은 candidate control metadata를 runtime으로 복사하지
  않고 명시된 field path만 적용한다. stale candidate/evidence/base와 unsupported
  path 거부 회귀도 유지됐다.
- 전체 39 paths는 tracked 32개 수정 + untracked 7개 추가이며 기준 커밋 대비
  `2367 insertions, 410 deletions`이다. 변경된 production source/script에는
  특정 질환·질문·concept ID hardcoding이 없고, review policy는 approval path만
  정의한다.
- `runtime_properties`는 자동 승인 path에서 제외되고, 관리자 UI는 bounded
  approval operation만 표시한다. active/provenance/Graph promotion 범위를
  확장하는 변경은 확인되지 않았다.

## 검증 증거

- focused pytest: `126 passed, 1 warning`.
- full pytest: `1064 passed, 3 warnings`.
- Node admin regression: `15 passed, 0 failed`; frontend 두 JS 파일
  `node --check` 통과.
- isolated frontend build: 성공. 임시 checkout에서 기존 read-only
  dependency만 참조했으며 target dist hash도 build 결과와 일치했다.
- isolated Playwright write E2E: 임시 DB/계정/로그/root, loopback port `18191`에서
  `1 passed`. 최초 실행의 임시 username이 32자 제한을 넘어 runner preflight에서
  중단된 뒤, 유효한 임시 계정으로 재실행했다. protected target에는 접근하지
  않았다.
- protected `18080`에는 요청하지 않았다. access log 영향이 있는 GET smoke는
  이번 검토에 필요하지 않아 생략했다.
- `check_ontology_sync.py`: RC 1, current raw registry quarantine 상태.
- protected Graph read-only `check_graph_index.py`: RC 1, 새 ontology metadata
  없는 기존 Graph를 차단.
- protected Graph read-only `check_graph_vector_sync.py`: RC 1, 동일 metadata
  mismatch를 차단.

## 운영 및 Git 경계

- `git diff --check` 통과, staged diff 없음, status는 정확히 39 paths.
- private-key marker 없음, 새 파일은 텍스트/JSON/Python/HTML이며 binary 없음.
- protected HEAD와 `origin/master`는 모두
  `fa8d734d643d18d6983447978de2210819717bc6`.
- protected에는 기존 `insurance_chat.db-wal` 및 `insurance_chat.db-shm`만
  untracked로 남아 있으며 보존했다.
- protected raw ontology hash:
  `c8cb89f0a5eb0749755441f0ffd0d9f06922542caa990e48050089fb2858b60e`.
- protected Graph hash:
  `1c3da6a6f3a9a814163c655476d560b5ef3999b455a3ea5a3845175b7a1487d2`.
- protected standard-code DB hash:
  `c8b830a8927023ccbeb24ea63f4868e9bd8a64f13a1d8d44efed5eb92168ce03`.
- 실행 종료 후 pytest/Playwright/build/ontology 작업 프로세스는 남지 않았고
  기존 protected uvicorn만 유지됐다. 제가 만든 review용 `/tmp/release-a-*`
  lock과 임시 directory는 정리했으며, 공용 lock 파일은 건드리지 않았다.
- 구현 파일 수정, candidate 승인/apply, active/provenance promotion,
  GraphDB rebuild, reindex, 서비스 재시작, protected 운영 데이터/계정/로그
  쓰기, stage/commit/push/deploy는 수행하지 않았다.

## 최소 Developer fixback prompt

```text
Review Team 재검토 결과는 CHANGES_REQUESTED입니다. 기존 Release A 격리
workspace에서 아래 두 항목만 최소 수정하고 active/Graph/candidate에는 적용하지
마십시오.

1. manifest_content_hash가 생성 version만 제외한 전체 manifest content를
   반영하게 하십시오. registry runtime load와 audit_active_manifest에서
   ontology manifest schema를 검증하고, provenance schema_version=1 및 required
   fields/rows를 검증하여 unknown top-level field, provenance schema 0/누락이
   recomputed hash와 함께 valid로 통과하지 않게 하십시오.
2. BaseManifestLock.from_dict()는 concept_hashes의 모든 row를 검증하십시오.
   유효 row와 malformed/empty/non-string row를 섞어도 해당 전체 lock을
   거부해야 하며, malformed row를 silently filter하지 마십시오.

회귀 테스트:
- active/base rogue top-level field + recomputed active hash -> stale/Registry 0
- provenance schema 0/누락/unknown artifact -> fail-closed
- valid+empty 또는 valid+non-string lock concept hash row -> parse reject
- 기존 active drift, ApprovalPatch malformed/in-memory, Graph missing-key,
  valid merge, raw 55/trusted 49/quarantine 6, approval operation 0/diff 0 유지

도메인 하드코딩, 자동 승인 확대, active/Graph promotion은 금지하십시오.
focused/full pytest, Node/admin, frontend build, isolated Playwright를 재실행하고
결과만 보고하십시오. protected 18080에는 쓰기 요청을 보내지 말고, candidate
apply, reindex, GraphDB rebuild, service restart, commit, push도 하지 마십시오.
```

이번 판정은 위 두 fixback과 재검토가 완료될 때까지 승격을 차단한다. 이후 PASS가
되더라도 code promotion은 별도 승인으로 진행해야 하며, 6개 ontology correction의
practitioner approval, active/provenance 적용, Graph 운영 반영, index 재생성,
서비스 smoke는 서로 분리된 운영 게이트로 유지해야 한다.

REVIEW_TEAM_RELEASE_A_ARTIFACT_BOUNDARY_REREVIEW_COMPLETE
