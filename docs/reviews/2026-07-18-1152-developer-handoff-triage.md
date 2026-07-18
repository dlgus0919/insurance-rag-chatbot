# Developer Handoff Triage

- Timestamp: 2026-07-18 11:52 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f` (not routed)
- DGX isolated worktree: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-fifth-policy-authority`
- Protected DGX main: `/srv/shared/projects/insurance-rag-chatbot` at `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`

## Reported

Developer reports that the 000 guardrail fixback, fifth-generation policy-source authority fix, manual-therapy calculation flow, and isolated browser E2E are complete. Reported verification is focused `158 passed`, full `999 passed`, isolated Playwright `1 passed`, protected-port read-only Playwright `1 passed`, frontend build pass, ontology sync pass, and `git diff --check` pass. The protected main remains clean and no commit, push, deploy, active-manifest mutation, production DB write, reindex, or service restart was performed.

## Observed

- Plain `도수치료` is candidate-only and returns `needs_code_selection` with no money result.
- Candidate-selected or directly entered `MX122` is preserved as `input_code=MX122` and reaches the existing approved 4th-generation exact rule.
- The tested contract is 4th generation, outpatient, special-calculation status unknown, nonpay 500,000 won -> deductible 150,000 won, payable 350,000 won, `estimated_review_required`.
- `51040` preserves its structured exclusion result instead of being reinterpreted as `MX122`.
- Isolated browser E2E binds chat DB, users, logs, credentials, port, and Playwright artifacts to an explicit temporary root. Protected port `18080` is restricted to a GET-only smoke.
- The standard-code database connection uses SQLite `mode=ro` only for the explicit isolated E2E mode, and a regression test proves writes fail.
- Base ontology, active claim manifest, protected main, and production-like data remain unchanged.

## Finding

### P1 - Evidence-spec candidate extraction crashes when `article` metadata is absent

- Location: `scripts/extract_claim_rule_candidates.py:435`
- Current expression: `primary.get("article") or f"source_chunk_id:{primary[chunk_id]}"`
- Defect: `chunk_id` is undefined in that scope. A valid source chunk without `article` raises `NameError` instead of falling back to its canonical chunk identifier.
- Reproduction: invoking `extract_fourth_manual_therapy_candidates()` with the existing valid three-chunk evidence fixture after omitting `article` fails at line 435 with `NameError: name 'chunk_id' is not defined`.
- Why the suite missed it: current extractor tests populate `article` for the primary chunk, so Python never evaluates the faulty fallback expression.
- Impact: future OCR/reingest evidence that lacks article metadata can stop pending rule-candidate generation. This is a release-blocking correctness defect in the same implementation slice.

## Decision

`DEVELOPER_FIXBACK`

The runtime calculation and isolated E2E portions appear ready for independent review, but the complete patch set is not ready for Review Team or protected-main integration while this observed crash remains.

## Required Fix

1. Replace the undefined fallback reference with the primary chunk's canonical `chunk_id` without changing candidate authority, payout values, status, or active manifests.
2. Add a regression test using an otherwise valid evidence set whose primary chunk has missing or empty `article`; assert candidate generation succeeds and `source_clause == "source_chunk_id:<primary_chunk_id>"`.
3. Run at minimum:
   - `pytest tests/test_claim_rule_candidate_review.py tests/test_rule_candidate_evidence_specs.py -q`
   - the previously reported focused suite
   - full `pytest -q`
   - `git diff --check`
4. Confirm `data/ontology/concepts.json`, active manifests, protected main, and production DB/logs remain unchanged.
5. Update report 274 with the regression and final verification counts. Do not stage, commit, push, deploy, restart services, apply the pending hair-loss candidate, rebuild GraphDB, or reindex.

## Stop Rule

Return with the exact changed files, commands/results, protected-main status, and marker `DEVELOPER_EVIDENCE_FALLBACK_FIXBACK_COMPLETE`. Planner will then re-inspect the diff and decide whether to route the same patch set to Review Team.
