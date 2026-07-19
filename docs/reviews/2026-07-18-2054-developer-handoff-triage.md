# Developer Handoff Triage — Release A Approval Artifact Boundary Fixback

- Timestamp: 2026-07-18 20:54 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Scope/spec: Release A ontology approval integrity and operational containment
- Isolated DGX workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- Base/protected expected: `fa8d734d643d18d6983447978de2210819717bc6`
- Review report: `docs/reviews/2026-07-18-204719-release-a-approval-integrity-review.md`

## Reported

- Review Team completed an independent read-only review and returned `CHANGES_REQUESTED`.
- The previous base-projection whole-manifest drift finding is closed and the 49 trusted/6 quarantined behavior remains correct.
- Review Team independently reproduced three remaining integrity-boundary defects:
  1. active-only top-level manifest drift passes when provenance active hash is recomputed;
  2. base lock and ApprovalPatch schema/provenance fields are insufficiently validated;
  3. a required Graph metadata key can be absent when its expected value is an empty string.
- Review Team reports focused `59 passed`, full pytest `1038 passed, 3 warnings`, Node/admin passing, frontend build passing in an isolated copy, and isolated Playwright `1 passed`.
- Review Team reports no implementation edit, protected request, candidate apply, Graph rebuild, reindex, restart, commit, or push.

## Observed

- Review Team thread is idle and its latest completed turn matches the project cwd.
- The immutable review report exists and provides exact source ranges, independent probes, verification counts, and a ready-to-send bounded fixback.
- Planner independently reproduced all three findings against the live isolated workspace:
  - active `description` drift plus recomputed provenance active hash returns `state=valid`, `issues=[]`;
  - `BaseManifestLock` accepts `schema_version=0`;
  - `ApprovalPatch` accepts `schema_version=0`, empty reviewer, and empty reviewed_at, and its operation passes merge prevalidation;
  - removing `ontology_provenance_content_hash` when the expected value is empty returns no Graph integrity error.
- The isolated workspace still has exactly 39 intended status paths, no staged diff, and `git diff --check` passes.
- Protected code/data was not changed during Planner reproduction.

## Not Verified

- Planner did not repeat Review Team's full pytest, Node, frontend build, or Playwright execution because the reported defects were independently reproducible with focused in-memory probes and already block promotion.
- No operational active manifest, GraphDB, index, or service migration has been attempted; this remains explicitly prohibited.

## Findings

### P1 — active-only top-level semantic drift is not represented in the approval delta contract

`audit_active_manifest()` verifies the active content hash against provenance and concept-level semantic operations, but it does not compare trusted base and active `schema_version`/`description`. Updating the provenance active hash together with the drift therefore makes an unapproved top-level change appear valid. Add explicit top-level semantic diff enforcement and fail closed even when hashes are internally consistent.

### P1 — lock and ApprovalPatch parsing/application accept unsupported or unaccountable artifacts

Supported schema version `1` is not required, mandatory reviewer/source metadata can be empty, malformed list entries are silently filtered, and merge prevalidation does not reassert these invariants. Reject malformed artifacts at parse time and revalidate before merge/apply so an in-memory or alternate caller cannot bypass parsing.

### P2 — required Graph metadata key absence is conflated with an expected empty value

`manifest.get(key) or ""` makes a missing key indistinguishable from a present empty string. Check required key presence first, then compare the value.

## Decision

`DEVELOPER_FIXBACK`

Promotion, Review Team re-routing, and operational migration remain blocked until these three bounded defects are fixed and re-reviewed.

## Dispatch

- Target thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Prompt sent:

```text
Review Team 재검토 결과는 CHANGES_REQUESTED이며 Planner도 세 결함을 독립 재현했습니다. 기존 Release A 격리 작업공간에서만 최소 수정하십시오.

권위 기록:
- /Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-18-204719-release-a-approval-integrity-review.md
- /Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-18-2054-developer-handoff-triage.md

작업공간/기준:
- /srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718
- fa8d734d643d18d6983447978de2210819717bc6

필수 수정:
1. audit_active_manifest가 trusted base와 active manifest의 schema_version 및 description 차이를 명시적으로 검사하게 하십시오. provenance.active_content_hash를 drifted active 값으로 다시 맞춘 경우에도 승인 operation 없는 변경은 전용 issue와 stale 상태가 되어야 하며, active OntologyRegistry는 concept를 노출하지 않아야 합니다.
2. BaseManifestLock과 ApprovalPatch는 지원 schema_version 1만 허용하십시오. BaseManifestLock의 manifest_content_hash, source_commit, review_record_id와 ApprovalPatch의 candidate/base hashes, reviewer, reviewed_at은 non-empty여야 합니다. allowed_operations 및 approved_evidence 배열의 non-object 원소를 조용히 버리지 말고 거부하십시오. empty allowed_operations는 parse 또는 apply 경계에서 일관되게 거부하십시오.
3. merge/apply 직전에도 ApprovalPatch invariant를 재검증하여 직접 생성된 in-memory artifact가 parse 검증을 우회하지 못하게 하십시오. schema 0, 빈 reviewer/time, malformed row, stale candidate/evidence/base, unsupported path가 모두 적용 전에 차단되는 회귀를 추가하십시오.
4. graph_manifest_integrity_errors는 모든 required metadata key의 존재를 먼저 확인하고 그 뒤 값을 비교하십시오. expected ontology_provenance_content_hash가 빈 문자열이어도 key 누락은 오류여야 합니다.
5. 기존 계약을 보존하십시오: raw 55개 중 trusted 49개/extra untrusted 6개 quarantine, base top-level drift stale, 승인 operation 0/diff 0 dry-run, 자동 승인 제한, pending correction 미적용.
6. 특정 질환·질문·concept ID 하드코딩이나 승인 범위 확대는 금지합니다.

실패 우선 테스트:
- active description/schema_version drift + recomputed provenance hash -> stale, Registry 0 concepts
- lock schema 0/누락 metadata -> parse/load reject
- patch schema 0/빈 reviewer/빈 reviewed_at/malformed list row/empty operations -> parse 또는 apply reject
- 직접 생성한 invalid patch -> merge prevalidation reject
- required Graph metadata key missing with expected empty value -> integrity error
- 기존 49/6 quarantine 및 valid approved operation 비회귀

검증:
- approval-integrity/review-store/merge/registry/Graph/API focused tests
- 전체 pytest
- Node/admin와 frontend build
- 임시 DB·계정·포트만 사용하는 isolated Playwright
- 실제 correction dry-run, git diff --check, 비밀·임시 산출물 및 protected boundary 점검
- docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md에 원인·수정·red→green·정확한 수치를 추가

금지:
- active/candidate apply 또는 승인
- GraphDB rebuild/reindex
- API/LLM/service restart
- protected-main 수정
- stage/commit/push
- Release B 착수

변경은 기존 isolated workspace에 unstaged/uncommitted로 유지하십시오. 성공 시 정확한 파일과 검증 수치를 보고하고 마지막 줄을 다음으로 끝내십시오:
DEVELOPER_RELEASE_A_ARTIFACT_BOUNDARY_FIXBACK_READY_FOR_REVIEW
```
