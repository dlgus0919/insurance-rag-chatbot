# Grounded Attribute and Composite Quick-Code Implementation Report

## Scope

- Remote candidate worktree: `/srv/shared/workspaces/muldae/insurance-rag-grounded-attribute-composite-20260721`
- Candidate branch: `codex/grounded-attribute-composite-quickcode-20260721`
- Base: `ba214dac5bd3aaba0361db2bad5eed508a794c79`
- Protected runtime repository: not modified.

## Implemented contracts

1. Direct policy attributes now retain the selected numeric value and category in hit metadata. The deterministic clause-detail path uses that value and its bounded raw display evidence instead of reparsing the wider OCR retrieval window. Multiple rows from one policy generation render as one answer rather than a false comparison.
2. A named procedure immediately before a fee cue is accepted as a HIRA lookup term only after the existing raw HIRA-row matcher validates it. The public `build_hira_fee_component()` helper reuses the existing raw-HIRA context and renderer.
3. For a question that requests both a fee code and a coverage judgment, a validated HIRA component is shown under `수가 정보`; the existing coverage disposition is retained unchanged under `실손 보상 판단`. No GraphDB candidate value, payout/exclusion conclusion, LLM, or calculation rule is used for that component.

## Changed files

- `src/rag/pipeline.py`
- `src/api/rag_service.py`
- `tests/test_pipeline.py`
- `tests/test_api_rag_service_payload.py`
- `tests/test_api_chat_stream.py`

## Verification

- `git diff --check` — passed.
- Focused regression: `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest -q tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py` — `173 passed`, warnings: 1 dependency deprecation warning.
- Full regression: `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest -q` — `1208 passed`, warnings: 3 dependency/Pillow deprecation warnings.
- Candidate raw-HIRA check: `식도조루술 수가 코드와 실손 보상 여부를 알려줘.` resolved `Q2333` from the raw HIRA chunk on p.531.
- Candidate direct-attribute check: a wide OCR context containing `3만원`, `350만원`, and a selected `300만원` rendered only `300만원`.

## Scope and unrun items

- No active calculation rule, GraphDB/ontology/raw data, prompt/model setting, frontend, reindex, rebuild, merge, commit, push, or service restart was performed.
- Chrome smoke against protected port 18080 was intentionally not run from this candidate. It requires a separate promotion/restart decision after independent review.
