# Review Team: Fifth Policy Authority / 000 Guardrail Review

- Review time: 2026-07-18 12:43 KST
- Target: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-fifth-policy-authority`
- Base: `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`
- Protected main: `/srv/shared/projects/insurance-rag-chatbot`
- Developer marker: `DEVELOPER_EVIDENCE_FALLBACK_FIXBACK_COMPLETE`
- Boundary: read-only review; no implementation, operational-data, service, index, GraphDB, candidate-apply, stage, commit, or push action

## Findings

### [P1] Plain `도수치료` can still receive a final payout when standard-code lookup returns no rows

- `src/claim_calculation/pipeline.py:931-943` creates a `StandardMatch` with no code when lookup returns no rows, but does not set `disambiguation_required` or `requires_user_disambiguation`.
- `src/claim_calculation/pipeline.py:599-625` blocks only an ambiguous match or a missing fourth-generation rule. A no-code `StandardMatch` therefore falls through to the normal calculation path.
- `config/claim_processing_policy.json:91-94` explicitly marks `3대비급여_도수` as requiring an explicit code, but `_requires_explicit_standard_code_selection()` is only reached in the non-empty-match branch at `src/claim_calculation/pipeline.py:982-1016`.
- Independent reproduction with `input_name=도수치료`, empty `input_code`, fourth generation, outpatient, `500000`, and `match_standard_code()` returning `[]` produced `deductible=150000`, `payable_amount=350000`, and line `calculation_status=calculated`.
- The passing regression at `tests/test_claim_calculation_pipeline.py:1091-1113` covers only the case where the mocked name lookup returns candidates; it does not cover the explicit no-row branch.

This violates the stated 000 contract that raw `도수치료` is candidate-only and must not produce a monetary final. It can be reached by an empty, filtered, unavailable, or changed standard-code result and must fail closed before the active `3대비급여_도수` rule is applied.

### [P2] The missing-`article` source fallback is still broken in the fifth-generation special-case extractor

- `scripts/extract_claim_rule_candidates.py:221-224` uses `chunk["article"]` in `_deductible_rule()`.
- A valid fifth-generation special-case chunk containing `text`, `doc_short`, `page`, and `chunk_id` but no `article` independently reproduced `KeyError: 'article'` in `extract_special_case_5th_candidates()`.
- The new regression at `tests/test_claim_rule_candidate_review.py:345-377` exercises only `extract_fourth_manual_therapy_candidates()`. Its fallback passes through `scripts/extract_claim_rule_candidates.py:435`, but the fifth-generation special-case branch remains uncovered.

This contradicts the report contract in `docs/274_000_GUARDRAIL_FIXBACK_REPORT.md:39-42`: a missing article must preserve canonical chunk provenance and continue creating a pending candidate. The failure is in candidate generation, not active payout data, but it can stop valid fifth-generation rule extraction.

## Verified

- The previously reported undefined fallback reference is gone. `scripts/extract_claim_rule_candidates.py:119` and `:435` use a defined `chunk_id`/`primary["chunk_id"]` fallback; no `primary[chunk_id]` reference remains.
- The fourth-generation missing-primary-article regression executes the intended branch and preserves `source_clause=source_chunk_id:약관_ch_002441`, two pending candidates, canonical source ID, and candidate authority.
- Explicit `MX122` behavior passed: `tests/test_claim_calculation_pipeline.py:1061-1088` verifies fourth-generation outpatient nonpay `500000 -> deductible 150000, payable 350000, estimated_review_required`, with active rule evidence.
- Explicit `51040` exclusion remained distinct and was covered by `tests/test_claim_calculation_pipeline.py:1116-1130` and the full suite.
- `config/claim_processing_policy.json:1-95` contains classification and code-selection metadata only; it contains no payout amount, ratio, or limit values. Financial extraction remains in source-grounded candidate logic.
- Fifth-generation source authority is computed from direct chunk metadata in `src/rag/source_grounded_answers.py:90-113`; the stale static `standard_reference_note` is not used by that runtime path. Reports 273/274 and the source-authority tests agree with this behavior.
- The hair-loss correction artifact remains non-active: `docs/review_artifacts/2026-07-18-hair-loss-full-payload-correction-candidate.json:93-115` shows direct fourth/fifth source chunks, `status: pending`, and `test_candidate: false`. No apply or rebuild was performed.
- Isolated browser E2E passed: 1 test, `3.7s`, including raw-name candidate selection, `MX122`, `150000/350000`, and same-thread follow-up.
- Protected `127.0.0.1:18080` read-only smoke passed: 1 test, `2.5s`. The config accepts only the loopback protected port, refuses write flags, and the test emitted only GET/HEAD requests.
- Relevant focused tests passed: `180 passed, 1 warning`. Full isolated-worktree pytest passed: `1000 passed, 3 warnings`.
- Protected main remained clean at `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`; `origin/master` resolved to the same commit and `git diff HEAD origin/master` was empty. The protected uvicorn process on port 18080 remained running and was not restarted.
- Isolated patch status contained only the expected source, test, policy, E2E safeguard, report, and pending-artifact paths. `git diff --check` passed. Secret-pattern scan found no candidate private-key/API-key files. Existing ignored Python bytecode caches were present but had no recent mtime and were not part of the patch; they were left untouched under the read-only boundary.
- Tracked ontology/rule/index/report data paths had no diff or status change in the isolated worktree. The isolated runner bound its database, users, logs, and browser artifacts to `/tmp`; the live smoke used GET/HEAD only and did not write the protected application database.

## Minimal Developer fixback prompt

```text
Ponytail/Fable5 fixback only. Do not refactor, touch Streamlit, apply pending artifacts, modify active ontology/manifests/DB/logs, restart services, or change MX122/51040 behavior.

1. In scripts/extract_claim_rule_candidates.py, make _deductible_rule use the same null-safe source_clause fallback as the corrected candidate path: absent/empty article must fall back to source_chunk_id:<chunk_id>. Add one regression for extract_special_case_5th_candidates() with article absent; preserve source_chunk_id, pending status, candidate authority, and all parsed rule values.
2. In src/claim_calculation/pipeline.py, close the empty-standard-code-match path for raw 도수치료: with empty input_code and a category requiring explicit code, it must not reach an active payout rule or return monetary totals. Return the existing no-payout review/selection state appropriate to the no-row case. Add a regression with match_standard_code() returning [] for fourth-generation outpatient nonpay 500000 and assert no final deductible/payable. Keep the existing explicit MX122 and 51040 tests unchanged and passing.
3. Re-run the focused/full pytest and both browser checks from the same isolated worktree. Report only exact evidence and leave protected main and operational data untouched.
```

## Verdict

CHANGES_REQUESTED
