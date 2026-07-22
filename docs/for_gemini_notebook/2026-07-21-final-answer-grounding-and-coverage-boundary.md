# Final Answer Grounding and Coverage Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make final user-visible answers derive from an explicit, provenance-gated answer disposition so direct policy attributes are concise and coverage/payout questions never become unsupported model judgments.

**Architecture:** Keep retrieval, Graph payload, and UI citations separate from the text shown in the assistant bubble. Retrieval produces a typed disposition that records whether a source-grounded deterministic answer is safe, whether a coverage decision has direct evidence, or whether the system must ask for facts without deciding. The chat route uses the disposition to select deterministic rendering or an ordinary LLM path, and audit records retain only safe origin/state metadata.

**Tech Stack:** Python 3, FastAPI/SSE, existing RAG pipeline/GraphDB payload, SQLite audit logging, pytest, existing frontend display tests.

## Global Constraints

- Preserve the 000 principle: implement a generic evidence-and-intent contract, not MRI-specific text, amounts, generation branches, or test-only special cases.
- Do not alter active calculation rules, calculation manifests, GraphDB contents, ontology approvals, raw documents, user/session data, service configuration, or model selection/tuning.
- Preserve source hover/click and page navigation: public source payloads retain document/page/chunk lookup data; only answer-body text must omit internal identifiers.
- Never treat a missing Graph path as proof that a policy document is absent.
- Do not store or display raw hidden reasoning, full prompts, credentials, or internal source implementation metadata.
- Work in an isolated `muldae` workspace; do not stage, commit, push, restart a service, rebuild/reindex, or promote artifacts.

## Failure Contract

The following question classes define the contract; implementation must generalize by intent and source provenance rather than by their literal wording.

| Class | Required final-answer behavior | LLM authority |
| --- | --- | --- |
| Pure policy attribute (`검사X의 연간 보상한도는?`) | First sentence gives the selected-source answer; optional condition and human-readable page reference only; no OCR dump or `chunk=` / `source=`. | Not used when direct selected-source evidence exists. |
| Generation comparison (`A세대와 B세대 검사X의 연간 보상한도를 비교해줘`) | Compare only when both selected-generation source facts are directly grounded. If one side is missing, say comparison cannot be completed from registered direct sources. | Not used for a grounded comparison. |
| Coverage/action (`검사X 연간 보장되나요?`, `검사X 보상한도 지급 여부는?`) | Never treat a numeric limit as an automatic coverage/payout decision. Render a direct, conditional clause result only when direct coverage/exclusion evidence exists; otherwise say the decision cannot be confirmed and ask only the missing factual conditions. | Must not generate a coverage/payout conclusion when the disposition is insufficient. |
| Ordinary explanation | Use the existing LLM route with grounded chunks. Internal Graph review text must not be part of its prompt. | Allowed, subject to existing final display normalization. |

## File Map

| File | Responsibility after change |
| --- | --- |
| `src/rag/pipeline.py` | Classify search intent, select grounded rows, and produce a typed answer disposition rather than only an opaque deterministic string. |
| `src/api/rag_service.py` | Carry the disposition through retrieval preparation, build safe public deterministic text, keep Graph review payload UI-only, and normalize display text. |
| `src/api/routes/chat.py` | Select deterministic vs. LLM streaming from the disposition and record safe audit fields. |
| `src/graph/context.py` | Provide a prompt-safe graph context containing only grounded facts/clarification instructions, never missing-path review summaries or UI templates. |
| `tests/test_pipeline.py` | Verify generic source/intent disposition and public deterministic rendering. |
| `tests/test_api_rag_service_payload.py` | Verify Graph review separation and final display normalization. |
| `tests/test_api_chat_stream.py` | Verify streaming path, persisted audit fields, and no LLM call for insufficient decision evidence. |
| `tests/test_search_intent.py` | Preserve the pure-attribute vs. coverage/action boundary. |
| `docs/` implementation report | Record scope, files, test results, and non-goals. |

---

### Task 1: Define the answer disposition at the retrieval boundary

**Files:**
- Modify: `src/rag/pipeline.py`
- Modify: `src/api/rag_service.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_api_rag_service_payload.py`

**Interfaces:**
- Produces an immutable `AnswerDisposition` with `origin`, `grounding_state`, `text`, and `source_chunk_ids` fields.
- `origin` is one of `policy_attribute`, `policy_comparison`, `coverage_grounded`, `coverage_insufficient`, `clause_detail`, or `llm`.
- `grounding_state` is one of `direct`, `conditional`, `insufficient`, or `none`.
- `prepare_retrieved_context(...)` returns the disposition instead of a bare `deterministic_answer` string, while preserving existing chunks, public sources, Graph payload, warnings, and debug return values.

- [ ] **Step 1: Write focused failing tests for disposition selection**

```python
def test_policy_attribute_disposition_is_direct_and_public() -> None:
    chunk = make_chunk(
        doc_short="약관A",
        text="검사X의 연간 보상한도는 123만원 이내입니다.",
        metadata={"policy_generation": "alpha", "page_start": 12},
    )

    disposition = resolve_answer_disposition(
        "검사X의 연간 보상한도는?", [chunk], search_intent=classify_search_intent("검사X의 연간 보상한도는?")
    )

    assert disposition.origin == "policy_attribute"
    assert disposition.grounding_state == "direct"
    assert disposition.text.startswith("선택한 alpha 기준")
    assert "123만원" in disposition.text
    assert "chunk=" not in disposition.text
    assert "source=" not in disposition.text


def test_coverage_question_does_not_reuse_limit_disposition() -> None:
    chunk = make_chunk(
        doc_short="약관A",
        text="검사X의 연간 보상한도는 123만원 이내입니다.",
        metadata={"policy_generation": "alpha", "page_start": 12},
    )

    disposition = resolve_answer_disposition(
        "검사X는 연간 보장되나요?", [chunk], search_intent=classify_search_intent("검사X는 연간 보장되나요?")
    )

    assert disposition.origin == "coverage_insufficient"
    assert disposition.grounding_state == "insufficient"
    assert "123만원" not in (disposition.text or "")
```

- [ ] **Step 2: Run the focused tests and confirm the missing interface fails**

Run: `pytest tests/test_pipeline.py -k 'disposition or coverage_question_does_not_reuse_limit' -v`

Expected: FAIL because the typed disposition resolver does not exist yet.

- [ ] **Step 3: Implement one typed resolver and preserve existing retrieval behavior**

```python
@dataclass(frozen=True)
class AnswerDisposition:
    origin: Literal[
        "policy_attribute", "policy_comparison", "coverage_grounded",
        "coverage_insufficient", "clause_detail", "llm",
    ]
    grounding_state: Literal["direct", "conditional", "insufficient", "none"]
    text: str | None
    source_chunk_ids: tuple[str, ...] = ()


def resolve_answer_disposition(
    question: str,
    chunks: list[Chunk],
    *,
    search_intent: SearchIntentPlan,
    policy_generation: str | None,
    graph_result: Any | None = None,
    table_store: TableStore | None = None,
) -> AnswerDisposition:
    if search_intent.requires_coverage_judgment:
        grounded = _render_direct_coverage_disposition(question, chunks, policy_generation)
        return grounded or _coverage_insufficient_disposition(question, policy_generation)
    return _resolve_non_decision_disposition(question, chunks, search_intent, policy_generation, graph_result, table_store)
```

Implementation requirements:

- Use the existing selected-generation metadata and evidence-assessment contracts; do not create document-name, amount, or generation literal branches.
- Keep surgery-grade and HIRA guards working by returning an equivalent `AnswerDisposition` with the appropriate non-LLM origin.
- Treat direct decision evidence as sufficient only when the selected source has an explicit coverage/exclusion condition for the queried concept. A numeric ceiling, deductible, or period row alone is insufficient.
- Use a single public renderer that emits `결론 → 적용 조건(있을 때만) → 근거 문서/쪽` and never serializes chunk IDs, source kinds, row IDs, OCR table blobs, Graph status strings, or debug fields.
- For an insufficient coverage/payout decision, return a concise deterministic fallback that says no decision can be confirmed from directly grounded evidence and requests only the relevant case facts. It must not claim a selected policy document is missing.
- Keep ordinary non-decision clause-detail answers grounded, but make their source reference public-readable rather than implementation-readable.

- [ ] **Step 4: Pass the disposition through `prepare_retrieved_context`**

Replace the opaque return element with the typed disposition and derive `search_intent` from the same retrieval/debug result used to choose chunks. If a valid evidence-assessment result already has a canonical display answer, create a disposition with the profile's direct/conditional state rather than bypassing it.

- [ ] **Step 5: Run the focused tests**

Run: `pytest tests/test_pipeline.py -k 'disposition or policy_attribute or clause_detail' -v && pytest tests/test_api_rag_service_payload.py -k 'disposition or finalize' -v`

Expected: PASS.

### Task 2: Keep Graph review data out of the model-answer channel

**Files:**
- Modify: `src/graph/context.py`
- Modify: `src/api/rag_service.py`
- Test: `tests/test_api_rag_service_payload.py`

**Interfaces:**
- Produces a prompt-only Graph context containing grounded facts plus safe clarification instructions.
- Keeps `graph_result_to_payload(...)` unchanged as the UI/export source for structured review paths.

- [ ] **Step 1: Write failing tests for prompt/UI separation**

```python
def test_prompt_graph_context_omits_missing_review_summary() -> None:
    result = graph_result_with(
        facts=[],
        review_paths=[{"status": "missing", "summary": "internal missing path"}],
        clarification_questions=["진료 목적을 확인해 주세요."],
    )

    prompt_context = build_prompt_graph_context(result)
    payload = graph_result_to_payload(result)

    assert "internal missing path" not in prompt_context
    assert "진료 목적을 확인해 주세요." in prompt_context
    assert payload["graph_review_paths"][0]["summary"] == "internal missing path"
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `pytest tests/test_api_rag_service_payload.py -k 'prompt_graph_context_omits_missing_review_summary' -v`

Expected: FAIL because `build_graph_context` currently renders review summaries into the prompt.

- [ ] **Step 3: Implement a prompt-safe graph-context builder**

```python
def build_prompt_graph_context(result: GraphRetrievalResult) -> str:
    lines = _render_grounded_fact_lines(result.facts)
    for question in result.plan.clarification_questions:
        lines.append(f"추가 확인 필요: {question}")
    return "\n".join(lines)
```

Use this function in `prepare_retrieved_context`. Keep the existing richer `build_graph_context` only for UI/debug callers that explicitly need the structured review template, or rename it only after updating all callers and tests. Do not copy a missing-path summary into prompt text and do not infer document absence from `facts == []`.

- [ ] **Step 4: Keep final normalization as a defense-in-depth layer**

Extend display normalization only for unambiguously internal syntax (`chunk=`, source implementation labels, row IDs, rendered Graph template headers). Do not use keyword deletion to hide unsupported factual prose; answer disposition must prevent those claims upstream.

- [ ] **Step 5: Run focused payload tests**

Run: `pytest tests/test_api_rag_service_payload.py -k 'graph or final or prompt' -v`

Expected: PASS.

### Task 3: Stream by answer disposition and add safe audit observability

**Files:**
- Modify: `src/api/routes/chat.py`
- Test: `tests/test_api_chat_stream.py`

**Interfaces:**
- `chat_stream` obtains an answer disposition for every route that can answer a coverage, payment, or claimability judgment (`general`, `formal`, `quickcode`, including explicit-mode variants). It uses `disposition.text` for deterministic streaming and only invokes `_generate_llm_stream` when the disposition origin is `llm`.
- `CHAT_QUERY` audit detail includes `answer_origin`, `grounding_state`, and a bounded `grounded_source_count`; it excludes raw prompts, hidden reasoning, and raw model response drafts.

- [ ] **Step 1: Write failing route-level regression tests**

```python
async def test_chat_stream_skips_llm_for_insufficient_coverage_evidence(...):
    monkeypatch.setattr(chat_routes, "_generate_llm_stream", lambda *args: pytest.fail("LLM must not decide coverage"))
    response = await collect_chat_stream("검사X 연간 보장되나요?", selected_generation="alpha")

    assert "확정할 수 없습니다" in response.answer
    assert "chunk=" not in response.answer
    assert response.audit.detail["answer_origin"] == "coverage_insufficient"
    assert response.audit.detail["grounding_state"] == "insufficient"


async def test_chat_stream_records_public_policy_attribute_disposition(...):
    response = await collect_chat_stream("검사X의 연간 보상한도는?", selected_generation="alpha")

    assert response.answer.startswith("선택한 alpha 기준")
    assert "123만원" in response.answer
    assert response.audit.detail["answer_origin"] == "policy_attribute"
    assert "chunk=" not in response.answer
```

Add route fixtures for each retrieval mode. A `formal` diagnostic-code coverage request and a `quickcode` fee-code-plus-coverage request must fail the test if `_generate_llm_stream` is reached without approved direct decision evidence. A pure formal code lookup and a pure quickcode lookup must retain their normal route behavior.

- [ ] **Step 2: Run the tests and confirm current behavior fails**

Run: `pytest tests/test_api_chat_stream.py -k 'insufficient_coverage or policy_attribute_disposition' -v`

Expected: FAIL because the route currently accepts an opaque string and can call the LLM for insufficient coverage evidence.

- [ ] **Step 3: Implement the route selection and audit fields**

```python
if answer_disposition.text is not None:
    raw_answer = answer_disposition.text
    for token in _chunk_text(raw_answer):
        ...
else:
    raw_answer = "".join(_generate_llm_stream(...)).strip()

audit_detail.update({
    "answer_origin": answer_disposition.origin,
    "grounding_state": answer_disposition.grounding_state,
    "grounded_source_count": len(answer_disposition.source_chunk_ids),
})
```

Ensure the coverage-boundary resolver runs after each route has its selected chunks but before the common streaming branch. It must receive the same selected policy-generation and conversation context as `general`; it may not rely on `resolved_mode == "general"`. Keep normal `formal`/`quickcode` retrieval for non-decision questions. Ensure Graph UI events and public sources are emitted as before. The finalizer must receive the already selected answer text and continue to protect display formatting without changing source payload semantics.

- [ ] **Step 4: Run route tests**

Run: `pytest tests/test_api_chat_stream.py -k 'policy_attribute or coverage or audit' -v`

Expected: PASS.

### Task 4: Preserve intent boundaries and add the UAT-class regression matrix

**Files:**
- Modify: `tests/test_search_intent.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_api_rag_service_payload.py`
- Modify: `tests/test_api_chat_stream.py`

- [ ] **Step 1: Add generic boundary cases**

```python
@pytest.mark.parametrize(
    "question, requires_coverage_judgment",
    [
        ("검사X의 연간 보상한도는?", False),
        ("alpha와 beta 검사X의 연간 보상한도를 비교해줘", False),
        ("검사X 연간 보장되나요?", True),
        ("검사X 보상한도 지급 여부는?", True),
    ],
)
def test_question_class_keeps_attribute_and_decision_boundaries(question, requires_coverage_judgment):
    plan = classify_search_intent(question)
    assert plan.requires_coverage_judgment is requires_coverage_judgment
```

Use a separate route test to assert that `requires_coverage_judgment=True` becomes a deterministic `coverage_insufficient` fallback when direct decision evidence is absent; do not force an LLM call.

- [ ] **Step 2: Add negative display assertions to every final-answer fixture**

```python
for forbidden in ("chunk=", "source=", "row_id=", "【claim_condition_review】", "직접 연결된 판단 조건 경로"):
    assert forbidden not in final_answer
```

Include a fixture where the Graph result has a missing review path but no facts, and assert that its UI payload remains available while final text does not contain the review summary.

- [ ] **Step 3: Require complete provenance for comparisons**

```python
def test_policy_comparison_requires_each_requested_generation_source() -> None:
    question = "alpha와 beta 검사X의 연간 보상한도를 비교해줘"
    only_alpha = make_chunk(
        doc_short="약관A",
        text="검사X의 연간 보상한도는 123만원입니다.",
        metadata={"policy_generation": "alpha", "page_start": 12},
    )

    disposition = resolve_answer_disposition(
        question,
        [only_alpha],
        search_intent=classify_search_intent(question),
    )

    assert disposition.origin == "policy_comparison"
    assert disposition.grounding_state == "insufficient"
    assert "123만원" not in (disposition.text or "")
    assert "비교할 수 없습니다" in (disposition.text or "")
```

Implement the completeness check from the question's requested comparison axes and the selected chunks' existing `policy_generation` / document provenance. Never enumerate product generations or numbers in code. Only set `policy_comparison/direct` after every requested axis has at least one direct selected source row; otherwise return the public insufficient-comparison fallback and record no direct source count for the missing side.

- [ ] **Step 4: Run all focused regression suites**

Run: `pytest tests/test_search_intent.py tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q`

Expected: PASS.

### Task 5: Record implementation evidence and perform a non-mutating candidate validation

**Files:**
- Create: `docs/reviews/2026-07-21-final-answer-grounding-implementation.md`

- [ ] **Step 1: Write the implementation report**

Include exact changed files, disposition origins/states, tests run and results, statement that active calculation rules/GraphDB/ontology/raw documents were not changed, and remaining runtime validation needed.

- [ ] **Step 2: Perform syntax/import and focused test validation**

Run:

```bash
python -m compileall -q src/rag/pipeline.py src/api/rag_service.py src/api/routes/chat.py src/graph/context.py
pytest tests/test_search_intent.py tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q
git diff --check
git status --short
```

Expected: compilation success, relevant tests PASS, no debug files or secrets, and only scope-approved candidate changes.

- [ ] **Step 3: Stop at the review gate**

Do not stage, commit, push, deploy, restart, rebuild, reindex, or promote. Report the candidate workspace path and completion marker so Planner can request an independent read-only review.

## Self-Review

- [x] **Spec coverage:** Task 1 fixes lost answer authority and public deterministic rendering; Task 2 stops Graph review leakage at the prompt boundary; Task 3 covers route and audit observability; Task 4 makes the generic failure class regression-tested; Task 5 records evidence and leaves promotion gated.
- [x] **No question-specific patch:** all examples use `검사X`, `alpha`, and `beta`; the design relies on existing intent/provenance metadata rather than literal MRI strings or values.
- [x] **Safety:** no active calculation rules, GraphDB/ontology data, raw documents, users/sessions, model configuration, or source-click payload are in scope.
- [x] **Boundary correctness:** numerical limit evidence cannot decide coverage/payout; missing Graph evidence cannot assert document absence; internal Graph content stays UI-only.
- [x] **Placeholder scan:** all tasks name files, interfaces, tests, commands, expected outcomes, and a required implementation report.
- [x] **Type consistency:** `AnswerDisposition` is produced at retrieval, consumed by the route, and recorded by audit; `origin`, `grounding_state`, and `source_chunk_ids` use the same names in all tasks.

## Execution Handoff

This plan is approved for a single isolated Developer implementation slice followed by an independent Review Team pass. Promotion is a later, separately authorized decision.
