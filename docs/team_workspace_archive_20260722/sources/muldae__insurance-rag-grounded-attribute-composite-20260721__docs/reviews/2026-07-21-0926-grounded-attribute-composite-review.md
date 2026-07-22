# Grounded Attribute and Composite Quick-Code Review

## Review Scope

- Candidate: `/srv/shared/workspaces/muldae/insurance-rag-grounded-attribute-composite-20260721`
- Candidate branch: `codex/grounded-attribute-composite-quickcode-20260721`
- Base: `ba214da`
- Review mode: independent read-only review. Protected runtime, active calculation rules, GraphDB/ontology, raw data, prompts, frontend, indexes, and services were not changed.

## Evidence and Verification

1. `git status --short` and working-tree diff show only the planned `pipeline`, `rag_service`, three test files, and the Developer completion record. `git diff --check` passed. No calculation-rule, GraphDB/ontology/raw-data, prompt/model, frontend, index, or service file is in scope.
2. Direct-attribute carry-through is present: `_direct_policy_attribute_hits()` records `direct_policy_attribute_value` and bounded `display_evidence`; `_extract_clause_detail_text_rows()` uses the recorded value instead of reparsing the wide OCR hit when those metadata fields are valid. The supplied regression prevents neighboring `3만원` and `350만원` from appearing in a `300만원` answer.
3. Fee composition uses `_build_hira_fee_context()` plus `build_hira_fee_answer()` and therefore needs a raw HIRA chunk match. The independent dynamic check returned a code for `식도조루술` and returned `None` for `없는조루술`; no LLM, GraphDB candidate value, `pay_opinion`, or default code was used. `dataclasses.replace()` retains the prior coverage disposition fields.
4. Independent test runs:
   - `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest -q tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py` — `173 passed`, 1 deprecation warning.
   - `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest -q` — `1208 passed`, 3 dependency/Pillow deprecation warnings.

## Finding

### P1 — A single-generation question can still be rendered as a 4th/5th comparison

`_build_clause_detail_evidence_answer()` now suppresses comparison only when the first two rows have the **same** `policy_generation`. It does not check whether the question explicitly requested multiple generations. Consequently, two valid direct rows from distinct generations still render a comparison even for a selected single-generation question.

Independent reproduction with a `4th=300만원` direct row and a `5th=200만원` direct row for `4세대 검사X의 연간 보상한도는?` returned:

```text
문서 근거상 보상한도/횟수/기간 기준 비교 결과입니다.
- 4세대: 300만원
- 5세대: 200만원
```

This violates the approved contract: comparison formatting is allowed only for an explicit request for distinct policy generations. Retrieval normally filters by the selected generation, but the deterministic renderer is a public defensive boundary and must not reinterpret extra retrieved evidence as a user-requested comparison.

The new test covers duplicate rows of the same generation but does not cover distinct-generation rows paired with a single-generation question. A small additional robustness case was also observed: `식도조루술은 수가 코드...` currently keeps the topic particle as part of the candidate, so it does not match the otherwise valid raw HIRA row. This is not the blocking safety finding, but should be covered if the fee-cue normalizer is being touched.

## Ready-to-send Developer Fixback

In the same isolated candidate only:

1. In `_build_clause_detail_evidence_answer()`, derive the requested generations using the existing `_requested_policy_generations(question, policy_generation)` contract. Render comparison only when that request contains two or more distinct generations **and** the chosen rows represent those distinct generations. For a selected single generation, choose only the matching row; do not rely solely on duplicate-generation suppression.
2. Add regressions with distinct 4th/5th direct rows showing that `4세대 ... 한도` renders only the 4th selected value, while an explicit `4세대와 5세대 비교` question still renders both. Preserve legacy direct-hit fallback.
3. Optionally in the same normalizer, strip common Korean topic/subject/object particles only from the trailing lookup candidate, then add a raw-HIRA validation test for `식도조루술은 수가 코드`. Do not add term-specific mappings.
4. Rerun the focused suite and `pytest -q`; update the Developer completion record. Do not stage, commit, push, merge, restart, rebuild, reindex, or touch protected runtime.

## Verdict

`CHANGES_REQUESTED`

The fee-plus-fail-closed-coverage path is source-bounded and the broad-OCR selected-value carry-through is directionally correct, but the remaining distinct-generation comparison bug affects the final user-facing deterministic answer contract. No protected-main promotion or Chrome re-smoke should occur until the fixback is reviewed.
