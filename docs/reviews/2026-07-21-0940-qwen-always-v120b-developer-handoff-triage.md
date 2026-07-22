# Developer Handoff Triage

- Timestamp: 2026-07-21 09:40 KST
- Cycle: qwen-always-v1.2.0.b-20260721-0940
- Project root: protected runtime `/srv/shared/projects/insurance-rag-chatbot` currently detached at `v1.2.0` (`3a8b6af`)
- Developer thread: `/root/developer_grounded_composite` (paused prior scope; to receive a new focused task)
- Review Team thread: to be created after Developer completion
- Scope/spec: temporary `1.2.0.b` retrieval-response override requested by user

## Reported

- User reports that the policy phrase “individual coverage cannot be stated without directly approved evidence” is over-applied and requests a temporary patch so Qwen is always invoked for answer generation, delivered as version `1.2.0.b`.

## Observed

- In `v1.2.0`, `prepare_retrieved_context()` returns `deterministic_answer` when approved-evidence assessment or a deterministic guard produces text.
- `src/api/routes/chat.py:717-722` streams that `deterministic_answer` directly and never calls `_generate_llm_stream()`.
- The neighboring `else` path at `src/api/routes/chat.py:723-742` already invokes Qwen for the same retrieved prompt, preserves sources/Graph payload/warnings, and finalizes the generated text.
- Formal and quick-code routes already reach `_generate_llm_stream()`; claim follow-up and ambiguous-continuation paths intentionally return structured non-LLM data and are out of scope because they are not document-answer generation.
- Protected runtime is clean at `v1.2.0`; the prior candidate for a different issue remains isolated and unmerged.

## Not Verified

- No `1.2.0.b` candidate exists yet.
- The final Qwen runtime request will be observed only after candidate promotion/restart; unit tests can verify the call boundary without consuming the production model.

## Findings

1. **P1 — deterministic short circuit suppresses Qwen.** Required fix: general retrieved responses must use the existing Qwen streaming path even when `deterministic_answer` is present. Keep retrieval, source emission, Graph payload, warning propagation, and final-answer normalization unchanged.
2. **P1 — version traceability.** Required fix: UI-visible version must become `1.2.0.b`, the generated SPA bundle must be rebuilt, and the reviewed candidate commit must receive a local `v1.2.0.b` tag at promotion. Do not mutate npm dependency versions for a display-only emergency patch.
3. **Scope fence.** No alterations to active calculation rules, GraphDB, ontology approvals, raw/OCR documents, source index, LLM/prompt settings, authentication, claim follow-up, or ambiguous-continuation behavior.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

Target: `/root/developer_grounded_composite`.

Prompt sent: create a fresh candidate from `v1.2.0`; replace only the retrieved-response deterministic short circuit with the existing Qwen stream/finalization path; retain structured claim/continuation paths; prove the call boundary with a focused test; set the UI label to `1.2.0.b` and rebuild the SPA; run focused/full tests; write an immutable report; commit the candidate release files only. No tag, merge, push, restart, reindex, data rebuild, or protected runtime mutation is authorized for Developer.
