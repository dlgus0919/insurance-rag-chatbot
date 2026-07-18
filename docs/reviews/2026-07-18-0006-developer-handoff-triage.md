# Developer Handoff Triage

- Timestamp: 2026-07-18 00:06 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f` (`cwd=/Users/june_kim/Projects/insurance-rag-chatbot`, idle)
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f` (`cwd=/Users/june_kim/Projects/insurance-rag-chatbot`, not routed)
- Scope/spec: 2026-07-16 through current Developer implementation versus `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`

## Reported

Developer reports the following recent implementation and verification:

- `23278c3`: live LLM display, HIRA intent gate, and source-grounded hair-loss decisions.
- `dbd8f37`, `0ad60f1`: runtime release and Graph validation reports.
- `ac42d9f`: chat continuity, procedure-grade resolution, standard-code matching, and approved fourth-generation manual-therapy claim calculation.
- `cd82f9e`: final claim-stabilization deployment report; GitHub `origin/master` and protected DGX main were aligned.
- Latest uncommitted isolated worktree `/srv/shared/workspaces/muldae/insurance-rag-chatbot-fifth-policy-authority`: fifth-generation authority wording and future-ingest generation metadata fix, with `965 passed`, ontology sync pass, and `git diff --check` pass.
- Developer reports no commit, push, protected-main change, reindex, GraphDB rebuild, production DB write, or service restart for the latest isolated slice.

## Observed

### Repository and thread state

- Project-matched Developer and Review Team threads are unambiguous by `cwd`.
- Developer is idle and its latest turn completed with marker `DEVELOPER_FIFTH_POLICY_AUTHORITY_FIX_COMPLETE`.
- Protected DGX main is clean at `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d`, equal to its current `origin/master`.
- The latest isolated worktree is based on the same commit and contains seven modified files plus untracked report `docs/273_FIFTH_POLICY_SOURCE_AUTHORITY_FIX_REPORT.md`.
- The latest slice has not been staged, committed, pushed, or deployed.

### 000-compliant areas

- Approved claim values are stored in `data/rules/claim_deductible_rules.active.json`, not copied as payout numbers into the runtime interpreter.
- The two fourth-generation manual-therapy rules were promoted only after the user authorized those exact candidates; other pending rules remained pending.
- Procedure-grade answers read grades and source pages from GraphDB/table evidence; the resolver does not embed the three tested procedure grades as production constants.
- Historical reports, failed tests, warnings, Graph exceptions, and two accidental audit events were disclosed instead of hidden.
- Raw PDFs, model snapshots, credentials, user conversations, and account DBs were not committed.

### Guardrail conflicts

1. Commit `23278c3` directly added the complete hair-loss concept, aliases, clarification questions, source chunk pins, conditions, and decision summaries to base `data/ontology/concepts.json:14-86`. Section 5 of 000 says new ontology knowledge starts as candidate/pending and base manifest direct modification should be avoided.
2. The later applied candidate `practitioner.hair-loss-source-grounding.20260716` exists and has source evidence, but its recorded payload has empty `planner` and `retrieval` plus only a small metadata property. It does not contain the full aliases, questions, conditions, decision summaries, and direct-source mapping that entered `concepts.active.json` from the already-modified base. Therefore the approval record does not fully represent the knowledge payload that was promoted.
3. The latest isolated slice again modifies base `data/ontology/concepts.json`, replacing `standard_reference_note`. Runtime already ignores this field after the source-grounded patch, so this base mutation is unnecessary and repeats the governance violation.
4. `src/claim_calculation/pipeline.py:36-53` classifies `도수`, `체외충격파`, or `증식` from `item.input_name`/user hint as `3대비급여_도수`. That category is later sufficient to select the approved active rule. In the split nonpay path at `src/claim_calculation/pipeline.py:642-676`, a missing `StandardMatch` is not blocked because `_is_unresolved_nonpay()` only blocks the broad `비급여` category. Thus a raw item name can drive an approved 30% rule without an exact/selected standard-code or structured evidence row. This conflicts with section 6's explicit ban on applying a coded deductible from the claim item name alone.
5. `scripts/extract_claim_rule_candidates.py:34-38,329-435` embeds the three current chunk IDs, fourth-generation label, treatment category, and treatment terms in a task-specific extractor. Although amounts are parsed from evidence and output remains candidate status, a reingest that changes chunk IDs or a policy revision requires Python changes. This conflicts with section 1/2's general-processing and policy-revision boundary.
6. `src/claim_calculation/standard_matcher.py:102-117` embeds MRI/MRA query aliases and insurance table category labels in Python. Section 2 explicitly permits synonyms and processing criteria in policy/ontology manifests; keeping this mapping in runtime code is the wrong layer.
7. The release smoke described in `docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md:106` wrote two `LOGIN_FAILED` events to the production audit DB because the temporary wrapper did not forward isolated paths. Account, conversation, and calculation records were not changed, and the audit entries were preserved, but the test crossed the intended production-data boundary. This is a process violation of the test-isolation rule.
8. During manual-rule review, external official web pages were used as corroboration but were not registered as source evidence in the candidate or active rule links. The active rules remain backed by local policy chunks, so no current rule rollback is required; however outside corroboration must not be presented as decision evidence unless it is ingested and traceable under section 3.

## Not Verified

- Planner did not independently rerun the reported `965 passed` suite; Review Team should do so only after known violations are fixed.
- No destructive rollback or active-manifest demotion was attempted. Existing applied review logs are historical/append-only and must not be rewritten.
- The exact production effect of a name-only `도수치료` input was established from current control flow, but a new explicit negative regression test has not yet been added.
- The broad standard-policy document's 856 chunks were not reclassified; that remains outside this audit/fixback.

## Findings

### P1 — Approved payout rule can be selected from an unverified raw item name

- Evidence: `src/claim_calculation/pipeline.py:36-53`, `552-553`, `642-676` at `cd82f9e`.
- Impact: an input containing a treatment keyword can enter `3대비급여_도수` and execute an approved deductible without exact/selected standard-code authority.
- Required resolution: make payout-category authority depend on an exact or user-selected structured standard-code row or another approved evidence mapping. A raw name may retrieve candidates but must result in `needs_code_selection`/human task until authority is established.

### P1 — Hair-loss knowledge payload bypassed complete candidate review

- Evidence: `data/ontology/concepts.json:14-86` added by `23278c3`; runtime candidate `practitioner.hair-loss-source-grounding.20260716` contains evidence tags but not the full promoted payload.
- Impact: the applied audit record cannot reconstruct what aliases, clarification conditions, decision summaries, and pins were actually approved.
- Required resolution: do not rewrite historical logs or demote live knowledge. Prepare a complete corrective candidate/update artifact that contains the full current payload and exact source evidence, remains pending until explicit practitioner approval, and documents the migration needed to stop using base as the promotion carrier.

### P2 — Latest isolated patch unnecessarily mutates base ontology

- Evidence: isolated diff changes only `standard_reference_note` in `data/ontology/concepts.json` while `src/rag/source_grounded_answers.py` stops reading it.
- Required resolution: drop the base-manifest diff; retain and test the runtime stale-note immunity. Update report 273 accordingly.

### P2 — Recent extraction and retrieval policies are embedded in Python

- Evidence: fixed manual-therapy chunk IDs and labels in `scripts/extract_claim_rule_candidates.py`; MRI/MRA alias/category filter in `src/claim_calculation/standard_matcher.py`.
- Impact: policy/doc revisions require code changes and bypass the designated manifest/policy layer.
- Required resolution: make the extractor accept an explicit evidence specification or review input, and move MRI/MRA aliases/category constraints to a versioned processing-policy manifest. Do not move payout values into a generic policy file.

### P2 — Smoke test crossed the production audit boundary

- Evidence: `docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md:106`.
- Required resolution: add a fail-closed isolated-smoke preflight or reusable helper that refuses to start when test credentials/DB paths resolve to protected production locations. Preserve the two historical audit events.

### P3 — Unregistered external corroboration was cited during approval

- Evidence: Developer rule-review final cited FSC/KIRI pages, while active links contain only local policy chunks.
- Required resolution: document that local source chunks are the sole rule authority. Future external evidence must be ingested with provenance before influencing approval.

## Decision

`DEVELOPER_FIXBACK`

Known 000 violations remain in protected main and the latest uncommitted slice. Review Team routing is not permitted until the P1/P2 items are fixed or explicitly dispositioned with evidence.

## Dispatch

Target: Developer thread `019eaf4a-6338-7812-bf3b-663df7d83d4f`.

Developer is instructed to continue in a fresh or safely rebased isolated `muldae` workspace, preserve protected main and historical logs, apply the minimal governance and runtime fixes above with regression tests and a new implementation report, and stop before stage/commit/push/deploy. Completion marker: `DEVELOPER_000_GUARDRAIL_FIXBACK_COMPLETE`.
