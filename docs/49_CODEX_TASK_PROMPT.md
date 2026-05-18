# Codex Task Prompt — #49

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer building a production OCR pipeline that processes all pages of two scanned insurance documents and stores results in a format compatible with the existing RAG indexing pipeline.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/49_CODEX_SPEC_FULL_OCR_INGEST.md` before writing any code. Also read `src/parser/ocr_chunker.py` and `scripts/run_true_hybrid_local.py` to understand the expected file formats and the existing OCR pipeline before writing any code.

## Role

Senior Python developer. You implement a new `scripts/run_full_ocr.py` script and tests. You do NOT run the full 681-page OCR job — only smoke tests. The human operator will run the full job after reviewing your implementation.

## Goal

Create `scripts/run_full_ocr.py` that:

1. Takes `--doc` (실무가이드 | 상담사례집 | all), optional `--pages`, `--vision-clean`, `--force`, `--timeout`, `--yes` flags.
2. For each page: runs True Hybrid OCR (PP-Structure layout → CLOVA API) using the existing `src/parser/` modules directly (do NOT import from `scripts/run_true_hybrid_local.py`).
3. Optionally applies Vision LLM table cleaning and numeric cell refinement when `--vision-clean` is set.
4. Saves each block to `data/extracted/{doc}/text/p{NNN}_b{II}.txt` or `data/extracted/{doc}/tables/p{NNN}_t{II}.txt` + `.json`.
5. Updates `data/extracted/{doc}/manifest.json` **after every page** (resumable on interruption).
6. Skips pages already recorded as `engine="true_hybrid"` in the manifest (unless `--force`).
7. Prints per-page progress and a final summary.

## Success Criteria

- `pytest tests/test_run_full_ocr.py -v` passes with ≥ 4 tests
- `pytest -q` passes with 0 failures (≥ 201 tests)
- `python scripts/run_full_ocr.py --doc 실무가이드 --pages 64 --yes` completes successfully
- After smoke test: `data/extracted/실무가이드/manifest.json` contains `page_no=64` with `engine="true_hybrid"`
- After smoke test: `data/extracted/실무가이드/text/` or `tables/` has new `p064_*` files
- Resume test: running `--pages 64-65` a second time shows p064 as SKIPPED, p065 as new
- Chunker test: `chunk_from_extracted('실무가이드', ...)` returns chunks with `source_method` containing `"true_hybrid"`
- Running without `--vision-clean` does NOT call any OpenAI API

## Constraints

- Do **not** modify `src/parser/ocr_chunker.py`, `src/parser/ocr_engine.py`, `src/parser/clova_ocr.py`, `src/config.py`, or `scripts/ingest.py`
- Do **not** import from `scripts/run_true_hybrid_local.py` or `scripts/run_clova_local.py` — use `src/parser/` modules directly
- Load `.env` using `Path(__file__).resolve().parents[1] / ".env"` — do **not** use `find_dotenv()`
- OpenAI client must be instantiated in the script and passed to `clean_table_blocks()` and `refine_numeric_cells()` — not created inside those modules
- `--vision-clean` defaults to False; runs without the flag must not call any OpenAI endpoint
- Show a cost warning and require `--yes` (or `CI=true` env) before starting `--vision-clean` runs with more than 10 pages
- Do **not** commit `data/extracted/` content files or `data/index/` files
- Manifest must be saved to disk after every successfully processed page (not only at the end)

## Execution Order

1. **Read** `src/parser/ocr_chunker.py` to understand manifest format exactly
2. **Read** `scripts/run_true_hybrid_local.py` to understand the True Hybrid OCR call sequence
3. **Implement** `scripts/run_full_ocr.py` core logic: page loop, `_save_blocks()`, `_update_manifest()`, `_is_page_done()`
4. **Implement** `tests/test_run_full_ocr.py` with ≥ 4 unit tests (mock CLOVA/OCR)
5. **Run** `pytest tests/test_run_full_ocr.py -v` → all pass
6. **Run** `pytest -q` → 0 failures
7. **Smoke test**: `python scripts/run_full_ocr.py --doc 실무가이드 --pages 64 --yes`
8. **Verify** manifest + file output
9. **Resume test**: run pages 64-65 again, confirm p064 SKIPPED
10. **Chunker test**: confirm `chunk_from_extracted` works on updated manifest

## Output

Write `docs/49_FULL_OCR_INGEST_REPORT.md` containing:
1. Changed/created files (one-line description per function)
2. `pytest -q` output
3. Smoke test result: manifest entry for p064, file listing
4. Resume test result
5. Chunker integration test result
6. Full-run operator instructions (exact command, estimated time, post-run ingest command)
7. Remaining blockers ("None" if clean)

Commit and push to `origin/master`.

## Stop Rules

- Any existing test fails → stop, report
- `src/parser/ocr_chunker.py` modification required to make chunker work with new manifest → stop, report the format mismatch in detail
- Smoke test: manifest.json is corrupted or unreadable after run → stop, report
- CLOVA API 401 during smoke test → stop, report
- `run_ppstructure` import fails (PaddleOCR not installed in env) → write the script anyway, note the import error in the report; do not modify the core modules to work around it
