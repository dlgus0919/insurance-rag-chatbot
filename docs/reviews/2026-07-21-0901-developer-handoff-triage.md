# Developer Handoff Triage

- Timestamp: 2026-07-21 09:01 KST
- Cycle: grounded-attribute-composite-quickcode-20260721-0901
- Project root: protected runtime `/srv/shared/projects/insurance-rag-chatbot`; local coordination checkout `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: to be created for this cycle
- Review Team thread: to be created after Developer completion
- Scope/spec: `docs/superpowers/plans/2026-07-21-grounded-attribute-and-composite-quickcode.md`; source analysis `docs/reviews/2026-07-21-chrome-smoke-root-cause-analysis.md`

## Reported

- The Chrome smoke exposed two final-answer defects: a selected policy limit was rendered as neighboring OCR amounts, and a named-procedure fee code disappeared when the same question requested a coverage judgment.
- The user requested a minimal general fix, Developer implementation, and a re-smoke after the implementation path is validated.

## Observed

- The protected DGX checkout is clean at `ba214dac5bd3aaba0361db2bad5eed508a794c79`, equal to its `origin/master`; the currently running FastAPI process serves this checkout on `127.0.0.1:18080`.
- `_direct_policy_attribute_hits()` in `src/rag/pipeline.py:2278` selects a number and creates `display_evidence`, but stores its wide compact OCR window as `Hit.document`. `_extract_clause_detail_text_rows()` reparses that document for a direct hit, and `_public_clause_detail_numbers()` at line 1546 returns the first two money values without attribute semantics.
- `_build_clause_detail_evidence_answer()` switches to comparison formatting solely on `len(rows) > 1`, not on an explicit distinct-generation comparison axis.
- `_HIRA_TERM_PATTERN` at `src/rag/pipeline.py:185` permits only a closed set of procedure suffixes. `_extract_hira_lookup_terms()` consequently misses procedure names that are followed by an explicit fee cue but have another valid suffix.
- The raw HIRA source contains the tested procedure/code row. `resolve_specialized_coverage_disposition()` at `src/api/rag_service.py:422` returns an independent coverage disposition, and the stream uses it before LLM generation; the code component is currently not composed with that result.
- The local coordination checkout is on `master`, two documentation commits ahead of its remote and has pre-existing modified/untracked UAT and review documents. It is not the protected runtime source baseline, so it must not be used for code edits in this cycle.

## Not Verified

- No implementation candidate exists yet.
- No full regression run has been performed for this change.
- No protected-main promotion, service restart, or post-change Chrome smoke is authorized or performed by this routing event.

## Findings

1. **P1 — selected policy attribute value loses semantic identity.** Evidence: `src/rag/pipeline.py:2278-2343`, `1138-1218`, `1546-1607` in protected runtime. Required resolution: preserve the selected value into a direct row and render it without reparsing neighboring OCR values.
2. **P1 — coverage safety gate erases independent source-backed fee information.** Evidence: `src/rag/pipeline.py:185,285-354`; `src/api/rag_service.py:422-452`. Required resolution: validate a generic name-before-fee-cue phrase against raw HIRA rows and compose that component with, never into, the unchanged coverage disposition.
3. **P1 — checkout mismatch risk.** Evidence: local `HEAD=a48ec11`, protected runtime `HEAD=ba214da`. Required resolution: implement only in a new remote isolated worktree based on `ba214da`.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

Target: `/root/developer_grounded_composite`.

Prompt sent: implement the two scoped contracts in a new remote worktree based on protected `ba214da`; preserve the selected direct attribute value into a direct display row, and compose a raw-HIRA-validated fee component with the unchanged fail-closed coverage disposition. Add the specified generic regressions, run focused and full pytest, save an immutable candidate completion record, and do not stage, commit, push, merge, restart, reindex, rebuild, or alter protected runtime state.
