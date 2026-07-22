# 259. Knowledge Intake Extension Stabilization Report

## Summary

관리자 문서 추가 기반 지식 확장 흐름에서 후보가 생성되었지만 승인 UI와 운영 apply 경로로 이어지지 않는 결점을 수정했다.

이번 변경은 신규 지식을 자동으로 운영 반영하지 않는다. 디지털 PDF에서 생성된 후보를 기존 전역 review store에 `pending` 상태로 게시하고, 실무자 승인 후 기존 apply 경로를 통해 active ontology/rule에 반영되도록 연결한다.

## Changes

- `src/ingest/intake_runner.py`
  - 디지털 PDF 후보 생성 후 job-local 후보를 전역 ontology/rule review JSONL로 게시한다.
  - 게시된 후보에 `intake_job_id`, `source_filename`, `staging_chunks_path`를 기록한다.
  - 동일 candidate id는 중복 게시하지 않고 skipped count로 기록한다.
  - 후보 추출 기준 ontology를 active manifest 우선으로 변경했다.
- `frontend/js/config.js`
  - 관리자 intake audit 상세 조회 endpoint base 누락을 수정했다.
- `src/ingest/file_intake_planner.py`
  - Excel intake plan을 현재 runtime과 맞춰 `excel_staging_not_ready`로 정리했다.
- `frontend/html/admin.html`
  - Excel이 후보 추출 가능한 것처럼 보이던 관리자 도움말을 수정했다.
- `tests/`
  - audit endpoint 상수 회귀 테스트를 추가했다.
  - intake 후보 전역 게시 및 중복 방지 테스트를 추가했다.
  - Excel staging 미연결 상태를 명시하는 planner 테스트를 갱신했다.
- `src/ingest/knowledge_apply.py`
  - 승인 후보 적용 전에 ontology/rule dry-run preflight를 실행한다.
  - preflight 실패 시 active manifest/rule/GraphDB mutation을 시작하지 않고 `failed_preflight`를 반환한다.

## Guardrail Check

- 신규 후보는 여전히 `pending` 상태로 시작한다.
- active ontology/rule manifest는 이번 intake 실행만으로 변경되지 않는다.
- 스캔 PDF/OCR 자동화는 추가하지 않았다.
- Excel은 후보 추출로 넘어가지 않고 현재 미지원 상태를 명확히 표시한다.
- 승인 후보 apply는 rule preflight 실패 시 GraphDB rebuild로 넘어가지 않는다.

## Validation

Local checkout:

```bash
python -m pytest tests/test_intake_runner.py tests/test_file_intake_planner.py -q
python -m pytest tests/test_knowledge_apply.py -q
node --test tests/test_admin_knowledge_frontend.mjs
```

Result:

- `13 passed`
- `2 passed`
- `9 passed`

Local API route tests were not run locally because the local Python environment does not include FastAPI. DGX validation is required for API route coverage.

## Remaining Work

- Source/index promotion: 업로드된 디지털 PDF 본문을 active searchable source/index로 승격하는 별도 단계를 설계하고 구현한다.
