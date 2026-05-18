# Codex Task Prompt — #50

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer fixing a word-ordering bug in a CLOVA OCR post-processing module for an insurance document RAG pipeline.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/50_CODEX_SPEC_OCR_WORD_ORDER_FIX.md` before writing any code. Also read `src/parser/clova_ocr.py` in full to understand the current implementation.

## Role

Senior Python developer. Fix the `_fields_to_lines()` and `_group_fields_into_rows()` functions in `src/parser/clova_ocr.py`. Write tests in `tests/test_clova_word_order.py`. Do **not** run the full OCR pipeline — a smoke test with 2 pages is sufficient.

## Goal

Fix two related functions in `src/parser/clova_ocr.py`:

1. **`_fields_to_lines()`** — Remove the `lineBreak` flag-based line splitting. Replace with Y-coordinate gap-based splitting (same approach as `_group_fields_into_rows()`). Add an adaptive `row_gap` parameter (default `None`) that auto-computes from the median field height × 0.6 (minimum 8px).

2. **`_group_fields_into_rows()`** — Change the hardcoded `row_gap=20.0` default to `row_gap: float | None = None`, and auto-compute it the same way as above when `None`.

The bug: CLOVA sets `lineBreak=True` on each line's last token in CLOVA's own internal ordering. But `_fields_to_lines()` re-sorts fields by (center_Y, center_X) before checking `lineBreak`. After re-sorting, a `lineBreak=True` token can appear mid-line, causing premature line splits. Words from different visual lines get merged into one line, while single visual lines get split across multiple lines.

## Success Criteria

- `pytest tests/test_clova_word_order.py -v` passes with ≥ 5 tests
- `pytest -q` passes with 0 failures (≥ 211 tests total)
- Given a mock field set where `lineBreak=True` is in the middle of a visual line (after Y-sort), `_fields_to_lines()` correctly outputs one line — not two
- Given a mock field set with fields whose center_Y differs by less than row_gap, they are grouped into one line
- `_group_fields_into_rows()` uses adaptive row_gap when called without arguments

## Constraints

- Do **not** modify `src/parser/ocr_engine.py`, `src/parser/ocr_chunker.py`, `src/parser/table_vision_cleaner.py`, `src/parser/numeric_cell_refiner.py`, `src/config.py`, `scripts/ingest.py`, `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`, `scripts/run_full_ocr.py`
- The `row_gap` parameter in both functions must default to `None` (not a hardcoded float) so that the adaptive calculation runs automatically
- Existing callers of `_fields_to_lines()` and `_group_fields_into_rows()` pass no arguments for `row_gap` — backward compatibility must be preserved
- `reconstruct_table_from_fields()` passes an explicit `row_gap` float to `_group_fields_into_rows()` — keep that call working (explicit float still works fine)
- Tests must not call the CLOVA API; use mock field dicts only

## Execution Order

1. **Read** `src/parser/clova_ocr.py` in full
2. **Fix** `_fields_to_lines()`: remove `lineBreak`, add Y-gap logic with adaptive `row_gap`
3. **Fix** `_group_fields_into_rows()`: change `row_gap=20.0` to `row_gap: float | None = None`, add adaptive calculation
4. **Write** `tests/test_clova_word_order.py` with ≥ 5 tests using the `make_field()` helper
5. **Run** `pytest tests/test_clova_word_order.py -v` → all pass
6. **Run** `pytest -q` → 0 failures
7. **Smoke**: `python scripts/run_full_ocr.py --doc 실무가이드 --pages 71,81 --force --yes`
8. **Verify**: `data/extracted/실무가이드/text/p071_b*.txt` and `p081_b*.txt` do not contain stray page numbers ("71", "81") embedded mid-sentence

## Output

Write `docs/50_WORD_ORDER_FIX_REPORT.md` containing:
1. Modified functions (one-line description each)
2. `pytest -q` output
3. `pytest tests/test_clova_word_order.py -v` output
4. Before/After comparison: run `_fields_to_lines()` on a test field set that triggers the bug; show old output vs. new output
5. Remaining blockers ("None" if clean)

Commit and push to `origin/master`.

## Stop Rules

- Any existing test fails → stop, report
- `reconstruct_table_from_fields()` breaks after `_group_fields_into_rows()` change → stop, report
- Smoke: CLOVA API network error → note it in report, continue (sandbox network restriction is expected)
