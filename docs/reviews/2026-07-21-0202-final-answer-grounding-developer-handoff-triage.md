# Developer Handoff Triage

- Timestamp: 2026-07-21 02:02 KST
- Cycle: `final-answer-grounding-20260721-0202`
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Runtime baseline: DGX protected `master` at `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7` (`fix(chat): route pure policy attributes to direct retrieval`)
- Developer thread: not yet created for this cycle
- Review Team thread: not yet created; independent review follows concrete Developer completion only
- Scope/spec: [Chrome core UAT execution](2026-07-20-chrome-core-uat-execution.md) and [final-answer grounding plan](../superpowers/plans/2026-07-21-final-answer-grounding-and-coverage-boundary.md)

## Reported

- Chrome UAT reported that direct 4th/5th-generation annual-limit questions retrieved the intended source pages and figures, but the visible answer exposed OCR fragments and `chunk=...` / `source=...` metadata.
- The coverage-boundary question reported an unsupported statement that no 5th-generation evidence existed, including internal Graph review text.
- The user requested a separation between local-LLM limitations and application defects, then a codebase-level diagnostic if necessary.

## Observed

### Current runtime and persisted evidence

- `GET http://127.0.0.1:18080/api/health` returned `{"status":"ok"}` after the diagnostic run. No extra `.../.venv/bin/python -` diagnostic process remained.
- `insurance_chat.db` persisted the Chrome UAT turns and the later diagnostic turns through the same message/audit path.
- Direct 5th-generation annual-limit UAT turns `345/346` and `347/348` both returned the deterministic clause-detail template, including `chunk=표준약관_ch_005435, source=text`; their audit rows (`514`, `515`) record temperature `0.0`.
- Earlier repeated turns `271/272` and `275/276` did begin with the correct `200만원` conclusion, but both still appended `【claim_condition_review】 직접 연결된 판단 조건 경로를 찾지 못했습니다.` They are not full UAT passes.
- The codebase-level diagnostic repeated `5세대 MRI 연간 보장되나요?` in separate new sessions at `0.1` temperature (turns `357/358`, `359/360`; audit rows `520`, `521`). The two visible answers differed in wording yet both asserted unsupported 4th-generation inheritance and `300만원` for 5th generation. Their persisted public sources were the same broad, mixed set (consultation casebook p.236/p.100/p.108, own-product material p.303, standard policy p.332), not the direct 5th-generation MRI clause.
- The diagnostic process was a cold, separate Python import. It logged a reranker CUDA OOM and disabled that duplicate reranker. It is therefore valid only as a qualitative repeated-output record, not as a latency or retrieval-ranking benchmark. It did not leave a process or change operational GraphDB, ontology, raw data, or active calculation rules.

### Code path evidence

- `src/api/rag_service.py:397-415` returns one undifferentiated `deterministic_answer` string after retrieval/evidence assessment.
- `src/api/routes/chat.py:771-790` streams that non-null string without calling the LLM. Therefore the direct annual-limit raw dump is not an LLM quality failure.
- `src/rag/pipeline.py:1494-1553` constructs the visible deterministic clause-detail response and explicitly inserts `chunk=<id>` and `source=<kind>`.
- `src/rag/pipeline.py:1639-1665` calls the generic clause-detail guard before the response layer knows whether the question is a pure attribute lookup or a coverage/payout judgment. This lets a numerical limit template answer a decision-shaped question.
- `src/graph/context.py:245-329` renders Graph review/clarification content into the model prompt even when there are no grounded facts. In the failed coverage turn, Graph facts and Graph source chunk IDs were empty while a missing-path review summary was available to the model.
- `src/api/rag_service.py:1136-1161` only strips known rendered templates or exact missing-summary lines after generation; it cannot prove or repair an unsupported substantive model claim.
- Existing tests intentionally expect debug provenance in a user-answer string, for example `tests/test_pipeline.py` asserts `chunk=...` in the clause-detail answer. This preserves the defect rather than testing the user-visible contract.

## Not Verified

- The diagnostic store does not persist an exact model prompt, sampling seed, or raw hidden reasoning. We cannot prove that the two model outputs had byte-identical prompts, so the observed variation must not be attributed solely to sampling.
- No direct 5th-generation coverage/exclusion decision profile was approved for this topic. The fix must not invent one, promote a candidate ontology item, rebuild GraphDB, or change active calculation rules.
- No post-fix runtime/Chrome validation has been run; implementation and independent review are still required.

## Findings

1. **P0 — answer authority is lost before final rendering.** A single free-text deterministic answer is used for direct attributes, generic clause details, and decision-shaped questions. The route cannot preserve whether the text is a grounded attribute result, a conditionally grounded coverage answer, or an insufficient-evidence fallback.
2. **P0 — user-visible renderer leaks internal provenance.** The deterministic renderer deliberately exposes chunk IDs and source implementation kinds, and it renders OCR-sized rows instead of a concise conclusion.
3. **P0 — ungrounded coverage questions are delegated to the LLM with internal Graph review content.** The resulting LLM answer can make unsupported cross-generation claims. Low-temperature repetition shows output variability, but the application supplied mixed evidence and did not enforce a grounded decision boundary.
4. **P1 — audit observability cannot distinguish the final answer authority.** It records route/temperature but not a safe `answer_origin` / `grounding_state`, making future diagnosis depend on manual message inspection.
5. **P2 — the one-off diagnostic duplicated the in-process reranker.** It must not become the routine test mechanism; code-level regression tests should use the normal request assembly with fixtures/mocks and retain production-safe audit fields.

## Decision

`DEVELOPER_FIXBACK`

The observed failures require a minimal architecture fix: an evidence/intent-aware answer disposition, a public deterministic renderer, and a fail-closed coverage boundary. The work must remain generic and must not contain MRI-specific amounts, generation-specific hardcoding, active calculation-rule edits, GraphDB rebuilds, ontology approvals, raw-data edits, or model replacement/tuning as the primary remedy.

## Dispatch

Target: new isolated DGX Developer task `developer_final_answer_grounding`.

Exact prompt to send:

> Project: `/Users/june_kim/Projects/insurance-rag-chatbot`; implement in an isolated DGX `muldae` workspace based on current protected `master` `3353fea`, never in the shared checkout. Read this immutable triage record and the linked implementation plan first. Implement only the final-answer authority/grounding boundary: distinguish source-grounded pure attributes/comparisons, source-grounded conditional coverage decisions, insufficient-evidence coverage fallbacks, and ordinary LLM answers; render deterministic answers in concise public language without chunk IDs/source implementation labels/OCR dumps; prevent Graph missing-review text from becoming model answer context; add safe audit fields identifying answer origin/grounding state; add regression tests using generic fixtures and the UAT failure class. Do not hardcode MRI values or any generation-specific answer, do not modify active calculation rules, manifests, GraphDB, ontology approvals, raw documents, users, sessions, or UI source hover/click behavior. Do not stage, commit, push, restart services, or run destructive operations. Provide an implementation report under `docs/`, exact changed files, focused/full test commands and outputs, and a completion marker for independent review.
