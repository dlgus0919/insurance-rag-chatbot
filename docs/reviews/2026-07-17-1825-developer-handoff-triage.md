# Developer Handoff Triage

- Timestamp: 2026-07-17 18:25 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: not routed because known implementation defects remain
- Design: `docs/superpowers/specs/2026-07-17-fifth-generation-policy-source-authority-design.md`
- Plan: `docs/superpowers/plans/2026-07-17-fifth-generation-policy-source-authority.md`

## Reported

The user knows that a fifth-generation indemnity-policy document is registered in raw data, but the current UI says the selected fifth-generation basis is a standard policy and that no fifth-generation own-company product policy is registered. The user asked for the recommended action's impacts and possible defects to be predicted, a concrete plan to be prepared, and implementation to be dispatched to Developer.

## Observed

- The DGX raw inventory contains the fifth-generation standard-policy PDF and the ShinhanEZ fourth-generation own-company indemnity-policy PDF.
- The live processed inventory contains 384 own-policy chunks tagged `4th` and 856 standard-policy chunks tagged `5th`.
- Five fifth-generation hair-loss clause chunks are retrievable; the deterministic direct source is `표준약관_ch_005453`, p.296–309.
- The latest fifth-generation answer therefore retrieved a registered fifth-generation standard-policy clause successfully. It was not a missing-document retrieval fallback.
- `src/rag/source_grounded_answers.py::_authority_note()` uses the ontology profile's static `standard_reference_note` whenever selected direct chunks are not marked as own-company.
- `data/ontology/concepts.json` statically says that no fifth-generation own-company product policy is registered. Runtime does not verify current inventory before making that assertion.
- Current standard-policy chunks may have `is_own_company=None`, so a safe immediate fix must recognize standard authority by `product_type` or `doc_short` as well as by the explicit false value that future ingest will produce.
- `PdfSource.policy_generation` was previously introduced but is absent from current `src/config.py`. Existing indexes retain generation metadata, but a future full ingest can omit it and cause the generation filter to exclude fifth-generation clauses.
- `src/parser/chunker.py` already lists `policy_generation` as an extended metadata field, so restoring the source configuration plus regression coverage is sufficient for future propagation.
- Historical answers that said the fifth-generation official document was unavailable predate the current deterministic release and remain stored in the same session; historical messages are not regenerated.
- The broad standard-policy compilation is blanket-tagged as fifth generation. The hair-loss section at p.296 is in the fifth-generation indemnity section, but document-wide section classification has not been proven.
- The local planning checkout is at stale `0ad60f1` and contains multiple pre-existing untracked planning/triage documents. It must not be used as the implementation base. The latest verified DGX release baseline is `origin/master` at `cd82f9e`.

## Not Verified

- The proposed patch has not been implemented or tested yet.
- No current index, GraphDB, service, or production conversation database has been changed.
- The full 856-chunk standard-policy compilation has not been section-classified.
- No fifth-generation own-company product-policy absence claim is treated as a verified runtime invariant.

## Findings

1. **P1 — future full-ingest generation loss:** `PdfSource.policy_generation` is missing from current source configuration. The running index masks this regression because old metadata remains.
2. **P2 — misleading authority message:** a static ontology string converts “selected evidence is a standard policy” into an unverified own-policy absence assertion.
3. **P2 — mixed-source overclaim:** the current `any(is_own_company)` rule can label a mixed own+standard evidence set as own-only.
4. **P2 — active-manifest staleness:** changing only the base ontology string may not affect an existing active manifest; runtime must stop consuming the stale field.
5. **P3 — deferred data-model risk:** blanket fifth-generation tagging of the broad standard-policy compilation can produce unrelated generation matches outside the verified fifth-generation section.

## Impact Forecast

- The bounded patch improves user-facing provenance and prevents the next ingest from losing generation metadata without changing current retrieval rankings.
- Existing exact-string snapshots may fail and must be updated to authority-contract assertions.
- Existing indexed `is_own_company=None` values remain until reindex, so fallback standard-source detection is required.
- Old and new answers will retain different wording in chat history. This is intentional to preserve audit history.
- Avoiding reindex prevents broad index drift and downtime, but leaves document-wide section tagging as a separately tracked risk.
- Future addition of a fifth-generation own policy will be represented correctly only if authority is derived from selected chunk metadata rather than the old static profile sentence.

## Decision

`DEVELOPER_FIXBACK`

Implement the bounded metadata-driven authority patch and restore future-ingest metadata configuration. Do not perform section-level reclassification, reindexing, GraphDB rebuild, historical-message rewrite, rule approval, protected-main mutation, service restart, commit, or push in this dispatch.

## Dispatch

Send exactly one implementation prompt to Developer thread `019eaf4a-6338-7812-bf3b-663df7d83d4f`. Developer must start from a fresh isolated `muldae` workspace based on current `origin/master`, follow the linked design and plan, use TDD, write the next non-conflicting implementation report, run focused and feasible full tests, and return changed files, validation evidence, workspace status, impact assessment, and remaining risks with completion marker `DEVELOPER_FIFTH_POLICY_AUTHORITY_FIX_COMPLETE`.
