# Hospital Receipt Claim Batch Evaluation Design

> Status: Historical design for the recorded `v1.0.22` batch run. It is not a compatibility claim for the current runtime.

## Context

Target app version: `v1.0.22`

Target DGX repository: `/srv/shared/projects/insurance-rag-chatbot`

Sample source:

- `data/hospital_receipts/manual_20260609/input/`
- `data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json`

The manual extraction file currently contains 155 `claim_items`. Its summary says 153 items are ready for auto calculation and 2 require review. Earlier OCR A-D tests concluded that OCR-generated `claim_items_ready` is 0, so this evaluation must not use OCR output as the calculation input.

## Goal

Run the current claim calculation logic against every manually extracted hospital receipt detail item and produce a practitioner-friendly grading package.

The package must let a practitioner grade each line item without reading JSON.

## Non-Goals

- Do not re-run or improve OCR.
- Do not use LLM/VLM to infer missing numbers, coverage decisions, deductibles, or payable amounts.
- Do not change production calculation rules during this test.
- Do not manually enter 155 rows through the browser UI.

## Approaches Considered

### Approach A: One Case-Level Batch Calculation Through the Current Calculation Engine

Run all 155 items as one claim case, then flatten `line_results` into a spreadsheet.

Pros:

- Closest to a real hospital receipt claim.
- One request/result contains total amount, total deductible, total payable amount, and line-level details.
- Easy for practitioners to grade line-by-line.
- Minimal moving parts.

Cons:

- It primarily tests the calculation engine, not every browser interaction.
- If one input mapping issue affects many rows, the result spreadsheet needs careful review.

Decision: use this as the primary path.

### Approach B: Per-Line Calculation

Run one calculation per item and produce 155 independent outputs.

Pros:

- Easier to isolate a single row failure.
- Smaller response per run.

Cons:

- Less realistic than one claim case.
- Slower and noisier.
- Totals and cross-line behavior are harder to judge.

Decision: keep only as a later diagnostic option if the case-level run is hard to interpret.

### Approach C: Browser UI Manual Entry

Use the app UI and enter all rows.

Pros:

- Tests the exact frontend path.

Cons:

- Too slow for 155 rows.
- High risk of manual input mistakes.
- Poor repeatability.

Decision: do not use for the main evaluation. Use UI only to spot-check that the app is reachable.

## Recommended Design

Create one operational test runner that:

1. Reads `manual_extraction/claim_calculation_input.json`.
2. Builds one claim calculation payload with all 155 items.
3. Uses the current default generation (`5th`) unless the input explicitly requests another supported generation.
4. Runs the current calculation logic.
5. Writes machine-readable output and a practitioner grading workbook.

The runner should store all outputs under:

`reports/claim_batch/manual_20260609/<timestamp>_v1.0.22/`

## LLM and App Runtime Handling

The default model for the current app is `sglang:qwen3-next-80b-a3b-instruct-fp8`.

The evaluation should start or verify:

- default SGLang model server
- FastAPI app on `http://127.0.0.1:18080`

However, claim calculation itself must remain deterministic. The LLM server is part of the current app environment check, not a source of numeric decisions.

If the LLM server fails to start, the test should stop before producing practitioner grading files. This avoids mixing an app-readiness failure with a claim-calculation result.

## Output Package

The result directory should contain:

- `input_payload.json`: normalized request sent into the calculation path
- `claim_response.json`: full calculation result
- `line_results.csv`: one row per calculation line
- `practitioner_scoring.xlsx`: spreadsheet for practitioner grading
- `summary.json`: totals, counts, app version, model, elapsed time
- `README.md`: how the run was produced and how to grade it

The spreadsheet should contain these columns:

- source page/file
- source row id
- item group
- service date
- input code
- item name
- claimed amount
- insured copay amount
- nonpay amount
- calculated category
- deductible
- payable amount
- calculation status
- requires review
- review reasons
- rule summary
- practitioner grade
- practitioner comment
- corrected category
- corrected payable amount

## Success Criteria

- 155 input rows are included.
- The run records the current app version and default model.
- One claim-level result and one line-level grading sheet are produced.
- Every line result is traceable back to the manual extraction source row.
- Review-required rows are visible in the spreadsheet.
- The output does not include unmasked patient identifiers.

## Risks

- The manual extraction is a curated input, not OCR automation. The report must label it as such.
- Current generation support is `4th` and `5th`; this test should use `5th` as the default.
- Some rows may be classified as review-required because contract coverage, accident type, or facility grade is not fully known from hospital documents.
- A line-level payable amount is an expected calculation output, not a final claim approval.

## Design Self-Review

- Placeholder scan: no placeholder requirements remain.
- Scope check: this is one bounded evaluation workflow, not an OCR or rule-change project.
- Consistency check: the design uses the existing manual extraction file and existing claim calculation engine only.
- Ambiguity check: the main run is a single claim case with all 155 items; per-line runs are deferred.
