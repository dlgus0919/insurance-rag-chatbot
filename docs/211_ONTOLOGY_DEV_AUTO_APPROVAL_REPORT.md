# 211. Ontology Development Auto Approval Report

작성일: 2026-06-10

## Summary

개발 단계에서 DB/GraphDB/ontology 로직을 반복 검증할 때 매번 실무자 승인 UI를 거치지 않아도 되도록, 운영 승인과 분리된 `Codex 개발용 자동 승인` 경로를 추가했다.

이 기능은 운영 실무 승인 대체가 아니라 개발 검증용이다. 기본값은 비활성화이며, `ENABLE_ONTOLOGY_DEV_AUTO_APPROVAL=true`가 설정된 경우에만 DGX GUI에서 실행된다.

## Auto Approval Criteria

`--auto-approve-dev`는 다음 조건을 모두 만족하는 pending 후보만 승인한다.

- `status == "pending"`
- `risk_flags`에 `dev_only` 또는 `dev_auto_approval` 포함
- `source_evidence`가 1개 이상 존재
- `properties.codex_dev_review.decision == "approve"`
- `properties.codex_dev_review.development_only == true`
- `properties.codex_dev_review.domain_fit == true`
- `properties.codex_dev_review.evidence_fit == true`
- `properties.codex_dev_review.risk_level`이 `low` 또는 `dev_only`

승인 로그는 다음 값으로 남긴다.

- `reviewer`: `codex-dev-auto`
- `reviewer_type`: `codex_dev_auto`
- `reason`: `codex development-only domain review auto approval`

## User Flow

DGX 바탕화면 아이콘에서 `온톨로지 승인 검토`를 선택한 뒤, pending 후보가 있을 때 `개발 후보 Codex 자동 승인`을 선택할 수 있다.

실행 전 환경변수:

```bash
ENABLE_ONTOLOGY_DEV_AUTO_APPROVAL=true
```

CLI 검증:

```bash
.venv/bin/python scripts/ontology_review.py --auto-approve-dev --dry-run
.venv/bin/python scripts/ontology_review.py --auto-approve-dev --reviewer codex-dev-auto
.venv/bin/python scripts/ontology_review.py --apply --rebuild-graph
```

## Guardrails

- 기존 `test_candidate=true` 테스트 자동 승인 경로는 변경하지 않았다.
- 운영 후보 전체 자동 승인은 추가하지 않았다.
- `codex_dev_review` metadata 없이 단순히 `risk_flags`만 있는 후보는 자동 승인하지 않는다.
- 개발 자동 승인은 환경변수로 명시 활성화해야 GUI에서 실행된다.

## Verification

```bash
bash -n ops/bin/insurance-rag-desktop-launcher ops/bin/insurance-rag-ontology-review-gui
python -m pytest tests/test_ontology_registry.py tests/test_ontology_manifest_merge.py tests/test_ontology_review_store.py -q
python scripts/ontology_review.py --auto-approve-dev --dry-run
```
