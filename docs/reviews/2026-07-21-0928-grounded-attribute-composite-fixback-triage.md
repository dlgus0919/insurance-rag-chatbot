# Developer Handoff Triage

- Timestamp: 2026-07-21 09:28 KST
- Cycle: grounded-attribute-composite-quickcode-20260721-0928-fixback
- Project root: candidate `/srv/shared/workspaces/muldae/insurance-rag-grounded-attribute-composite-20260721`
- Developer thread: `/root/developer_grounded_composite`
- Review Team thread: `/root/review_grounded_composite` (`REVIEW_CHANGES_REQUESTED`)
- Scope/spec: `docs/superpowers/plans/2026-07-21-grounded-attribute-and-composite-quickcode.md`; review `docs/reviews/2026-07-21-0926-grounded-attribute-composite-review.md`

## Reported

- Developer reported focused `173 passed` and full `1208 passed` for the candidate.
- Review Team independently reran the same focused/full suites and obtained the same pass counts, but found a contract-level scenario missing from the tests.

## Observed

- Candidate `src/rag/pipeline.py` suppresses a second row only when both displayed rows have the same `policy_generation`.
- Reviewer reproduced a single-generation question (`4세대 검사X의 연간 보상한도는?`) with two direct rows (`4th=300만원`, `5th=200만원`) and observed a 4th/5th comparison answer.
- This contradicts the approved contract: comparison formatting requires an explicit request for multiple distinct generations, not merely two rows with different metadata.
- No protected runtime, data, GraphDB, ontology, rule, prompt, frontend, index, or service change occurred.

## Not Verified

- No post-fix candidate test or re-review exists yet.
- Chrome re-smoke is intentionally unrun and remains blocked behind a PASS plus separately authorized promotion/restart.

## Findings

1. **P1 — false comparison remains possible.** Evidence: candidate `src/rag/pipeline.py:_build_clause_detail_evidence_answer()` and review reproduction in `docs/reviews/2026-07-21-0926-grounded-attribute-composite-review.md`. Required fix: compute requested generations from the question only (do not let selected UI generation manufacture a comparison). Only when two or more distinct generations are explicitly requested may one row per requested generation be displayed as a comparison. For a single-generation question, select the row matching `policy_generation` when available, otherwise render exactly one row.
2. **P2 — Korean topic-particle resilience.** The fee cue pattern should accept normal topic/subject particles immediately before the fee cue (`의`, `은`, `는`, `이`, `가`) and strip them before exact raw-HIRA matching. This is a grammar-general validation improvement, not a named-procedure exception.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

Target: `/root/developer_grounded_composite`.

Prompt sent: constrain comparison rendering to two distinct generations explicitly named in the question; for single-generation questions, select only the requested UI generation row or one deterministic fallback. Add generic single- and dual-generation regressions, accept/strip a general Korean topic particle before a fee cue, rerun focused/full tests, and save an immutable candidate fixback record. No stage, commit, push, merge, restart, reindex, rebuild, or protected runtime mutation is permitted.
