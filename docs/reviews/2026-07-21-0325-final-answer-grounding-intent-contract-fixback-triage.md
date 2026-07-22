# Developer Handoff Triage

- Timestamp: 2026-07-21 03:25 KST
- Cycle: `final-answer-grounding-20260721-0325-intent-contract-fixback`
- Candidate workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`
- Candidate branch/base: `codex/final-answer-grounding-20260721` from `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`
- Predecessor review: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721/docs/reviews/2026-07-21-0318-final-answer-grounding-fixback-rereview.md`

## Observed

The P0 comparison-completeness correction passed independent review.  A second
P0 remains in the intent contract: `classify_search_intent()` calculates
`requires_coverage`, but `clause_or_appendix_lookup`, `cross_doc_compare`, and
`procedure_code_lookup` do not preserve it in their returned plan.  The later
specialized coverage gate therefore sees `False` and allows the ordinary LLM
path for real compound questions.

Read-only reproduction from the reviewer:

```text
question: 식도조루술 수가 코드와 실손 보상 여부를 알려줘.
raw coverage judgment: True
route / plan: quickcode / procedure_code_lookup
plan.requires_coverage_judgment: False
disposition: llm / none
registry evaluation calls: 0
```

This is a general intent-propagation defect, not an MRI, generation, procedure,
or keyword-specific issue.

## Required correction

1. Preserve the existing computed `requires_coverage` value in all three
   relevant `SearchIntentPlan` return branches:
   `clause_or_appendix_lookup`, `cross_doc_compare`, and
   `procedure_code_lookup`.
2. Add real automatic-routing regression tests.  Do not force the route or
   hardcode named procedures/generations in production code.
   - A code/surgery-code plus coverage query must be `coverage_insufficient`,
     retain public sources, make no LLM call, and persist zero grounded direct
     sources when no approved direct evidence exists.
   - A clause/exclusion plus coverage query must obey the same boundary.
   - A two-axis comparison plus coverage query must not disclose numeric
     comparison values when it has only attribute evidence and no approved
     direct coverage/exclusion evidence.
   - Pure code lookup, procedure-grade lookup, and clause explanation requests
     must keep their established non-decision behavior.
3. Retain all prior P0/P1 tests: incomplete and complete generic comparisons,
   approved direct coverage evidence, public provenance stripping, and source
   payload contracts.

## Scope fence

Code and tests only in the existing candidate.  Do not change active
calculation rules, manifests, GraphDB/ontology, raw documents, user/operational
data, frontend/PDF behavior, service configuration, or runtime services.  Do
not stage, commit, push, merge, restart, rebuild, reindex, or promote.

## Verification and handoff

Run focused and full pytest, compile/import checks as appropriate, and
`git diff --check`; update the Developer implementation report with exact
results.  This correction needs a fresh, read-only Review Team verdict before
any promotion decision.

