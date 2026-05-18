# Codex Task Prompt — #43

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer implementing a targeted bug fix and feature addition in an insurance document OCR pipeline. This is a multi-step task. Before each tool call, provide a one-line status update so the reviewer can follow your progress.

## Goal

Make the smallest coherent set of changes that achieves all of the following:

1. Fix a silent data-loss bug in `_cell_words_text()` (`src/parser/clova_ocr.py`) caused by wrong dictionary key names
2. Enable CLOVA's native table detection by adding `"enableTableDetection": True` to the API payload
3. Route table parsing through the native `tables[]` array when it is present, falling back to the existing geometric approach when it is absent
4. Fix the corresponding test fixture keys and add two new targeted tests

Full technical detail is in `docs/43_CODEX_SPEC_CLOVA_NATIVE_TABLE.md`. Read it before writing any code.

## Success criteria

- `pytest tests/test_clova_ocr.py -v` passes with **zero failures**, including 2 new tests you add
- `pytest -q` passes with **zero failures** across the full test suite (≥ 186 tests)
- `python -c "import src.parser.clova_ocr; print('import OK')"` exits cleanly
- Calling `_cell_words_text({"cellTextLines": [{"cellWords": [{"inferText": "테스트"}]}]})` returns `"테스트"` (verify this with a one-liner in the shell)

## Constraints

- Do **not** modify any file outside `src/parser/clova_ocr.py` and `tests/test_clova_ocr.py`
- Do **not** call the real CLOVA API — all tests must use monkeypatching or mocks
- Do **not** delete `reconstruct_table_from_fields()` — it remains as the fallback path
- Do **not** change the signature or return type of `clova_ocr_page()`
- Do **not** change `_table_to_json()`'s signature

## Output

When done, report:
1. **What changed** — list every function you modified or added, with a one-sentence description
2. **Validation performed** — paste the terminal output of each test/check run
3. **Remaining blockers** — anything that could not be completed and why (write "None" if clean)

Then commit with message: `fix(clova): enable native table detection, fix _cell_words_text keys (#43)` and push to `origin/master`.

## Stop rules

Stop immediately and report if:
- Any existing test fails after your changes (do not attempt to suppress or skip)
- You need to modify a file outside the two listed above to make tests pass
- You are unsure whether the CLOVA API endpoint supports `enableTableDetection` at runtime (note it in your report rather than removing the flag — the flag is confirmed supported)
