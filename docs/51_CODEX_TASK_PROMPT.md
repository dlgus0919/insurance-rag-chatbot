# Codex Task Prompt — #51

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer fixing two OCR post-processing bugs in an insurance document RAG pipeline, then running tests, re-running OCR on problem pages, generating a comparison HTML, and writing a report.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/51_CODEX_SPEC_OCR_ORDER_REFINER_FIX.md` before writing any code. Also read `src/parser/clova_ocr.py` and `src/parser/numeric_cell_refiner.py` in full.

## Role

Senior Python developer. You fix two bugs, write new unit tests, re-run OCR on specific pages, generate a comparison HTML report, and write a markdown report. Reviewer is Claude. Operator is the human user.

## Goal

### Fix 1 — `_fields_to_lines()` in `src/parser/clova_ocr.py`

**Problem**: After Y-gap grouping, words within the same visual line are re-sorted by `center_X`. This destroys CLOVA's original reading order. For closely-spaced words where bounding box X precision is off, the sort swaps adjacent words ("원칙적으로"/"각각", "생기고"/"다른").

**Evidence**: Both True Hybrid and CLOVA native paths show the same word-pair swaps on p255, proving the bug is in `_fields_to_lines()`, not PP-Structure.

**Fix**: Within each Y-group, use the field's **original index in the input `fields` list** (CLOVA's own reading order) instead of `center_X` for ordering. Y-coordinates are still used for line-boundary detection only.

Implementation:
```python
def _fields_to_lines(fields: list[dict], row_gap: float | None = None) -> str:
    if not fields:
        return ""
    # Sort by Y only — keep original CLOVA index for within-line order
    indexed = sorted(enumerate(fields), key=lambda pair: _field_center_y(pair[1]))
    if row_gap is None:
        row_gap = _adaptive_row_gap([f for _, f in indexed])

    lines: list[list[str]] = []
    current_line: list[tuple[int, str]] = []  # (original_index, text)
    prev_y: float | None = None

    for orig_idx, field in indexed:
        text = str(field.get("inferText", "")).strip()
        cy = _field_center_y(field)
        if prev_y is not None and (cy - prev_y) > row_gap:
            if current_line:
                current_line.sort(key=lambda x: x[0])  # restore CLOVA order
                lines.append([t for _, t in current_line if t])
            current_line = []
        if text:
            current_line.append((orig_idx, text))
        prev_y = cy

    if current_line:
        current_line.sort(key=lambda x: x[0])
        lines.append([t for _, t in current_line if t])

    return "\n".join(" ".join(line) for line in lines)
```

Do **NOT** change `_group_fields_into_rows()` — that function is used for table column reconstruction where `center_X` ordering is correct.

### Fix 2 — `numeric_cell_refiner.py`: corrections-only delta format

**Problem**: Current prompt asks the Vision LLM to echo the entire `table_json` (17 rows with long surgery descriptions) with `_corrections` embedded. This exceeds `max_tokens=3072`, causing truncated JSON and `_same_table_shape_allow_metadata` validation failure. CLOVA native p064 shows `numeric_refined: False` as a result.

**Fix**: Change the prompt to ask for a compact corrections-only delta:
```json
{
  "corrections": [{"row_index": 0, "col": "1-3종", "to": "1", "confidence": "high"}],
  "unresolved": [{"row_index": 2, "col": "신1-5종", "reason": "not_readable"}]
}
```

Changes required:
1. Replace `VISION_PROMPT` — remove table_json echo, add delta format requirement, replace `__TABLE_JSON__` placeholder with `__CANDIDATE_ROWS__` (summary only: row_index + 수술명[:50] + current values)
2. Replace `_build_prompt()` — pass candidate row summary instead of full table_json
3. Replace `_parse_with_retry()` — use `_is_valid_delta()` check instead of `_same_table_shape_allow_metadata`
4. Replace `_extract_valid_corrections_and_unresolved()` — read from `delta["corrections"]` and `delta["unresolved"]` directly
5. Set `max_tokens=512` (delta format is very compact)

The full implementation specs are in `docs/51_CODEX_SPEC_OCR_ORDER_REFINER_FIX.md` section 4-2.

## Success Criteria

- `pytest tests/test_clova_field_order.py -v` passes with ≥ 4 tests
- `pytest tests/test_numeric_refiner_delta.py -v` passes with ≥ 3 tests
- `pytest -q` passes with 0 failures (≥ 219 tests)
- All 5 existing tests in `tests/test_clova_word_order.py` still pass
- Given fields where CLOVA order is A→B but center_X(B) < center_X(A), `_fields_to_lines()` returns "A B" (not "B A")
- p064 CLOVA native re-run shows `numeric_refined: True` with corrections applied
- `reports/ocr_method_compare_v51.html` exists and contains all 11 page sections
- p255 HTML blocks show "원칙적으로 각각" (not "각각 원칙적으로")

## Constraints

- Do **not** modify `src/parser/ocr_engine.py`, `src/parser/ocr_chunker.py`, `src/parser/table_vision_cleaner.py`, `src/config.py`, `scripts/ingest.py`, `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`
- Do **not** modify `_group_fields_into_rows()` — only `_fields_to_lines()`
- The `_same_table_shape_allow_metadata` function can be kept (it's used nowhere else after this fix) or removed — do not break anything
- OCR re-runs write to `reports/full_ocr_method_compare_v51/` — do **not** overwrite `data/extracted/`
- If CLOVA API is unreachable in the sandbox, note it in the report and generate the HTML from whatever data was produced

## Execution Order

1. **Read** `src/parser/clova_ocr.py` in full
2. **Read** `src/parser/numeric_cell_refiner.py` in full
3. **Fix** `_fields_to_lines()` in `clova_ocr.py`
4. **Write** `tests/test_clova_field_order.py` (≥ 4 tests, including the "inverted X" test)
5. **Run** `pytest tests/test_clova_field_order.py tests/test_clova_word_order.py -v` → all pass
6. **Fix** `numeric_cell_refiner.py` (VISION_PROMPT, `_build_prompt`, `_parse_with_retry`, `_extract_valid_corrections_and_unresolved`, max_tokens)
7. **Write** `tests/test_numeric_refiner_delta.py` (≥ 3 tests)
8. **Run** `pytest tests/test_numeric_refiner_delta.py -v` → all pass
9. **Run** `pytest -q` → 0 failures (full regression)
10. **Re-run OCR** — True Hybrid + CLOVA native, 실무가이드 pages 64,65,68,74,151,255,279 and 상담사례집 pages 65,189,211,273, both into `reports/full_ocr_method_compare_v51/`
11. **Generate HTML** — `reports/ocr_method_compare_v51.html` with before/after text blocks and table rendering
12. **Verify checklist**:
    - p255 True Hybrid: "원칙적으로 각각" correct order?
    - p255 CLOVA native: same?
    - p064 CLOVA native: `numeric_refined: True` with ≥ 5 corrections?
    - p068, p074, p151: quality maintained?
13. **Write** `docs/51_OCR_ORDER_REFINER_REPORT.md`
14. **Commit and push** to `origin/master`

## Output

Write `docs/51_OCR_ORDER_REFINER_REPORT.md` containing:
1. Modified functions (one-line description each)
2. `pytest -q` output
3. `pytest tests/test_clova_field_order.py tests/test_numeric_refiner_delta.py -v` output
4. Before/After comparison for `_fields_to_lines()` on the p255 word-swap test case
5. p064 CLOVA native: corrections count before (0) vs. after (≥ 5), list of row_index + col corrected
6. HTML verification checklist results
7. Remaining blockers ("None" if clean)

Commit and push to `origin/master`.

## Stop Rules

- Any existing test fails → stop, report
- `_group_fields_into_rows()` was accidentally modified and table tests fail → stop, report
- `reconstruct_table_from_fields()` produces wrong column assignment after the fix → stop, report
- CLOVA 401 during OCR re-runs → stop, report
- Network error (sandbox restriction) during OCR → note in report, skip to HTML generation with available data
