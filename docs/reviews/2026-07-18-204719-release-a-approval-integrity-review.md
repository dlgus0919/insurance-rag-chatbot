# Release A 온톨로지 승인 무결성 독립 검토

- 검토 시각: 2026-07-18 20:47 KST
- 검토 유형: Review Team 독립 read-only review
- 대상 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- protected main: `/srv/shared/projects/insurance-rag-chatbot`
- 기준 커밋: `fa8d734d643d18d6983447978de2210819717bc6`
- Developer marker: `DEVELOPER_RELEASE_A_FIXBACK_READY_FOR_REVIEW`
- 판정: **CHANGES_REQUESTED**

## Findings

### [P1] active manifest의 상위 필드 변경이 provenance를 함께 갱신하면 유효 상태로 통과함

`src/ontology/approval_integrity.py:707-811`의 `manifest_semantic_diffs()`는
concept 내부 필드만 비교한다. `schema_version`과 `description`은
`manifest_content_hash()`에는 포함되지만 `audit_active_manifest()`의 실제 delta
검사는 `:875-909`의 concept operation 집합에만 적용된다. 따라서 active
manifest의 상위 필드를 바꾸고 `provenance.active_content_hash`도 그 값으로
갱신하면 base lock, provenance, hash가 서로 일관된 것으로 보인다.

독립 재현 결과:

```text
active description 변경 + provenance active hash 재계산 -> audit state=valid, issues={}
active schema_version 변경 + provenance active hash 재계산 -> audit state=valid, issues={}
동일 fixture의 OntologyRegistry -> state=valid, concepts=1
```

기대 결과는 승인 operation이 없는 상위 필드 변경을 `stale` 또는 명시적인
무결성 실패로 처리하고 runtime projection을 노출하지 않는 것이다. trusted
base와 active의 `schema_version`/`description`도 비교하는 최소 검증을 추가하고,
provenance hash를 내부적으로 맞춘 경우를 포함하는 회귀 테스트가 필요하다.

### [P1] lock과 ApprovalPatch의 schema 및 승인자 필수값 검증이 fail-open임

`src/ontology/approval_integrity.py:83-101`은 유효한 content hash와 concept
hash가 있으면 lock의 `schema_version`이 0이거나 누락되어도 객체를 생성한다.
`src/ontology/approval_integrity.py:235-264`도 ApprovalPatch의 schema 0,
빈 `reviewer`, 빈 `reviewed_at`을 허용하고, list 안의 non-object 행을 조용히
버린다. `src/ontology/manifest_merge.py:219-261`의 적용 전 재검증에는
patch schema, reviewer, reviewed_at 검사가 없다.

독립 boundary probe 결과:

```text
lock schema=0 + valid hash                 -> state=valid
lock schema_version 누락 + valid hash      -> state=valid
patch schema=0 + 유효 operation            -> accepted; merge 적용
patch reviewer 누락                        -> accepted
patch reviewed_at 누락                     -> accepted
non-object operation 행                    -> 조용히 필터링
```

이는 승인 산출물의 버전·책임 추적 계약을 우회한다. 최소 수정은 lock과 patch에
지원 schema version을 정확히 요구하고, source/review record/reviewer/reviewed_at
필수값을 비어 있지 않게 검증하며, malformed list 원소를 필터링하지 않고 거부하는
것이다. merge 직전에도 같은 invariant를 재검증하고, empty operation은 parse 또는
apply 단계에서 일관되게 거부해야 한다. schema 0, 누락 필드, malformed row가
적용되지 않는 회귀 테스트를 추가해야 한다.

### [P2] expected 값이 빈 문자열일 때 Graph manifest의 필드 누락을 검출하지 못함

`src/ontology/registry.py:567-575`는 `manifest.get(key) or ""`로 비교한다.
따라서 registry가 provenance hash를 아직 가지지 않는 상태에서 기대값이 빈
문자열이면 `ontology_provenance_content_hash` key 자체가 없어도 정상으로
처리된다.

독립 재현 결과:

```text
expected ontology_provenance_content_hash=""
manifest에서 해당 key 삭제
graph_manifest_integrity_errors() -> []
```

메타데이터 계약은 값이 빈 문자열인 경우와 key가 없는 경우를 구분해야 한다.
모든 required Graph metadata key의 존재 여부를 먼저 확인하고, 그 뒤에 실제
값을 비교하는 최소 수정과 누락 key 회귀 테스트가 필요하다.

## 독립 검증 증거

### 변경 범위와 상태

- 기준 커밋 대비 `git diff --stat`: tracked 32개 수정, untracked 7개 추가,
  `2228 insertions, 410 deletions`; Developer 보고서의 39 paths와 일치한다.
- `git diff --check`: 통과.
- `git diff --cached --quiet`: 통과, staging 없음.
- 새 파일은 JSON, Python, Markdown, HTML 텍스트였고 private-key marker는
  검출되지 않았다. binary 산출물은 없었다.
- 변경된 source/script에서 특정 탈모·질환·질문·concept ID 분기는 확인되지
  않았다. 변경은 generic ontology/approval/registry/Graph 경계에 한정된다.

### 계획·보고서와의 대조

Developer 보고서 `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md:101-120`은
whole-manifest lock fixback, 49 retained/6 quarantined, approval operation 0,
manifest diff 0, full pytest 1038 passed를 보고한다. 아래 결과로 이 수치와
raw quarantine 결과는 재현했지만, 보고서의 P1 회귀는 base projection drift만
검증하며 위 active top-level drift와 malformed approval artifact를 다루지
않았다. 따라서 보고서의 운영 비변경 주장은 확인하되, 구현 PASS로 승격하지
않는다.

### 무결성 및 비회귀 재현

- 실제 raw `concepts.json`: 55개.
- base lock trusted: 49개.
- trusted projection: 49개.
- 개별 quarantine: 6개.
- projection hash와 lock hash: 둘 다
  `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`.
- 실제 dry-run: `status=quarantined`, `applied_operations=[]`,
  `concept_diffs=[]`, `valid=false`, `graph_rebuild_required=false`.
- registry 독립 확인: `state=quarantined`, `concepts=49`, `quarantined=6`.
  전역 outage로 확대되지 않았다.
- locked mutation/missing, stale candidate/evidence/base, unsupported path는
  모두 stale/reject로 재현됐다.
- empty base lock 및 empty concept hash는 거부됐다. 위 Findings는 거부되지
  않은 version/metadata 변형에 한정한다.

### 테스트 및 실행 경계

- focused pytest: `59 passed`.
- full pytest: `1038 passed, 3 warnings`.
- Node admin regression: `15 passed, 0 failed`; 변경 frontend 두 파일
  `node --check` 통과.
- frontend build: 격리 `/tmp` checkout에서 기존 read-only dependency를
  참조하여 성공. 대상 checkout의 build 산출물은 추가 변경되지 않았다.
- isolated Playwright write E2E: 임시 root, 임시 DB/계정, port `18191`에서
  `1 passed`.
- protected `18080`에는 요청을 보내지 않았다. access log 영향을 피하기 위해
  GET-only smoke가 꼭 필요하지 않은 이번 검토에서는 생략했다.
- protected Graph/DB read-only check는 수행했으며, new ontology metadata가
  아직 없는 기존 Graph가 예상대로 non-zero를 반환했다. GraphStore는 readonly
  URI로 열었다.
- 테스트·build·E2E 후에도 실행 중인 프로세스는 기존 protected uvicorn
  `3996005`뿐이었다. 서비스 재시작은 하지 않았다.

### protected main 및 운영 데이터

- protected HEAD와 `origin/master`: 모두
  `fa8d734d643d18d6983447978de2210819717bc6`.
- protected의 기존 untracked는 `insurance_chat.db-wal`과
  `insurance_chat.db-shm`뿐이며, 삭제·checkpoint·rename하지 않았다.
- active ontology, active provenance, review log, GraphDB, index, 운영 DB,
  사용자, 서비스에는 쓰기하지 않았다.
- candidate 승인/apply, active promotion, GraphDB rebuild, reindex,
  commit, push는 수행하지 않았다.

## 바로 전달할 Developer fixback prompt

```text
Review Team 재검토 결과 CHANGES_REQUESTED입니다. 구현은 격리 작업공간에서만
최소 수정하고 active/Graph/candidate에는 적용하지 마십시오.

1. BaseManifestLock과 ApprovalPatch의 schema_version을 지원 버전 1로 정확히
   제한하십시오. source_commit, review_record_id, reviewer, reviewed_at을
   필수 non-empty로 검증하고, malformed list 원소를 silently filter하지 말고
   거부하십시오. empty allowed_operations도 parse/apply 경계에서 명확히
   거부하고 merge 직전 invariant를 재검증하십시오. schema=0/누락 metadata가
   적용되지 않는 회귀 테스트를 추가하십시오.
2. audit_active_manifest가 trusted base와 active manifest의 top-level
   schema_version/description 차이를 검사하게 하십시오. provenance의
   active_content_hash를 새 active 값으로 맞춘 경우에도 승인 operation 없는
   변경은 stale/fail-closed가 되어 Registry가 runtime concept를 노출하지
   않아야 합니다. 이 경우를 포함한 회귀 테스트를 추가하십시오.
3. graph_manifest_integrity_errors는 expected 값이 빈 문자열이어도 required
   key 누락을 오류로 처리하십시오. ontology_provenance_content_hash 누락
   회귀 테스트를 추가하십시오.

도메인 특정 하드코딩, 자동 승인 범위 확대, active/Graph promotion은 금지합니다.
focused/full pytest, Node/admin, frontend build, isolated Playwright를 재실행하고
결과만 보고하십시오. protected 18080에는 쓰기 요청을 보내지 말고, candidate
승인/apply·reindex·GraphDB rebuild·service restart·commit·push를 하지 마십시오.
```

## 후속 게이트와 잔여 위험

위 세 항목의 fixback과 독립 재검토가 먼저 필요하다. 그 다음에도 현재 6개
concept는 practitioner approval 전까지 quarantine 상태로 유지해야 한다.
PASS 이후에만 개발 검토 승인, 운영 실무자 승인, active manifest/provenance의
원자 적용, Graph metadata 확인, Graph/index 재생성, 서비스 smoke를 각각 분리된
승인 단계로 진행해야 한다. 이번 보고서는 해당 운영 승인을 대신하지 않는다.

본 문서는 기존 triage와 Developer 보고서를 수정하지 않고 현재 검토 시각에 새로
작성한 단일 Review Team 기록이다. 이 검토에서 구현 변경은 수행하지 않았다.
