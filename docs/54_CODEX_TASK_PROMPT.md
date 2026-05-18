# Codex Task Prompt — #54

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python developer building a search quality evaluation suite for an insurance document RAG pipeline.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/54_CODEX_SPEC_EVAL_QA.md` before writing any code. Also read `scripts/eval.py` and `eval/smoke_qa.jsonl` in full to understand the existing evaluation framework.

## Role

Senior Python developer. You create the OCR Q&A evaluation dataset and extend the eval script. Reviewer is Claude. Operator is the human user.

## Goal

### Task 1 — Create `eval/ocr_qa.jsonl`

Write ≥40 evaluation items covering the two OCR-processed documents:

- `실무가이드` (doc_short: `실무가이드`) — surgery grade tables, disability rate tables, procedure descriptions, disability criteria text
- `상담사례집` (doc_short: `상담사례집`) — consultation case content

**CRITICAL**: For every `surgery_grade` item, read the actual OCR table file from `data/extracted/실무가이드/tables/` to verify the exact 1-3종/1-5종/신1-5종 values. Do NOT guess. The manifest is at `data/extracted/실무가이드/manifest.json`.

Use the item list in `docs/54_CODEX_SPEC_EVAL_QA.md` section 4 as your guide. Items #10–#12 and all `consultation` expected_keywords must be derived from actual OCR file content.

Format (one JSON per line):
```json
{"question": "...", "expected_pages": [64], "expected_codes": [], "type": "surgery_grade", "doc_sources": ["실무가이드"], "expected_grades": {"1-3종": "1", "1-5종": "2", "신1-5종": "2"}}
{"question": "...", "expected_pages": [255], "expected_codes": [], "type": "disability_rate", "doc_sources": ["실무가이드"], "expected_rate": "60"}
{"question": "...", "expected_pages": [65], "expected_codes": [], "type": "consultation", "doc_sources": ["상담사례집"], "expected_keywords": ["키워드1", "키워드2"]}
```

### Task 2 — Extend `scripts/eval.py`

Add `--ocr` flag and the following:

1. Load `eval/ocr_qa.jsonl` when `--ocr` is passed
2. Add three helper functions:
   - `answer_mentions_expected_grades(answer, expected_grades) -> tuple[int, int]`
   - `answer_mentions_expected_rate(answer, expected_rate) -> bool`
   - `answer_mentions_expected_keywords(answer, expected_keywords) -> tuple[int, int]`
3. Accumulate per-type metrics: `grade_correct_total/grade_total`, `rate_hits/rate_evaluated`, `keyword_correct/keyword_total`
4. Print additional metrics: `수술종수 정확도`, `장해 지급률 정확도`, `키워드 포함율`
5. Exit 1 if recall < 0.70, or grade_accuracy < 0.60, or rate_accuracy < 0.70

See `docs/54_CODEX_SPEC_EVAL_QA.md` section 5 for exact function signatures.

## Success Criteria

- `wc -l eval/ocr_qa.jsonl` ≥ 40
- type distribution: surgery_grade ≥ 10, disability_rate ≥ 10, consultation ≥ 4
- `python -c "import json; [json.loads(l) for l in open('eval/ocr_qa.jsonl')]"` — no errors
- `pytest -q` → 0 failures
- `python scripts/eval.py --ocr` runs without crash (LLM unavailable is acceptable — print "Ollama unavailable, skipping LLM evaluation" and report retrieval-only metrics)
- `python scripts/eval.py` and `python scripts/eval.py --v2` still pass (no regression)
- All `expected_grades` values verified against actual `data/extracted/실무가이드/tables/` files

## Constraints

- Do NOT modify `eval/smoke_qa.jsonl` or `eval/smoke_qa_v2.jsonl`
- Do NOT modify any file under `src/`
- Do NOT modify `scripts/ingest.py`, `scripts/run_full_ocr.py`
- `expected_grades` must be verified from OCR table files — no fabrication

## Execution Order

1. **Read** `scripts/eval.py` in full
2. **Read** `eval/smoke_qa.jsonl` to understand existing format
3. **Read** `data/extracted/실무가이드/manifest.json` — identify table file paths for surgery-grade pages
4. **Read** actual table files for pages 7, 64, 107, 108, 109, 167 — extract correct grade values
5. **Read** OCR text files for disability pages 232, 236, 242, 245, 247, 251, 255, 257, 262, 264 — extract correct rates
6. **Read** OCR text files for 상담사례집 pages 65, 101, 189, 273 — extract keywords
7. **Write** `eval/ocr_qa.jsonl` (≥40 items, all values verified)
8. **Validate** `eval/ocr_qa.jsonl` with `python -c "import json; ..."` 
9. **Edit** `scripts/eval.py` — add `--ocr` flag and new metrics
10. **Run** `pytest -q` → 0 failures
11. **Run** `python scripts/eval.py --ocr` (if Ollama available) or report retrieval-only
12. **Run** `python scripts/eval.py` → verify no regression
13. **Write** `docs/54_EVAL_QA_REPORT.md`
14. **Commit and push** to `origin/master`

## Output

Write `docs/54_EVAL_QA_REPORT.md` containing:
1. Q&A 문항 분포표 (type별 건수)
2. `python scripts/eval.py --ocr` 전체 출력
3. `python scripts/eval.py` 기존 smoke 결과 (회귀 확인)
4. MISS 문항 분석 (검색 실패 원인)
5. 개선 권장사항
6. 잔여 블로커 ("None" 또는 구체적 내용)

Commit and push to `origin/master`.

## Stop Rules

- Any existing test fails → stop, report
- `eval/smoke_qa.jsonl` is modified → restore and stop
- `expected_grades` cannot be verified from OCR files (file missing) → note which items and use `"expected_grades": null` as placeholder, report
- Ollama connection error → skip LLM eval, continue to write JSONL + extend eval.py + report retrieval-only metrics
