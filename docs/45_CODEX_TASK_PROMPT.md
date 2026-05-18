# Codex Task Prompt — #45

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer implementing two targeted improvements to an insurance document OCR pipeline. This is a multi-step task. Before each tool call, provide a one-line status update.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/45_CODEX_SPEC_TABLE_MULTIHEADER_VISION.md` before writing any code.

## Goal

Deliver two improvements to table parsing quality for a RAG document database pipeline:

1. **Multi-level header detection** in `_table_to_json()` (`src/parser/clova_ocr.py`): auto-detect when a CLOVA table has a 2-row header (merged row + sub-header row) and use the sub-header values as actual column names. Currently `수술종수 / 수술종수_2 / 수술종수_3` should become `1-3종 / 1-5종 / 신1-5종`.

2. **Vision LLM table cleaner** (`src/parser/table_vision_cleaner.py`): new module that crops each table region from the page image and sends it to Claude Vision API to detect figure/diagram cells and replace their OCR text with `[그림]`. Integrate via `--vision-clean` flag in both run scripts.

Full technical detail (algorithm, prompt, integration) is in `docs/45_CODEX_SPEC_TABLE_MULTIHEADER_VISION.md`.

## Success criteria

- Manual one-liner check in the spec passes with `PASS` (multi-level header returns `['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']`)
- `pytest -q` passes with zero failures (≥ 190 tests)
- `python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 64 --vision-clean` completes without error
- p064 output shows `headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']` and figure cells marked `[그림]`
- `block.raw["vision_cleaned"] == True` for cleaned table blocks

## Constraints

- Do **not** modify `src/parser/ocr_engine.py` or any other `src/` file not listed in the spec
- Load `.env` using `Path(__file__).resolve().parents[N] / ".env"` — do **not** use `find_dotenv()`
- Use `openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))` — **not** Anthropic. The OpenAI client must be instantiated in the run script and passed into `clean_table_blocks()` — do not create it inside the module
- `--vision-clean` defaults to `False`; existing runs without the flag must behave identically to today
- Vision API failures must be handled gracefully (log warning, keep original table_json, continue)
- Do **not** commit JSON result files or HTML files

## Execution order

Implement and validate in this order to isolate failures:

1. Part 1 (multi-level header) → run `pytest tests/test_clova_ocr.py -v` before proceeding
2. Part 2 (vision cleaner module + tests) → run `pytest tests/test_table_vision_cleaner.py -v`
3. Integration into run scripts → run full `pytest -q`
4. End-to-end test with `--vision-clean` on p064

## Output

Write `docs/45_TABLE_MULTIHEADER_VISION_REPORT.md` containing:
1. Changed files with one-line description per function
2. Manual one-liner output (must show `PASS`)
3. Full `pytest -q` output
4. Before/after comparison of p064 headers and first data row
5. `vision_cleaned` field value from p064 output
6. Remaining blockers (write "None" if clean)

Then commit and push to `origin/master`.

## Stop rules

- Any existing test fails after Part 1 → stop, report, do not proceed to Part 2
- `LayoutBlock` structure change required to implement cleaner → stop and report
- OpenAI API returns 401 → stop and report (OPENAI_API_KEY missing or invalid in .env)
- Run script behavior changes when `--vision-clean` is NOT passed → stop and report
