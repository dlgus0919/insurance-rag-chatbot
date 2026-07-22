# Review Team Re-review: Fifth Policy Authority / 000 Guardrail Fixback

- Review time: 2026-07-18 13:24 KST
- Target: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-fifth-policy-authority`
- Protected main: `/srv/shared/projects/insurance-rag-chatbot`
- Expected base: `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`
- Developer marker: `DEVELOPER_NO_MATCH_AND_FIFTH_FALLBACK_FIXBACK_COMPLETE`
- Prior review: `docs/reviews/2026-07-18-124339-review-team-fifth-policy-authority.md`
- Planner triage: `docs/reviews/2026-07-18-131716-developer-handoff-triage.md`
- Boundary: read-only review; no implementation, stage, commit, push, integration, deploy, restart, candidate apply, reindex, GraphDB rebuild, or operational-data mutation

## Findings

No blocking findings remain. Both prior findings were independently reproduced after the fixback and now satisfy the requested fail-closed/provenance contracts.

## Prior Finding Closure

### P1 closure: empty standard-code lookup

- `src/claim_calculation/pipeline.py:934-961` now classifies the no-match result before calculation, applies the explicit-code policy, and creates `requires_user_disambiguation=True` with no candidates when the high-risk category requires a code.
- `src/claim_calculation/pipeline.py:204-214` keeps the explicit-code decision independent of whether a database match exists.
- Exact reproduction: raw `도수치료`, empty `input_code`, fourth generation, outpatient, special-calculation `unknown`, nonpay `500000`, and `match_standard_code()=[]` returned:
  `blocked_missing_info`, aggregate `deductible=None`, aggregate `payable_amount=None`, line `needs_code_selection`, and `excluded_from_calculation=True`.
- Regression: `tests/test_claim_calculation_pipeline.py:1116-1142` asserts the same contract, including no monetary line result and an empty candidate list.

### P2 closure: fifth-generation `article` omission

- `scripts/extract_claim_rule_candidates.py:221-224` now uses `chunk.get("article") or source_chunk_id:<chunk_id>` in the fifth-generation deductible rule builder. The common candidate path remains null-safe at `:119` and `:435`.
- Exact reproduction with a valid special-case chunk whose only missing field was `article` returned two candidates without an exception. Both were `pending`, both retained `source_clause=source_chunk_id:표준약관_ch_missing_article`, and parsed values remained intact: copay ratio `0.3`, hospitalization annual limit `50000000`, outpatient minimum deductible `30000`, and outpatient per-visit limit `200000`.
- Regression: `tests/test_claim_rule_candidate_review.py:268-297` asserts pending/candidate authority, canonical source ID/clause, ratio, and parsed limits.

## Non-regression Verification

- Raw-name candidate behavior remains fail-closed: `tests/test_claim_calculation_pipeline.py:999-1038` preserves candidate display, `blocked_missing_info`, `needs_code_selection`, null monetary fields, and exclusion before a code is selected.
- Explicit `MX122` remains the structured authority: `tests/test_claim_calculation_pipeline.py:1061-1088` verifies fourth-generation outpatient nonpay `500000 -> deductible 150000, payable 350000`, `estimated_review_required`, and retained active-rule evidence.
- Explicit `51040` remains distinct: `tests/test_claim_calculation_pipeline.py:1145-1163` verifies payable `0`, deductible `500000`, and the input-code scope review.
- When the exact fourth-generation rule is forced absent, an independent probe returns line `needs_rule_approval` with the line excluded from calculation; the active exact-rule path remains the only path that produces the MX122 estimate.
- The processing policy only declares classification and explicit-code requirements in `config/claim_processing_policy.json:41-95`; it contains no payout amount, ratio, or limit authority. Financial values remain source/rule-layer data.
- Fifth-generation source wording remains metadata-derived in `src/rag/source_grounded_answers.py:90-113`; direct chunk authority distinguishes own, standard, and other sources. The runtime path does not use the stale static `standard_reference_note`.
- The hair-loss correction artifact remains approval-gated at `docs/review_artifacts/2026-07-18-hair-loss-full-payload-correction-candidate.json:93-115`: direct fourth/fifth source evidence, `status: pending`, and `test_candidate: false`.

## Scope and Operational Audit

- The isolated worktree is still based at `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`. Its 43 uncommitted paths are the expected source, test, policy, E2E guard, report, and pending-artifact paths; no unrelated patch path was found.
- Current tracked diff: 21 files, `875 insertions(+), 134 deletions(-)`. `git diff --check` passed.
- No active ontology/rule/index/report data path appears in the isolated diff or status. Protected reference hashes remained stable for `data/ontology/concepts.json`, `data/rules/claim_deductible_rules.active.json`, and `data/rules/rule_links.active.json`; ontology sync also passed with `concepts=55`, `aliases=126`, `candidate_aliases=18`, `retrieval_rules=5`.
- No private-key/API-key candidate files were found. No worktree logs, traces, Playwright results, videos, or HAR files were present. Four ignored Python bytecode caches were created/updated by the test runtime; they are not part of the patch and were left untouched under the read-only boundary.
- The isolated E2E runner binds database, users, logs, and browser artifacts under its temporary root. `src/api/isolated_smoke.py:81-117` requires absolute destinations contained by that root, and `src/db/standard_codes.py:14-26` opens the reference SQLite database read-only under the isolated flag.
- Protected main was clean at `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`; `origin/master` resolved to the same commit and `git diff HEAD origin/master` was empty.
- Protected uvicorn PID `2217937` remained running with start time `Fri Jul 17 13:00:24 2026`; no service restart or control command was issued.
- The protected live smoke issued only GET/HEAD requests as enforced by `tests/e2e/live-readonly-smoke.spec.js:4-20`. The production database/account files were not written by the review. The active FastAPI log can still append normal access-log entries for GET requests; after this smoke its observed file was `logs/fastapi_20260717_130024.log` at mtime `2026-07-18 13:22:28` and size `25646`. This is a server logging side effect of a read-only HTTP probe, not a write request or a patch mutation.

## Independent Verification

- Exact prior-finding regressions: `2 passed in 0.06s`.
- Six boundary regressions covering raw-name selection, no-match fail-closed, explicit `MX122`, explicit `51040`, and fifth-generation fallback: `6 passed in 0.06s`.
- Focused isolated-workspace pytest: `182 passed, 1 warning`.
- Full isolated-workspace pytest: `1002 passed, 3 warnings in 14.44s`.
- Ontology sync check: passed with `concepts=55`, `aliases=126`, `candidate_aliases=18`, `retrieval_rules=5`.
- Isolated Playwright write E2E: `1 passed (3.4s)` on loopback port `18188`; candidate selection, `MX122`, `150000/350000`, and same-thread follow-up passed.
- Protected `127.0.0.1:18080` GET-only smoke: `1 passed (3.0s)`; no login, chat, or claim write request was sent.

## Residual Risk and Recommended Integration Procedure

- The pending hair-loss correction still requires explicit practitioner approval before any active apply, ontology update, GraphDB rebuild, or reindex.
- The broader 856-chunk standard-policy generation classification remains outside this fixback scope, as noted in report 273.
- For future strictly zero-log-mutation checks, use an isolated service/access-log sink or omit the protected live smoke; GET-only protects application data paths but does not suppress normal server access logging.
- Do not integrate or push from this review. If promotion is later approved, first preserve this isolated evidence, obtain explicit approval for the pending artifact, run the same focused/full pytest and isolated E2E checks, run only the protected GET-only smoke, then review the final diff and protected-main cleanliness before a separate controlled integration.

## Verdict

PASS
