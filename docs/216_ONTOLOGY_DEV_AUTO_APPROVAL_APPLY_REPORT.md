# 216. Ontology Development Auto-Approval Apply Report

작성일: 2026-06-10

## Summary

개발 편의성을 위해 후보 추출 CLI에 테스트 후보 표시 옵션을 추가하고, DGX 메인 저장소에서 실제 후보 추출, 개발용 자동 승인, active manifest 적용, GraphDB rebuild, 앱 기동 검증까지 수행했다.

이번 작업은 개발 단계 검증용이다. 운영 후보 전체 자동 승인은 허용하지 않았고, 개발 자동 승인은 `test_candidate=true`, source evidence 존재, low risk, `codex_dev_review.decision=approve` 조건을 모두 통과한 후보에만 적용했다.

## Implemented

### 1. 테스트 후보 명시 옵션 추가

수정 파일:

- `scripts/extract_ontology_candidates.py`
- `tests/test_extract_ontology_candidates_cli.py`

추가 옵션:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --mark-test-candidates
```

동작:

- 추출된 후보의 `test_candidate`를 `true`로 표시한다.
- `properties.extraction.marked_test_candidate=true`를 기록한다.
- `test_candidate_reason="explicit --mark-test-candidates"`를 기록한다.
- 명령 출력에 `mark_test_candidates` 상태를 포함한다.

이 옵션은 개발자가 명시적으로 실행한 후보 배치만 개발 자동 승인 대상으로 올리기 위한 장치다. 정책 파일의 `auto_approval.require_test_candidate=true` 조건은 유지했다.

### 2. Base manifest alias conflict 처리 보강

수정 파일:

- `src/ontology/manifest_merge.py`
- `tests/test_ontology_manifest_merge.py`

`scripts/ontology_review.py --apply --rebuild-graph` 실행 중 기존 base manifest 내부 alias 충돌 때문에 적용이 중단되는 문제가 확인됐다.

기존 base manifest 안에 이미 존재하던 alias 충돌은 이번 후보 적용으로 새로 생긴 충돌이 아니므로 warning으로 낮췄다. 단, 후보가 관여한 alias 충돌은 계속 오류로 처리한다.

## DGX Execution

작업 경로:

```text
/srv/shared/projects/insurance-rag-chatbot
```

사전 백업:

```text
/tmp/ontology-dev-apply-backup-20260610-161451
```

후보 추출:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --limit 100 \
  --source-limit 2000 \
  --template-only \
  --validate-policies \
  --mark-test-candidates \
  --replace-existing
```

개발용 자동 승인:

```bash
.venv/bin/python scripts/ontology_review.py \
  --auto-approve-dev \
  --reviewer codex-dev-auto
```

운영 반영 및 GraphDB rebuild:

```bash
.venv/bin/python scripts/ontology_review.py \
  --apply \
  --rebuild-graph
```

## Apply Result

최종 review summary:

```json
{
  "applied": 1,
  "approved": 0,
  "held": 0,
  "pending": 28,
  "rejected": 0,
  "total": 29
}
```

적용된 후보:

```json
[
  {
    "candidate_id": "dev.cond.drunk_injury.bf3efa56fe56",
    "concept_id": "cond.drunk_injury",
    "canonical_name": "음주 후 상해",
    "candidate_aliases": ["중상해"],
    "test_candidate": true,
    "status": "applied"
  }
]
```

적용 결과:

- `data/ontology/concepts.json` 직접 수정 없음
- `data/ontology/concepts.active.json` 생성/갱신
- `insurance_graph.sqlite` rebuild 완료
- 지급/면책/감액/보험금 계산 rule 후보 승인 없음
- 개발 자동 승인 가능한 후보 1건만 active manifest에 병합

## GraphDB Rebuild

GraphDB rebuild 중 SQLite sidecar 파일 소유권 문제로 1차 재시도에서 다음 오류가 발생했다.

```text
sqlite3.OperationalError: attempt to write a readonly database
```

원인:

- `insurance_graph.sqlite` 본체는 현재 작업 계정 소유였으나, 기존 `-shm`, `-wal` sidecar 파일이 다른 사용자 소유로 남아 있었다.

조치:

```text
data/index/graph/backups/rebuild-retry-20260610-161745/
```

기존 GraphDB 파일과 sidecar 파일을 위 백업 경로로 이동한 뒤 rebuild를 재실행했다.

재빌드 후 GraphDB 카운트:

```json
{
  "graph_nodes": 545223,
  "graph_edges": 46241,
  "graph_aliases": 528204,
  "graph_evidence": 27015
}
```

## Warnings

적용 과정에서 base manifest에 이미 존재하던 alias 충돌이 warning으로 보고됐다.

대표 warning:

- `검진 목적`: `cov.health_check`, `cond.preventive_purpose`
- `건강검진`: `cov.health_check`, `cond.preventive_purpose`
- `자동차보험`: `cov.auto_insurance`, `cond.other_insurance_payment`
- `산재보험`: `cov.workers_compensation`, `cond.other_insurance_payment`
- `치료 목적`: `cond.treatment_purpose`, `cond.treatment_purpose_check`
- `세부내역서`: `cond.detail_statement_check`, `evidence.detail_statement`
- `진단서`: `cond.diagnosis_certificate_check`, `evidence.diagnosis_certificate`

이 warning은 이번 개발 후보가 새로 만든 충돌이 아니라 기존 base manifest 정합성 이슈다. 별도 정리 작업에서 canonical concept, evidence concept, condition concept 사이의 alias 소유권을 재정리하는 것이 좋다.

## App Startup Validation

GraphDB rebuild 후 앱 기동 검증을 수행했다.

기존 앱 상태 확인:

```text
api_health: ok
api_models: ok
graph_db: ok
```

LLM 서버 상태를 불필요하게 변경하지 않기 위해 최종 앱 재기동은 다음 명령으로 수행했다.

```bash
ops/bin/insurance-rag-up --replace --no-llm-switch
```

결과:

```text
app ready: http://127.0.0.1:18080
api_health: ok
api_models: ok
graph_db: ok
curl /api/health: {"status":"ok"}
```

앱 로그:

```text
logs/fastapi_20260610_162341.log
```

## Verification

로컬 검증:

```bash
python -m pytest \
  tests/test_extract_ontology_candidates_cli.py \
  tests/test_ontology_policy.py \
  tests/test_ontology_candidate_extractor.py \
  tests/test_ontology_candidate_reviewer.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  -q
```

결과:

```text
29 passed
30 passed after manifest merge warning test addition
```

DGX 검증:

```bash
.venv/bin/python -m pytest \
  tests/test_extract_ontology_candidates_cli.py \
  tests/test_ontology_policy.py \
  tests/test_ontology_candidate_extractor.py \
  tests/test_ontology_candidate_reviewer.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  -q
```

결과:

```text
30 passed
```

DGX runtime 검증:

```bash
.venv/bin/python scripts/ontology_review.py --summary
ops/bin/insurance-rag-status
curl -s http://127.0.0.1:18080/api/health
```

결과:

```text
applied: 1
pending: 28
api_health: ok
api_models: ok
graph_db: ok
{"status":"ok"}
```

## Commits

DGX 메인 저장소와 GitHub `master`에 반영된 구현 커밋:

```text
336d997 feat(ontology): allow marking extracted candidates as tests
595f7fa fix(ontology): allow base alias conflict warnings
```

## Remaining Work

- base manifest 내부 alias 충돌 정리
- pending 28건 후보의 hold 사유 재검토
- 테스트 후보 자동 승인 정책을 운영 후보 정책과 분리해 UI에서 더 명확하게 표시
- 앱 질의 레벨에서 `중상해` alias가 `cond.drunk_injury` retrieval에 기대한 방식으로 작동하는지 기능 테스트
