# Source citation PDF click restoration: Review Team handoff

## Scope

- Review only. Do not edit, stage, commit, push, merge, tag, deploy, restart, reindex, rebuild GraphDB, or write operational data.
- Inspect the actual isolated DGX workspace and its diff; do not rely only on this summary.
- Protected main and port `18080` must remain untouched.

## Immutable baseline and workspace

- Baseline: `3a8b6af06a359b72cbe903dcffc4b24f19c062aa`
- Isolated workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-source-citation-click-20260720`
- Protected main: `/srv/shared/projects/insurance-rag-chatbot`

## Intended behavior

1. Existing source-chunk hover preview remains intact.
2. A complete PDF citation badge is keyboard-accessible and opens the registered original PDF in a new tab/window at `#page=N`.
3. The new same-origin endpoint requires authentication and `chat.stream` permission.
4. The endpoint resolves only configured `src.config.PDF_SOURCES`; traversal, unknown, missing, non-PDF, ambiguous, or unauthorized requests fail closed.
5. New-tab opener access is blocked; special characters are URL encoded.
6. Non-PDF and incomplete citations remain non-clickable.
7. No RAG answer logic, ontology, GraphDB, calculation rule, model, or operational data change is allowed.

## Actual changed paths

- `frontend/css/chat.css`
- `frontend/dist/app.min.js`
- `frontend/js/pages/chat.js`
- `src/api/routes/chat.py`
- `tests/test_api_source_pdf.py`
- `tests/test_frontend_source_preview_settings.mjs`
- `docs/282_SOURCE_CITATION_CLICK_IMPLEMENTATION_REPORT.md`

## Planner re-verification evidence

- `git diff --check`: PASS
- `git diff --summary`: no mode or rename changes
- `find frontend -maxdepth 1 -type l -print`: empty; temporary `node_modules` symlink removed
- `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q tests/test_api_source_pdf.py tests/test_api_chat_stream.py`: `45 passed`
- `node --test tests/test_frontend_source_preview_settings.mjs tests/test_frontend_assistant_display.mjs`: `11 passed`
- Focused endpoint-only test: `3 passed`
- Focused source-badge test: `6 passed`

## Required independent checks

- Inspect source and generated bundle diffs for consistency.
- Re-run the focused tests from the isolated workspace using the protected repository venv read-only.
- Confirm auth and `chat.stream` permission boundaries.
- Confirm only allowlisted configured PDFs can be served inline as `application/pdf`.
- Confirm Unicode-normalized identifiers, traversal rejection, unknown/missing/non-PDF fail-closed behavior.
- Confirm hover preview, focus preview, click/keyboard activation, `target=_blank`, `noopener noreferrer`, `#page=N`, URL encoding, and non-PDF disabled behavior.
- Check that a source object without the fields required by the current public payload cannot become a misleading clickable badge.
- Confirm no unintended file mode changes, symlink residue, deployment changes, or out-of-scope answer/ontology/Graph/calculation changes.
- State whether isolated browser-level validation is still required before promotion.

## Verdict contract

Return exactly one verdict:

- `PASS`: no blocker; safe to prepare promotion subject to Planner integration/deployment authorization.
- `CHANGES_REQUIRED`: list concrete file/behavior/test findings and the smallest fixback scope.
- `BLOCKED`: state the exact inaccessible evidence or environment dependency.
