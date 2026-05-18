# Codex Task Prompt — #46

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer implementing two independent improvements to an insurance document RAG pipeline. Each part must be validated before moving to the next.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/46_CODEX_SPEC_NUMERIC_CELL_REFINER.md` before writing any code.

## Role

Senior Python developer. Reviewer is Claude. Operator is the human user. You implement; Claude checks correctness and completeness.

## Goal

**Part 1 — Numeric cell Vision refiner**: Add `src/parser/numeric_cell_refiner.py` with `refine_numeric_cells()`. It identifies table rows where ALL 수술종수-type columns (`1-3종`, `1-5종`, `신1-5종`, `수술종수*`) are blank, crops the table region from the page image, and uses OpenAI Vision API (`gpt-4o-mini`) to recover the actual numeric values. Integrate into `--vision-clean` in both run scripts. Add `✏️ 숫자 정제` badge in `generate_ocr_html.py`.

**Part 2 — Streamlit Cloud index fix**: Add `scripts/build_cloud_index.py` to rebuild cloud-only ChromaDB + BM25 from the committed `chunks.jsonl`. Add `REBUILD_INDEX_FROM_CHUNKS` env var support in `scripts/bootstrap_assets.py`. The root cause of the cloud search failure for `자사_SOL건강` and `자사_SOL운전자` is a stale ChromaDB zip — these two docs were added to chunks/BM25 in commit `b730b4a` but the deployed ChromaDB was never rebuilt.

## Success Criteria

**Part 1:**
- `pytest tests/test_numeric_cell_refiner.py -v` passes with ≥ 4 new tests
- `pytest -q` passes with ≥ 197 total tests, 0 failures
- `python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 68 --vision-clean` succeeds
- p068 output contains `block.raw["numeric_refined"] == True` and at least one 수술종수 column value is non-blank where it was previously blank
- Running without `--vision-clean` produces identical output to current behavior

**Part 2:**
- `python scripts/build_cloud_index.py` completes without error
- After running, `python scripts/check_cloud_index.py` shows `자사_SOL건강` and `자사_SOL운전자` with vector count > 0
- `REBUILD_INDEX_FROM_CHUNKS=true python scripts/bootstrap_assets.py` prints rebuild completion message
- Existing tests pass (no regressions from new scripts)

## Constraints

- Do **not** modify `src/parser/ocr_engine.py`, `src/parser/clova_ocr.py`, or `src/config.py`
- Load `.env` using `Path(__file__).resolve().parents[N] / ".env"` — do **not** use `find_dotenv()`
- Use `openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))` — instantiate in the run script and pass into `refine_numeric_cells()`; do not create it inside the module
- `--vision-clean` flag default remains `False`; runs without the flag must be identical to current behavior
- Vision API failures must be handled gracefully (log WARNING, keep original block, continue)
- Do **not** commit `data/index/chroma/`, any JSON result files, or HTML files
- `scripts/build_cloud_index.py` must not be invoked automatically at test time; wrap its `main()` under `if __name__ == "__main__"`
- `bootstrap_assets.py` must preserve existing `INDEX_RELEASE_URL` logic unchanged when `REBUILD_INDEX_FROM_CHUNKS` is not set

## Execution Order

Implement and validate in this order to isolate failures:

1. **Part 1a** — implement `src/parser/numeric_cell_refiner.py` and `tests/test_numeric_cell_refiner.py`
   - Run: `pytest tests/test_numeric_cell_refiner.py -v` → all pass before continuing
2. **Part 1b** — integrate into run scripts and `generate_ocr_html.py`
   - Run: `pytest -q` → 0 failures before continuing
3. **Part 1c** — end-to-end test on p068 with `--vision-clean`
4. **Part 2a** — implement `scripts/check_cloud_index.py` and run it (document the "before" state)
5. **Part 2b** — implement `scripts/build_cloud_index.py` with `rebuild_from_chunks()`
6. **Part 2c** — update `scripts/bootstrap_assets.py` with `REBUILD_INDEX_FROM_CHUNKS` support
7. **Part 2d** — validate: run `build_cloud_index.py`, then `check_cloud_index.py` (document "after" state)

## Output

Write `docs/46_NUMERIC_REFINER_CLOUD_REPORT.md` containing:
1. Changed files with one-line description per function
2. Full `pytest -q` output (total pass count)
3. p068 수술종수 column before/after comparison
4. `check_cloud_index.py` output — before and after rebuild
5. Sample of `block.raw["numeric_corrections"]` from p068
6. Remaining blockers (write "None" if clean)

Then commit and push to `origin/master`.

## Stop Rules

- Any existing test fails after Part 1a → stop, report, do not proceed to Part 1b
- `LayoutBlock` structure change required → stop, report
- `src/parser/ocr_engine.py` / `src/parser/clova_ocr.py` / `src/config.py` modification required → stop, report
- Running without `--vision-clean` changes current behavior → stop, report
- OpenAI API returns 401 → raise `NumericCellRefinerAuthError`, include in report (do not continue end-to-end test)
- Embedding model unavailable during Part 2b → `build_cloud_index.py` prints a clear error and exits non-zero; do not modify app code; document in report and continue with remaining steps
