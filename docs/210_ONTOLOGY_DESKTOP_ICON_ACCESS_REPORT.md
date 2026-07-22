# 210. Ontology Desktop Icon Access Report

작성일: 2026-06-10

## Summary

DGX 바탕화면의 `신한EZ손해보험 보상지원 AI 챗봇` 아이콘에서 온톨로지 실무자 승인 workflow를 수동으로도 진입할 수 있게 실행기 메뉴를 보강했다.

기존 구현은 승인 대기 후보가 있을 때만 LLM 선택 전에 `insurance-rag-ontology-review-gui`를 자동 실행했다. 승인 대기 후보가 0건이면 사용자가 데스크탑 아이콘을 눌러도 승인 기능에 직접 진입할 메뉴가 보이지 않았다.

## Changes

- `ops/bin/insurance-rag-desktop-launcher`
  - `--choices` 진단 출력에 `ontology|review|<pending_count>` 행을 추가했다.
  - LLM 선택창에 `온톨로지 승인 검토` 항목을 추가했다.
  - 메뉴에는 현재 승인 대기 건수를 함께 표시한다.
  - 사용자가 해당 항목을 선택하면 `insurance-rag-ontology-review-gui`를 실행한다.
  - 검토 UI 종료 후 기존 앱 실행 흐름으로 돌아온다.
  - 수동 검토 후 재진입할 때 동일 preflight가 반복되지 않도록 `INSURANCE_RAG_SKIP_ONTOLOGY_PREFLIGHT=1`을 한 번 사용한다.

## Preserved Guardrails

- 승인 대기 후보가 있으면 기존처럼 LLM 선택 전에 자동 preflight가 실행된다.
- 테스트 자동 승인은 `test_candidate=true` 후보만 대상으로 하는 기존 CLI/GUI guardrail을 변경하지 않았다.
- 운영 후보 자동 승인은 추가하지 않았다.
- GraphDB rebuild와 active manifest 적용 경로는 기존 `insurance-rag-ontology-review-gui` 및 `scripts/ontology_review.py` 흐름을 그대로 사용한다.

## Verification

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
bash -n ops/bin/insurance-rag-ontology-review-gui
python -m pytest tests/test_ontology_registry.py tests/test_ontology_manifest_merge.py tests/test_ontology_review_store.py -q
```

DGX 설치본 동기화 후 다음 명령도 확인한다.

```bash
bash -n /srv/ai-ops/bin/insurance-rag-desktop-launcher
/srv/ai-ops/bin/insurance-rag-ontology-review-gui --dry-run
```
