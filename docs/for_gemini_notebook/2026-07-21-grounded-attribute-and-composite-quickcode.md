# Grounded Attribute and Composite Quick-code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct deterministic final answers so a selected policy attribute renders only its selected value, and a source-backed fee-code result survives an independent fail-closed coverage judgment in the same question.

**Architecture:** Keep the existing deterministic-answer and coverage-gate boundaries. A direct policy hit will carry the already-selected value into the display row instead of reparsing its wider OCR context. For a composite fee-code and coverage request, a verified HIRA fee component is rendered alongside—not instead of—the existing coverage disposition; the coverage disposition remains the only authority for a coverage conclusion.

**Tech Stack:** Python 3.12, FastAPI streaming API, pytest, existing raw HIRA chunks and approved policy-source retrieval.

## Global Constraints

- Work only in a new isolated remote worktree created from deployed `/srv/shared/projects/insurance-rag-chatbot` revision `ba214da`; first record that the deployed checkout is clean and at that revision.
- Do not change active calculation rules, GraphDB, ontology approvals, raw/OCR documents, source indexes, prompt text, LLM/model settings, or user-facing policy copy unrelated to the two response contracts.
- Do not special-case `MRI`, `식도조루술`, or any particular insurer/product. Tests may use generic fixture labels; production behavior must be based on the selected direct value and exact HIRA raw-row validation.
- A fee code may be stated only when a HIRA source row contains the extracted term or explicit code. It must never make a coverage decision or promote unapproved GraphDB values.
- Preserve existing fail-closed behavior: no approved coverage evidence must still produce the existing insufficient-evidence coverage conclusion, with no LLM call.
- Do not stage, commit, push, merge, rebuild/reindex, restart the protected application, or change the running `18080` service during this task.

---

## File Structure

- Modify: `src/rag/pipeline.py` — preserve selected direct-attribute values in deterministic rows; derive verified HIRA fee components from the existing raw-row lookup.
- Modify: `src/api/rag_service.py` — compose a verified fee component with the existing coverage disposition without changing the coverage decision.
- Modify: `tests/test_pipeline.py` — regression coverage for wide OCR windows, selected-value rendering, and generic named fee procedures.
- Modify: `tests/test_api_rag_service_payload.py` — composition contract and no-unapproved-coverage assertion.
- Modify: `tests/test_api_chat_stream.py` — streaming path keeps both components and still bypasses the LLM for insufficient coverage evidence.
- Create: `docs/reviews/2026-07-21-<HHMM>-grounded-attribute-composite-implementation.md` — Developer completion record with worktree/revision, diff summary, and exact test results.

### Task 1: Render only the already-selected direct policy value

**Files:**
- Modify: `src/rag/pipeline.py:1546-1607, 2278-2343`
- Modify: `tests/test_pipeline.py:1673-1738`

**Interfaces:**
- Consumes: `Hit.metadata["direct_policy_attribute"]`, `display_evidence`, selected `re.Match` from `_select_policy_attribute_number()`.
- Produces: direct-hit metadata keys `direct_policy_attribute_value: str` and `direct_policy_attribute_categories: tuple[str, ...]`; `ClauseDetailEvidenceRow` values that contain only the selected attribute value for a direct hit.
- Preserves: `_public_clause_detail_numbers(question, numbers)` for non-direct rows and the existing direct-hit selection/ranking behavior.

- [ ] **Step 1: Write failing selected-value and comparison-shape tests**

```python
def test_direct_attribute_answer_uses_selected_value_not_neighboring_ocr_amounts() -> None:
    chunk = Chunk(
        id="direct-limit",
        text="검사X 공제 3만원, 인접 시술 한도 350만원, 검사X 연간 한도 300만원",
        metadata={
            "doc_short": "약관",
            "page_start": 71,
            "page_end": 71,
            "policy_generation": "4th",
            "direct_policy_attribute": True,
            "direct_policy_attribute_value": "300만원",
            "direct_policy_attribute_categories": ("limit",),
            "display_evidence": "검사X의 1년간 보상한도는 300만원입니다.",
        },
    )
    answer = _deterministic_clause_detail_answer(
        "4세대 검사X의 연간 보상한도는?", [chunk], policy_generation="4th"
    )
    assert "300만원" in answer
    assert "3만원" not in answer
    assert "350만원" not in answer
    assert "비교 결과" not in answer
```

Add a second test with two direct rows of the same `policy_generation` and a single-generation question. It must not select comparison formatting merely because two rows exist. Keep a distinct 4th/5th explicit-comparison test passing to prove cross-generation comparison remains available.

- [ ] **Step 2: Run tests to verify the current path fails**

Run: `pytest tests/test_pipeline.py -q -k 'direct_attribute_answer_uses_selected_value or direct_policy_attribute'`

Expected: the new answer test fails because the display row is rebuilt from a wide OCR hit and returns neighboring money values.

- [ ] **Step 3: Implement the minimal direct-value carry-through**

In `_direct_policy_attribute_hits`, persist the selected result at the point it is chosen:

```python
direct_metadata["direct_policy_attribute"] = True
direct_metadata["direct_policy_attribute_value"] = selected_number.group(0)
direct_metadata["direct_policy_attribute_categories"] = tuple(categories)
direct_metadata["display_evidence"] = _raw_display_window(...)
```

In the text-row extractor, take an early direct-hit branch only when all three direct metadata fields are valid. Build one `ClauseDetailEvidenceRow` whose `text` is the bounded `display_evidence`, whose `numbers` is `[direct_policy_attribute_value]`, and whose `source_kind` is `"direct_policy_attribute"`; then continue without splitting `chunk.text`. If the metadata is missing or malformed, retain the existing generic fallback unchanged.

In `_build_clause_detail_evidence_answer`, choose comparison formatting only when the question explicitly requests two or more generations **and** the displayed direct rows have distinct `policy_generation` values. For a selected single generation, render its one direct row even if generic retrieval supplied duplicate same-generation rows.

- [ ] **Step 4: Run focused regressions**

Run: `pytest tests/test_pipeline.py -q -k 'direct_policy_attribute or selected_value or policy_attribute_lookup'`

Expected: PASS. The generic fixture proves that the selected value is not replaced by an adjacent deductible or another procedure's limit.

### Task 2: Compose verified fee information with the fail-closed coverage result

**Files:**
- Modify: `src/rag/pipeline.py:185, 285-354`
- Modify: `src/api/rag_service.py:422-452`
- Modify: `tests/test_pipeline.py:87-199, 474-490`
- Modify: `tests/test_api_rag_service_payload.py:624-665`
- Modify: `tests/test_api_chat_stream.py:476-550`

**Interfaces:**
- Produces: `build_source_grounded_hira_fee_answer(question: str, graph_context: str | None = None) -> str | None` in `src/rag/pipeline.py`.
- Consumes: `_build_hira_fee_context()` and `build_hira_fee_answer()`; the latter remains the sole formatter for raw HIRA evidence rows.
- Produces: `resolve_specialized_coverage_disposition()` text that contains both a fee component and its existing coverage component when both were requested and the fee component is source-backed.

- [ ] **Step 1: Write failing exact-HIRA and composite-disposition tests**

```python
def test_hira_fee_context_extracts_named_procedure_before_fee_cue(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "_load_hira_chunks", lambda: [{
        "text": "Q2333 식도조루술 Esophagostomy 1,234.00점",
        "metadata": {"doc_short": "심평원", "source_file": "수가표.pdf", "page_start": 531},
    }])
    answer = build_source_grounded_hira_fee_answer("식도조루술 수가 코드와 실손 보상 여부를 알려줘")
    assert answer is not None
    assert "Q2333" in answer
```

Add a service test that monkeypatches this new helper to return `Q2333` and supplies no approved coverage evidence. Assert the final disposition contains both `Q2333` and the existing insufficient-evidence wording, and does not contain an unapproved `면책`/`지급` conclusion. Add an API-stream test asserting `_generate_llm_stream` is not called in this case.

- [ ] **Step 2: Run tests to verify the current behavior fails**

Run: `pytest tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q -k 'named_procedure_before_fee_cue or composite_fee or specialized_coverage'`

Expected: the named-procedure test fails because the old suffix-only extraction does not identify the procedure, and the composite result lacks the fee code.

- [ ] **Step 3: Implement exact, source-backed composition**

Add a fee-intent pattern which extracts the concise procedure phrase immediately before `수가`, `수가코드`, `수가표`, `점수`, `심평원`, or `수술코드`. Normalize and deduplicate it through the same HIRA raw-row matching used by `_build_hira_fee_context`. Retain `_HIRA_TERM_PATTERN` as a fallback; do not add a list entry for any named procedure.

Expose the existing raw-row route through:

```python
def build_source_grounded_hira_fee_answer(
    question: str,
    graph_context: str | None = None,
) -> str | None:
    return build_hira_fee_answer(question, _build_hira_fee_context(question, graph_context))
```

In `resolve_specialized_coverage_disposition`, compute this component only for an explicit fee intent. When it is non-empty and the question also needs coverage judgment, create a new `AnswerDisposition` retaining the existing `origin`, `grounding_state`, and `source_chunk_ids`, with text in this order:

```text
수가 정보
<verified HIRA component>

실손 보상 판단
<existing disposition text>
```

If no raw HIRA row validates the fee component, leave the coverage disposition unchanged. Do not use GraphDB candidate values, `pay_opinion`, an LLM, or a default code as a substitute.

- [ ] **Step 4: Run focused regressions and contract checks**

Run: `pytest tests/test_pipeline.py tests/test_source_grounded_answers.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q`

Expected: PASS. The composite case contains a HIRA-backed code and an unchanged fail-closed coverage decision, while non-fee coverage questions remain unchanged.

### Task 3: Verify the candidate without touching the protected application

**Files:**
- Create: `docs/reviews/2026-07-21-<HHMM>-grounded-attribute-composite-implementation.md`

**Interfaces:**
- Consumes: candidate worktree diff and focused test evidence from Tasks 1–2.
- Produces: an immutable Developer completion record for independent review.

- [ ] **Step 1: Inspect the candidate diff and change boundary**

Run: `git diff --check && git diff -- src/rag/pipeline.py src/api/rag_service.py tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py`

Expected: only the planned code/tests and one immutable report are present; no data, active rule, ontology, GraphDB, frontend bundle, or prompt files change.

- [ ] **Step 2: Run the full test suite in the candidate worktree**

Run: `pytest -q`

Expected: PASS. If an unrelated pre-existing failure occurs, record it verbatim and do not hide it with skip/xfail.

- [ ] **Step 3: Save the completion record**

Record the deployed base revision, candidate worktree path and branch, modified files, focused/full commands with counts, no-LLM composite assertion, and any unrun verification. State explicitly that protected-main promotion, restart, and Chrome re-smoke were not performed.

- [ ] **Step 4: Leave the candidate ready for independent review**

Do not stage, commit, push, merge, restart, or remove the candidate worktree. Report the exact worktree path and completion-record path to the Planner.

## Self-Review

- Spec coverage: Task 1 fixes the selected-value and false-comparison contract; Task 2 fixes named HIRA extraction and preserves the independent coverage boundary; Task 3 records candidate evidence and preserves the promotion gate.
- Boundary coverage: no task changes raw data, active calculation rules, GraphDB, ontology approvals, prompts, or running services. The two supplied example terms occur only in tests that prove generic behavior, not in production mapping data.
- Placeholder scan: all code/test changes have concrete file paths, signatures, assertions, and commands. The completion report timestamp is intentionally generated once at execution to preserve immutable-record naming.
- Type consistency: the only new public helper returns `str | None`; the service consumes exactly that type and retains the pre-existing `AnswerDisposition` fields.

## Execution Handoff

This plan is to be executed by the dedicated Developer in an isolated DGX worktree. The Planner will inspect the completion record and route an independent read-only review before any protected-main promotion or Chrome re-smoke.
