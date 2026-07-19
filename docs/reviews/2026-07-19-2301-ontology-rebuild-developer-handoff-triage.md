# Developer Handoff Triage

- Timestamp: 2026-07-19 23:01 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f` (`Developer`, project cwd matched)
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f` (`Review Team`, project cwd matched)
- Scope/spec: general-query ontology and GraphDB rebuild preparation for `v1.2.0`; active claim-calculation rules frozen

## Reported

- The user deferred final physical GUI acceptance testing and ranked the offline HDD installer as the lowest-priority remaining item.
- The user authorized a general-query ontology and GraphDB rebuild, direct practitioner approval/rejection by the Planner, version minor bump, operational promotion, and push if validation passes.
- The user explicitly requested that current active claim-calculation rules remain unchanged unless a major defect is found.

## Observed

- DGX protected main `/srv/shared/projects/insurance-rag-chatbot` is clean at `3cd661778059ca0901c32c3147b789de81518c0f`, equal to `origin/master`; runtime status is overall `ok` and SGLang/Qwen remains active.
- Latest release tag is `v1.1.0`, so the requested second-position bump maps to candidate `v1.2.0`.
- Active calculation boundary hashes before this work:
  - `data/rules/claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
  - `data/rules/rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
  - `src/claim_calculation/processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- Raw ontology contains 55 concepts. The approved-integrity baseline trusts 49 and quarantines 6 legacy hair-loss payload concepts with insufficient provenance.
- Existing candidate store has 17 applied, 10 rejected, and 3 held candidates. The three held candidates are `dev.cov.indemnity_medical.2f8f7057fb90`, `dev.cond.motorcycle_riding.fc842c72db6f`, and `dev.cov.superior_room_difference.d1fad7d62df5`.
- Workbook `phase4_weak20_final_answers_for_practitioner_review (2).xlsx` contains 20 practitioner re-review cases: 10 approved, 5 conditionally approved, 5 hold/regression.
- Workbook `테스트셋(추가56문항)_qwen80b (2).xlsx` contains 56 cases: 55 scored, 43 scored 5, 9 scored 1, 1 scored 2, 2 scored 3, and 1 unscored. Weaknesses cluster in claim payment/documents, coverage/exclusions, non-pay rider conditions, generation/source authority, and multiple-policy handling.
- Both workbooks were imported and all sheets were rendered for visual inspection without modifying the source files.

## Not Verified

- No fresh ontology extraction has yet been run against the current raw/canonical data and evaluation questions.
- No new candidate payload has yet been inspected or practitioner-decided by the Planner.
- No `v1.2.0` isolated GraphDB has been built, reviewed, published, deployed, or tagged.
- Full resource impact and operational rollback artifacts for the upcoming rebuild have not yet been produced.

## Findings

1. **P1 — required deliverable missing:** an auditable, source-grounded general-query candidate batch does not yet exist for the current evaluation findings.
2. **P1 — approval boundary:** the six quarantined hair-loss concepts must not be silently reintroduced; they remain rejected from the trusted runtime projection unless a new explicit practitioner approval occurs.
3. **P1 — calculation freeze:** any change to active calculation-rule files, rule links, or processing policy is outside scope and must stop the work.
4. **P2 — stale held candidates:** the three held legacy candidates contain sentence fragments, over-broad aliases, or ownership mismatch and require explicit practitioner disposition before the rebuilt ontology is finalized.

## Decision

`DEVELOPER_FIXBACK`

The Developer must prepare only the isolated candidate/evidence package first. The Planner retains all practitioner approval/rejection authority. Review Team routing is premature until the approved batch is applied and validated in isolation.

## Dispatch

Target: Developer thread `019eaf4a-6338-7812-bf3b-663df7d83d4f`.

Prompt sent:

```text
Prepare the source-grounded general-query ontology candidate/evidence package for the v1.2.0 rebuild. Work only in a new isolated muldae workspace based on protected main commit 3cd661778059ca0901c32c3147b789de81518c0f. Do not edit /srv/shared/projects/insurance-rag-chatbot.

This is preparation phase only. Do not approve/reject candidates, apply active ontology, publish, rebuild the operational GraphDB, restart services, tag, merge, or push. The Planner will make every practitioner decision directly after reading your evidence package.

Inputs:
- /Users/june_kim/Downloads/phase4_weak20_final_answers_for_practitioner_review (2).xlsx
- /Users/june_kim/Downloads/테스트셋(추가56문항)_qwen80b (2).xlsx
- current raw/canonical chunks, policy documents, claim guide, consultation cases, ontology approval history, and safe-baseline artifacts in the repository

Required preparation:
1. Create an isolated workspace named for general ontology v1.2.0 and record its exact path/base/status.
2. Record and enforce these frozen hashes. Any mismatch is a hard stop:
   - claim_deductible_rules.active.json ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818
   - rule_links.active.json ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9
   - processing_policy.py 5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f
3. Preserve the trusted 49-concept baseline. Treat the six provenance-deficient hair-loss concepts as excluded/rejected from the proposed runtime projection; do not reintroduce their aliases or decision payload.
4. Produce a bounded candidate batch for reusable general-query concepts only, prioritizing the observed weak areas: claim documents, payment deadline and delay reasons, product/generation/source authority, Korean-medicine treatment, dental K00-K08, foreign medical institutions, surgery exclusion purposes, non-pay/no-claim discount and special-case terminology, multiple indemnity policies/proportional handling, and policy ambiguity/insufficient-grounding handling.
5. Each proposal must include canonical id/name/node type, only reusable noun-phrase aliases, planner fields, exact source chunk IDs/pages/document authority, evidence excerpts, source hash where available, evaluation case IDs, risk flags, and proposed field-level approval paths. Do not encode payment amounts, deductible rates, claim outcomes, individual question strings, or case-specific hardcoded answers in ontology concepts.
6. Include the three legacy held candidates in a separate disposition appendix with their exact current payload and evidence; do not mutate them.
7. Use deterministic/template-only or bounded existing-SGLang extraction. Do not start, stop, or switch the LLM. Do not touch protected port 18080 with writes.
8. Store the candidate artifact and an implementation-preparation report under unique repository docs/review_artifacts and docs paths in the isolated workspace. Validate JSON/schema/policy, run dry-run only, and report exact commands/results.
9. No product code changes unless the existing candidate tooling cannot represent the required evidence contract. If code changes appear necessary, stop and report the blocker instead of widening scope.
10. Preserve all unrelated state and leave the isolated workspace unstaged/uncommitted. Report temporary files/process cleanup and both isolated/protected statuses.

Completion marker: DEVELOPER_V1_2_0_ONTOLOGY_CANDIDATES_READY_FOR_PRACTITIONER_DECISION
```
