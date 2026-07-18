# Developer handoff triage — chat continuity, surgery grade, and manual-therapy release

- Project: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Developer isolated workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-chat-procedure-claim-stabilization`
- Protected DGX main: `/srv/shared/projects/insurance-rag-chatbot`
- Base commit: `0ad60f156afcf001bf425338fae9c98dbc3afe86`
- Triage time: 2026-07-17 12:09 KST

## Reported

- Developer implemented chat-history restoration and request/session race protection, unified general-query and claim-calculation history, deterministic surgery-grade lookup, bounded standard-code candidates, and exact 4th-generation manual-therapy rule gating.
- Developer reported `954 passed, 1 failed`, Node and Playwright passes, frontend build success, and no protected-main deployment.
- In the later completed turn, Developer cross-checked and approved these two source-grounded candidates without applying them:
  - `rulecand.add.deductible.4th.three_major_manual.hospitalization`
  - `rulecand.add.deductible.4th.three_major_manual.outpatient`

## Observed

- The Developer thread is idle and its latest completed turn records both candidates as approved, not applied.
- DGX main and `origin/master` remain at `0ad60f1`; the implementation is not patched into DGX main.
- DGX main rule state is `pending=23, approved=2, rejected=1, applied=0`. `--apply --dry-run` selects exactly the two approved manual-therapy candidates and adds their rules and links.
- Active rule manifest hash is still `1f803f3bd2f201de102349b48622ba14fa1c244a1a7e08e78c1569a5619c0d5c`; neither manual-therapy rule exists in it yet. `data/rules/rule_links.active.json` does not exist yet.
- Read-only focused DGX verification passed: `246 passed, 1 warning`; local Node thread-state tests passed `3/3`; DGX `node --check` and `npm run build` passed.
- The previously suspected duplicate JavaScript declaration was a range-overlap inspection artifact and was withdrawn after direct syntax/build verification.
- The combined-plan acceptance suite includes `tests/test_api_claim_calculation.py`. Its `test_claim_calculation_route_returns_payable_amount` still fails on both base and implementation because it expects deductible/payable `75,000/75,000`. Once the approved 30% manual-therapy rule is active, the source-grounded expected result for 150,000원 is deductible/payable `45,000/105,000`; this test contract must be updated and the full suite must pass.
- `docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md` still says both candidates are pending and active application is a future step, so it is stale after the approved review turn.
- The isolated workspace contains task-local symlinks/artifacts (`.venv`, `node_modules`, `test-results`) and remains uncommitted. These are valid for testing but are not release content and must be removed with the task workspace after successful promotion.
- The local protected checkout contains pre-existing untracked triage/plan documents and unrelated stale/prunable worktree records; they are outside this release and must not be deleted or swept into the commit.

## Not verified yet

- Full Python suite after applying the two approved rules and updating the stale API assertion.
- GraphDB rebuild using the newly generated active rule-link manifest and post-build integrity checks.
- Live DGX app smoke for chat-history restoration, same-thread calculation-to-general-query continuity, the three surgery-grade scenarios, and 4th-generation `MX122` manual therapy after deployment.
- Final commit/push hash equality among GitHub `master`, DGX main, and the intended release commit.
- Removal of only this task's isolated workspace and temporary staging after successful release.

## Routing decision

**Route: Developer fixback and release.**

The implementation has no confirmed focused-code regression, but required release deliverables are missing and the authoritative combined suite still has one in-scope stale assertion. Per the routing contract, missing deliverables and a known acceptance failure route back to Developer, not Review Team.

## Required completion evidence

1. Apply only the two approved manual-therapy candidates; verify both become `applied`, the active rule rows have `approval_status=active`, and no other pending candidate is promoted.
2. Update the stale API test to the approved rule contract and add/retain assertions for `45,000원` deductible, `105,000원` payable, and review requirements. Do not skip or xfail the test.
3. Update report 272 to the final approved/applied state, actual test totals, GraphDB result, deployment, rollback, and cleanup evidence.
4. Rebuild `frontend/dist/app.min.js` from the final source and include it only if the repository's tracked production bundle changes.
5. Persist the active manifest and active rule-link manifest in the release commit; keep runtime candidate/review JSONL out of Git if the established runtime-data policy requires it, while preserving it on DGX.
6. Rebuild GraphDB with the active rule links and run integrity/synchronization checks. Do not restart or modify Qwen/SGLang.
7. Run the combined focused suite, full pytest with zero failures, Node tests, frontend build, Playwright, and `git diff --check`.
8. Patch the validated files into the protected DGX main without overwriting unrelated state, commit intentionally, push `master` force-free, and verify local/GitHub/DGX commit equality.
9. After successful smoke and push, remove only this task's isolated DGX workspace, local `/private/tmp/insurance-rag-chat-procedure-staging`, task test artifacts, and task backup if no longer needed. Preserve unrelated worktrees and existing untracked user files.
