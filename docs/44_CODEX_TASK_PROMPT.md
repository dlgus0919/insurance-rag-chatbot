# Codex Task Prompt — #44

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer working on an insurance document OCR pipeline. This is a multi-step task. Before each tool call, provide a one-line status update so the reviewer can follow your progress.

## Goal

Verify that our CLOVA OCR endpoint supports native table detection, then re-run the OCR pipeline and regenerate the HTML comparison viewer so the reviewer can see the native table results in their browser.

Full technical detail is in `docs/44_CODEX_SPEC_NATIVE_TABLE_VERIFY_RERUN.md`. Read it before writing any code.

## Three-phase execution — run phases in order, stop if Phase 1 fails

**Phase 1 — Endpoint verification (REQUIRED FIRST)**
Write and run `scripts/verify_native_table.py` to test whether the CLOVA endpoint returns a non-empty `tables[]` array when `enableTableDetection: True` is sent. Use `p066_original.png` (a page known to contain tables). Exit 0 = tables present, Exit 1 = tables absent.

**Phase 2 — Re-run OCR (only if Phase 1 exits 0)**
Re-run `scripts/run_clova_local.py --doc 실무가이드 --pages 60-70` then `scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 60-70` to overwrite the existing JSON reports with v43 results.

**Phase 3 — Regenerate HTML viewer (only if Phase 2 completes)**
Write and run `scripts/generate_ocr_html.py --doc 실무가이드` to produce `reports/ocr_compare_v43_review.html`. The viewer must visually distinguish native CLOVA tables (`raw.native_table == true`) from geometric reconstructions.

## Success criteria

- `scripts/verify_native_table.py` exits 0 AND prints `tables_found=True`
- Both OCR re-runs complete with all 11 pages SUCCESS
- `p066_true_hybrid.json` contains at least one block with `raw.native_table == true`
- `reports/ocr_compare_v43_review.html` exists and is non-empty

## Constraints

- Do **not** modify any file under `src/` or `tests/`
- Do **not** modify `scripts/run_clova_local.py` or `scripts/run_true_hybrid_local.py`
- Load `.env` using `Path(__file__).resolve().parents[1] / ".env"` — do NOT use `find_dotenv()`
- Do **not** commit JSON result files or the HTML file — commit only the two new `.py` scripts
- All three phases must be attempted in order; if Phase 1 exits 1, stop and report immediately

## Output

When done (or stopped early), report:
1. **Phase 1 result** — paste the exact terminal output of `verify_native_table.py` including exit code
2. **Phase 2 result** — page-by-page SUCCESS/FAIL counts for each script (paste the run output)
3. **Phase 3 result** — path and file size of the generated HTML
4. **native_table block count** — output of the one-liner check in the spec's success criteria table
5. **Remaining blockers** — write "None" if all phases completed cleanly

Then commit the two new scripts and push to `origin/master`.

## Stop rules

Stop immediately and report if:
- Phase 1 exits 1 — paste the raw API response or error, note that the endpoint may not support `enableTableDetection`, and do not proceed to Phase 2 or 3
- Either OCR re-run script exits with an unrecoverable error after the built-in retries
- You need to modify files outside the two new scripts to make things work
