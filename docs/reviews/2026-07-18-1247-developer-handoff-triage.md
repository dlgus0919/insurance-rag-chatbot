# Developer Handoff Triage

- Timestamp: 2026-07-18 12:47 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Scope/spec: Review Team verdict for the fifth-policy-authority / 000 guardrail patch in `/srv/shared/workspaces/muldae/insurance-rag-chatbot-fifth-policy-authority`

## Reported

Review Team returned `CHANGES_REQUESTED` with two findings and wrote the immutable report `docs/reviews/2026-07-18-124339-review-team-fifth-policy-authority.md`:

1. Plain `도수치료` still receives a monetary result when standard-code lookup returns no rows.
2. The fifth-generation special-case candidate extractor still raises `KeyError` when `article` metadata is absent.

Review Team independently reported focused `180 passed, 1 warning`, full `1000 passed, 3 warnings`, isolated browser E2E pass, protected-port GET-only smoke pass, and protected-main cleanliness.

## Observed

- `src/claim_calculation/pipeline.py:934-943` converts an empty standard-code lookup into a no-code `StandardMatch` but does not set `disambiguation_required`.
- `_requires_explicit_standard_code_selection()` is evaluated only in the non-empty-match branch and explicitly returns false when the match has no code.
- Planner independently reproduced the P1 path with plain `도수치료`, empty `input_code`, fourth generation, outpatient, special status unknown, nonpay 500,000 won, and `match_standard_code()` returning `[]`. Actual result: `estimated_review_required`, deductible `150000`, payable `350000`, line status `calculated`.
- `scripts/extract_claim_rule_candidates.py:223` still accesses `chunk['article']` directly in `_deductible_rule()`.
- Planner independently reproduced the P2 path with a valid fifth-generation special-case chunk lacking only `article`. Actual result: `KeyError: 'article'`.
- Explicit `MX122`, explicit `51040`, the corrected fourth-generation article fallback, source-authority behavior, pending hair-loss artifact, and isolated E2E safeguards were verified by Review Team and are not part of this fixback.
- Protected main remains unchanged at `cd82f9e`; no integration authority is granted.

## Not Verified

- The required fixes and their new regressions do not yet exist.
- Full and browser verification must be rerun after the fixes rather than inferred from the pre-fix suite.

## Findings

### P1 - Empty standard-code lookup bypasses explicit-code authority

The review finding is valid. A raw high-risk name must fail closed even when the lookup returns no rows; an empty or unavailable lookup cannot grant more payout authority than a non-empty candidate lookup.

### P2 - Fifth-generation candidate extractor has an uncovered article fallback

The review finding is valid. The report states a general missing-article fallback contract, but the special-case 5th-generation rule builder still requires the key.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

Target: Developer thread `019eaf4a-6338-7812-bf3b-663df7d83d4f`.

Developer is instructed to make only the two minimal corrections, add direct regressions for the independently reproduced paths, preserve explicit MX122/51040 behavior and all active/pending boundaries, rerun focused/full and both browser checks, update report 274, and stop before stage, commit, push, protected-main integration, deploy, service changes, candidate apply, reindex, or GraphDB rebuild.
