# Claim Special Case Group Deductible Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5세대 산정특례 케이스 단위 선택, 3대비급여/MRI-MRA 보완 계산, 동일 공제 그룹 합산 공제, 제한된 계산 룰 후보 추출/승인 흐름을 000번 규칙에 맞게 연결한다.

**Architecture:** 산정특례 여부는 `ClaimCaseContext`의 케이스 단위 필드로 전달하고, 계산 엔진은 active rule manifest와 source-grounded 후보 승인 결과만 사용한다. 그룹 합산 공제는 보험 지식값이 아니라 동일 공제 단위에 1회 공제를 적용하는 계산 엔진 규칙으로 코드에 둔다. 5세대 3대비급여 보완값은 승인된 rule manifest 또는 승인 후보 apply 결과를 통해만 활성화한다.

**Tech Stack:** Python dataclasses, Pydantic, FastAPI, pytest, SQLite-backed chat history, static SPA JavaScript/CSS, existing claim rule JSON manifest and review scripts.

---

## File Structure

- Modify: `src/claim_calculation/models.py`
  - Add case-level `special_calculation_status` constants and field.
- Modify: `src/api/schemas/claim.py`
  - Add API request contract for case-level special calculation status.
- Modify: `src/claim_calculation/pipeline.py`
  - Add 5th-generation special-status gate, MRI/MRA category routing, grouped deductible post-processing.
- Modify: `src/api/routes/claim.py`
  - Persist special status in claim history text and claim snapshot.
- Modify: `src/claim_calculation/thread_recalculation.py`
  - Detect explicit special-status changes in follow-up recalculation requests and block ambiguous 5th-generation 3대비급여 recalculations.
- Modify: `src/api/routes/chat.py`
  - Return clarification message when recalculation needs case-level 산정특례 status.
- Modify: `src/api/rag_service.py`
  - Include special status in claim snapshot context shown to general RAG follow-up.
- Modify: `frontend/html/chat.html`
  - Add one case-level 산정특례 selector in claim mode, not per line item.
- Modify: `frontend/js/pages/chat.js`
  - Send, render, reset, and text-export the case-level special status.
- Modify: `frontend/css/chat.css`
  - Style the new selector with the existing claim mode bar pattern.
- Modify: `src/claim_calculation/rule_candidates.py`
  - Support approved replacement candidates for existing active rule IDs with review history.
- Modify: `scripts/extract_claim_rule_candidates.py`
  - Add scoped extractor mode for the attached 5세대 산정특례/3대비급여/MRI-MRA 보완 rules.
- Modify: `scripts/claim_rule_candidate_review.py`
  - Display practitioner labels for special status, MRI/MRA, and blocking candidates.
- Test: `tests/test_claim_calculation_pipeline.py`
- Test: `tests/test_deductible_rules.py`
- Test: `tests/test_claim_rule_candidates.py`
- Test: `tests/test_claim_rule_candidate_review.py`
- Test: `tests/test_api_chat_stream.py`
- Test: `tests/e2e/chat.spec.js`

## Execution Ground Rules

- Work from DGX main repository state for final validation: `/srv/shared/projects/insurance-rag-chatbot`.
- Do not start or replace an LLM server for this implementation; claim calculation tests use deterministic pipeline paths.
- Do not manually write source-grounded insurance rates into Python code except the group aggregation engine rule.
- Do not add item-level 산정특례 fields.
- Do not commit sample receipts, runtime reports, or generated candidate review JSONL unless the user explicitly asks to preserve the runtime artifact.
- Before every commit, run `git diff --name-only --cached` and confirm only the task files are staged.

---

## Task 1: Case-Level Special Calculation Contract

**Files:**
- Modify: `src/claim_calculation/models.py`
- Modify: `src/api/schemas/claim.py`
- Test: `tests/test_claim_calculation_pipeline.py`

- [ ] **Step 1: Write failing dataclass/API contract tests**

Add these tests near the generation tests in `tests/test_claim_calculation_pipeline.py`:

```python
def test_claim_case_context_defaults_special_calculation_unknown():
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient")

    assert context.special_calculation_status == "unknown"


def test_claim_case_context_accepts_case_level_special_calculation_status():
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="hospitalization",
        special_calculation_status="not_applied",
    )

    assert context.special_calculation_status == "not_applied"
```

Add this schema test to `tests/test_api_claim.py` if that file exists. If it does not exist, add it to `tests/test_api_chat_stream.py` because that file already validates claim snapshot contracts:

```python
from src.api.schemas.claim import ClaimCaseContextRequest


def test_claim_case_context_request_accepts_special_calculation_status():
    payload = ClaimCaseContextRequest(
        policy_generation="5th",
        visit_type="outpatient",
        special_calculation_status="applied",
    )

    assert payload.special_calculation_status == "applied"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_claim_case_context_defaults_special_calculation_unknown \
  tests/test_claim_calculation_pipeline.py::test_claim_case_context_accepts_case_level_special_calculation_status \
  -q
```

Expected: FAIL with `AttributeError: 'ClaimCaseContext' object has no attribute 'special_calculation_status'`.

- [ ] **Step 3: Add model constants and field**

In `src/claim_calculation/models.py`, add after imports:

```python
SPECIAL_CALCULATION_UNKNOWN = "unknown"
SPECIAL_CALCULATION_APPLIED = "applied"
SPECIAL_CALCULATION_NOT_APPLIED = "not_applied"
SPECIAL_CALCULATION_STATUSES = {
    SPECIAL_CALCULATION_UNKNOWN,
    SPECIAL_CALCULATION_APPLIED,
    SPECIAL_CALCULATION_NOT_APPLIED,
}


def normalize_special_calculation_status(value: str | None) -> str:
    normalized = (value or SPECIAL_CALCULATION_UNKNOWN).strip().lower()
    if normalized in {"applied", "적용", "산정특례 적용"}:
        return SPECIAL_CALCULATION_APPLIED
    if normalized in {"not_applied", "미적용", "산정특례 미적용"}:
        return SPECIAL_CALCULATION_NOT_APPLIED
    return SPECIAL_CALCULATION_UNKNOWN
```

Add this field to `ClaimCaseContext` after `policy_generation`:

```python
    special_calculation_status: str = SPECIAL_CALCULATION_UNKNOWN
```

- [ ] **Step 4: Add API schema field**

In `src/api/schemas/claim.py`, add this field to `ClaimCaseContextRequest` after `policy_generation`:

```python
    special_calculation_status: Literal["unknown", "applied", "not_applied"] = "unknown"
```

- [ ] **Step 5: Run contract tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_claim_case_context_defaults_special_calculation_unknown \
  tests/test_claim_calculation_pipeline.py::test_claim_case_context_accepts_case_level_special_calculation_status \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add src/claim_calculation/models.py src/api/schemas/claim.py tests/test_claim_calculation_pipeline.py
git diff --name-only --cached
git commit -m "feat(claim): add case special calculation status"
```

Expected staged files: the three paths listed in the `git add` command.

---

## Task 2: API Persistence and Claim Snapshot Text

**Files:**
- Modify: `src/api/routes/claim.py`
- Modify: `src/api/rag_service.py`
- Test: `tests/test_api_chat_stream.py`

- [ ] **Step 1: Write failing snapshot persistence test**

In `tests/test_api_chat_stream.py`, add this test near `_claim_snapshot_source_for_chat` tests:

```python
from src.api.routes.claim import _claim_snapshot_context
from src.api.schemas.claim import ClaimCaseContextRequest


def test_claim_snapshot_context_keeps_special_calculation_status():
    context = ClaimCaseContextRequest(
        policy_generation="5th",
        visit_type="hospitalization",
        special_calculation_status="not_applied",
    )

    snapshot_context = _claim_snapshot_context(context)

    assert snapshot_context["special_calculation_status"] == "not_applied"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py::test_claim_snapshot_context_keeps_special_calculation_status -q
```

Expected: FAIL with `KeyError: 'special_calculation_status'`.

- [ ] **Step 3: Add labels and persistence in claim route**

In `src/api/routes/claim.py`, add this helper after `MODEL_ALIAS`:

```python
SPECIAL_CALCULATION_LABELS = {
    "unknown": "산정특례 여부 모름",
    "applied": "산정특례 적용",
    "not_applied": "산정특례 미적용",
}


def _special_calculation_label(value: str | None) -> str:
    return SPECIAL_CALCULATION_LABELS.get(value or "unknown", "산정특례 여부 모름")
```

Update `_claim_user_text()` so the return value includes the case-level status:

```python
def _claim_user_text(payload: ClaimCalculationRequest) -> str:
    generation = "5세대" if payload.context.policy_generation == "5th" else "4세대"
    special_status = _special_calculation_label(payload.context.special_calculation_status)
    lines = []
    for item in payload.items:
        insured = item.insured_copay_amount or "0"
        nonpay = item.nonpay_amount or "0"
        lines.append(f"{item.input_name} 급여본인부담 {insured}원 / 비급여 {nonpay}원 x {item.quantity}")
    return f"[보험금 계산/{generation}/{special_status}] " + ", ".join(lines)
```

Update `_claim_response_text()` by adding this line after the insurance generation line:

```python
        f"- 산정특례 상태: {_special_calculation_label(getattr(response, 'special_calculation_status', 'unknown'))}",
```

If `ClaimCalculationResponse` does not contain `special_calculation_status`, use the result line context only in snapshot and omit the response text line until Task 3 adds it to result metadata. Do not synthesize a value from item names.

Update `_claim_snapshot_context()` by adding this key:

```python
        "special_calculation_status": getattr(context, "special_calculation_status", "unknown"),
```

- [ ] **Step 4: Add special status to RAG claim snapshot context**

In `src/api/rag_service.py`, find the helper that serializes claim snapshot context into prompt text. Add a Korean line when `special_calculation_status` exists:

```python
special_status = (context or {}).get("special_calculation_status") or "unknown"
special_label = {
    "unknown": "산정특례 여부 모름",
    "applied": "산정특례 적용",
    "not_applied": "산정특례 미적용",
}.get(special_status, "산정특례 여부 모름")
lines.append(f"- 산정특례 상태: {special_label}")
```

Use the existing `lines` variable in that helper. If the helper returns a string directly, insert the same text into the returned joined list.

- [ ] **Step 5: Run snapshot test**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py::test_claim_snapshot_context_keeps_special_calculation_status -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add src/api/routes/claim.py src/api/rag_service.py tests/test_api_chat_stream.py
git diff --name-only --cached
git commit -m "feat(claim): persist special calculation context"
```

Expected staged files: `src/api/routes/claim.py`, `src/api/rag_service.py`, `tests/test_api_chat_stream.py`.

---

## Task 3: Frontend Case-Level Selector

**Files:**
- Modify: `frontend/html/chat.html`
- Modify: `frontend/js/pages/chat.js`
- Modify: `frontend/css/chat.css`
- Test: `tests/e2e/chat.spec.js`

- [ ] **Step 1: Write failing frontend payload test**

In `tests/e2e/chat.spec.js`, add a test near existing claim calculation payload tests:

```javascript
test('claim form sends case-level special calculation status', async ({ page }) => {
  const requests = [];
  await page.route('**/claim/calculate', async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: 'session-1',
        claimed_amount: '100000',
        payable_amount: '70000',
        deductible: '30000',
        formula_intent: '',
        executed_code: '',
        applied_basis: [],
        requires_review: false,
        review_reasons: [],
        notes: '',
        candidates: [],
        policy_generation: '5th',
        line_results: [],
        calculation_status: 'auto_calculated',
        warnings: [],
      }),
    });
  });

  await page.goto('/chat');
  await page.getByRole('button', { name: '보험금 계산' }).click();
  await page.getByLabel('5세대 실손').check();
  await page.getByLabel('산정특례 미적용').check();
  await page.locator('.claim-item-name').first().fill('도수치료');
  await page.locator('.claim-nonpay-amount').first().fill('100000');
  await page.getByRole('button', { name: '계산하기' }).click();

  expect(requests[0].context.special_calculation_status).toBe('not_applied');
  expect(requests[0].items[0].special_calculation_status).toBeUndefined();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npx playwright test tests/e2e/chat.spec.js -g "case-level special calculation status"
```

Expected: FAIL because the label or payload field does not exist.

- [ ] **Step 3: Add selector to claim mode UI**

In `frontend/html/chat.html`, add this block inside `.mode-claim-generation`, immediately after the generation radio group:

```html
        <div class="mode-claim-special">
          <label class="p-label">산정특례 여부</label>
          <div class="claim-radio-group claim-special-radio-group">
            <label><input type="radio" name="claim-special-calculation-status" value="unknown" checked/> 모름</label>
            <label><input type="radio" name="claim-special-calculation-status" value="applied"/> 산정특례 적용</label>
            <label><input type="radio" name="claim-special-calculation-status" value="not_applied"/> 산정특례 미적용</label>
          </div>
        </div>
```

Do not add this control inside `[data-claim-line]`.

- [ ] **Step 4: Send and render the status in JavaScript**

In `frontend/js/pages/chat.js`, add these helpers near `getPolicyGeneration()`:

```javascript
function getSpecialCalculationStatus() {
  return document.querySelector('input[name="claim-special-calculation-status"]:checked')?.value || 'unknown';
}

function specialCalculationLabel(value) {
  const labels = {
    unknown: '산정특례 여부 모름',
    applied: '산정특례 적용',
    not_applied: '산정특례 미적용',
  };
  return labels[value] || labels.unknown;
}
```

In `sendClaim()`, add:

```javascript
  const specialCalculationStatus = getSpecialCalculationStatus();
```

Update the user message:

```javascript
    appendMsg('user', `[보험금 계산/${policyGeneration === '5th' ? '5세대' : '4세대'}/${specialCalculationLabel(specialCalculationStatus)}] ${itemSummary}`);
```

Add to request context:

```javascript
      special_calculation_status: specialCalculationStatus,
```

In `resetClaimForm()`, reset to unknown:

```javascript
  const specialStatus = document.querySelector('input[name="claim-special-calculation-status"][value="unknown"]');
  if (specialStatus instanceof HTMLInputElement) specialStatus.checked = true;
```

In `renderClaimResultHtml(result)`, change the calculation 기준 line to:

```javascript
      <div class="claim-note-text">계산 기준: ${result.policy_generation === '5th' ? '5세대 실손 표준약관' : '4세대 실손 기준'} / ${specialCalculationLabel(result.special_calculation_status || 'unknown')}</div>
```

In `claimResultToText(result)`, add after calculation 기준:

```javascript
    `산정특례 상태: ${specialCalculationLabel(result.special_calculation_status || 'unknown')}`,
```

- [ ] **Step 5: Add CSS sizing**

In `frontend/css/chat.css`, add:

```css
.mode-claim-special {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.claim-special-radio-group {
  min-width: 0;
}

.claim-special-radio-group label {
  white-space: nowrap;
}
```

- [ ] **Step 6: Run frontend test**

Run:

```bash
npx playwright test tests/e2e/chat.spec.js -g "case-level special calculation status"
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add frontend/html/chat.html frontend/js/pages/chat.js frontend/css/chat.css tests/e2e/chat.spec.js
git diff --name-only --cached
git commit -m "feat(frontend): add claim special status selector"
```

Expected staged files: the four paths listed in the `git add` command.

---

## Task 4: 5th-Generation Special-Status Calculation Gate

**Files:**
- Modify: `src/claim_calculation/pipeline.py`
- Test: `tests/test_claim_calculation_pipeline.py`

- [ ] **Step 1: Replace old 5th 3대비급여 assumption test**

Replace `test_fifth_generation_three_nonpay_uses_nonsevere_rate` in `tests/test_claim_calculation_pipeline.py` with these tests:

```python
def test_fifth_generation_unknown_three_major_nonpay_requires_special_status():
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="unknown")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "0"
    assert result.deductible == "0"
    assert result.requires_review
    line = result.line_results[0]
    assert line["calculation_status"] == "human_task"
    assert line["excluded_from_calculation"] is True
    assert any("산정특례 적용 여부" in reason for reason in line["review_reasons"])


def test_fifth_generation_not_applied_manual_therapy_is_not_auto_paid():
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="not_applied")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.payable_amount == "0"
    assert result.deductible == "0"
    assert result.requires_review
    line = result.line_results[0]
    assert line["calculation_status"] == "human_task"
    assert line["human_task_amount"] == "100000"
    assert any("산정특례 미적용" in reason for reason in line["review_reasons"])


def test_fifth_generation_applied_three_major_nonpay_uses_special_case_rule():
    items = [ClaimItemInput(line_id="line_dosu", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여")]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", special_calculation_status="applied")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "30000"
    assert result.payable_amount == "70000"
    assert "중증비급여" in result.line_results[0]["category"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_unknown_three_major_nonpay_requires_special_status \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_not_applied_manual_therapy_is_not_auto_paid \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_applied_three_major_nonpay_uses_special_case_rule \
  -q
```

Expected: FAIL because the pipeline still treats 5세대 3대비급여 as the old 50% route.

- [ ] **Step 3: Add special-status helper functions**

In `src/claim_calculation/pipeline.py`, import the constants:

```python
from src.claim_calculation.models import (
    ClaimItemInput,
    ClaimCaseContext,
    StandardMatch,
    BasisSelection,
    CalculationPlan,
    CalculationResult,
    normalize_special_calculation_status,
    SPECIAL_CALCULATION_APPLIED,
    SPECIAL_CALCULATION_NOT_APPLIED,
    SPECIAL_CALCULATION_UNKNOWN,
)
```

Add these helpers after `_classify_claim_category()`:

```python
THREE_MAJOR_BLOCK_KEYWORDS = ("도수", "체외충격파", "증식", "주사")
MRI_MRA_KEYWORDS = ("mri", "mra", "자기공명영상")


def _special_status(context: ClaimCaseContext) -> str:
    return normalize_special_calculation_status(getattr(context, "special_calculation_status", "unknown"))


def _is_mri_mra_item(item: ClaimItemInput, match: StandardMatch | None) -> bool:
    text = " ".join([item.input_name or "", item.user_category_hint or "", _standard_match_text(match)]).lower()
    return any(keyword in text for keyword in MRI_MRA_KEYWORDS)


def _is_three_major_nonpay_item(category: str, item: ClaimItemInput, match: StandardMatch | None) -> bool:
    if category == "3대비급여":
        return True
    text = " ".join([item.input_name or "", item.user_category_hint or "", _standard_match_text(match)]).lower()
    return any(keyword in text for keyword in THREE_MAJOR_BLOCK_KEYWORDS) or _is_mri_mra_item(item, match)


def _fifth_generation_special_category(
    category: str,
    item: ClaimItemInput,
    match: StandardMatch | None,
    context: ClaimCaseContext,
) -> tuple[str, str]:
    if _normalize_policy_generation(context.policy_generation) != "5th":
        return category, ""
    if not _is_three_major_nonpay_item(category, item, match):
        return category, ""

    status = _special_status(context)
    if status == SPECIAL_CALCULATION_APPLIED:
        return "중증비급여", ""
    if status == SPECIAL_CALCULATION_NOT_APPLIED and _is_mri_mra_item(item, match):
        return "비급여자기공명영상진단", ""
    if status == SPECIAL_CALCULATION_NOT_APPLIED:
        return category, "산정특례 미적용 케이스에서는 도수치료, 체외충격파, 증식치료, 주사료 계열 3대비급여를 자동 지급 산정하지 않습니다."
    return category, "5세대 3대비급여 계산에는 산정특례 적용 여부 확인이 필요합니다."
```

- [ ] **Step 4: Use the helper in split and non-split nonpay paths**

In `_calculate_line_items()`, before nonpay deductible calculation in split mode, insert:

```python
                nonpay_category, special_block_reason = _fifth_generation_special_category(
                    nonpay_category,
                    item,
                    match,
                    context,
                )
                if special_block_reason:
                    rule_parts.append("비급여 금액: 산정특례 상태 확인 필요로 자동 산정 제외")
                    line_review = True
                    line_reasons.append(special_block_reason)
                    category_parts[-1] = nonpay_category
                    continue
```

In the non-split standard path before `_is_unresolved_nonpay(category, match)`, insert:

```python
            category, special_block_reason = _fifth_generation_special_category(category, item, match, context)
            if special_block_reason:
                deductible = Decimal("0")
                payable = Decimal("0")
                rule = "산정특례 상태 확인 필요로 자동 산정 제외"
                line_review = True
                line_reasons.append(special_block_reason)
                total_payable += payable
                total_deductible += deductible
                review_reasons.extend(line_reasons)
                line_results.append(
                    {
                        "line_id": item.line_id,
                        "input_name": item.input_name,
                        "input_code": item.input_code,
                        "category": category,
                        "claimed_amount": _format_decimal_won(amount),
                        "insured_copay_amount": _format_decimal_won(insured_copay_amount),
                        "nonpay_amount": _format_decimal_won(nonpay_amount),
                        "deductible": _format_decimal_won(deductible),
                        "payable_amount": _format_decimal_won(payable),
                        "policy_generation": generation,
                        "rule_summary": rule,
                        "extra_info": item.extra_info,
                        "requires_review": line_review,
                        "review_reasons": line_reasons,
                        "calculation_status": "human_task",
                        "excluded_from_calculation": True,
                        "human_task_amount": _format_decimal_won(amount),
                    }
                )
                continue
```

Do not apply this block to 4세대.

- [ ] **Step 5: Ensure active rule lookup supports MRI/MRA category through manifest**

In `tests/test_deductible_rules.py`, add a manifest-level expectation if the active manifest already contains MRI/MRA rules after candidate approval:

```python
def test_fifth_generation_mri_mra_rule_is_source_grounded_when_active():
    from src.claim_calculation.deductible_rules import lookup_rule

    rule = lookup_rule("5th", "비급여자기공명영상진단", "outpatient")

    assert rule.copay_ratio == Decimal("0.5")
    assert rule.min_deductible == Decimal("50000")
    assert rule.source_chunk_id
```

If this test fails before candidate approval, keep it marked in the implementation branch only after the candidate apply task activates MRI/MRA rules. Do not skip it in the final state.

- [ ] **Step 6: Run special-status tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_unknown_three_major_nonpay_requires_special_status \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_not_applied_manual_therapy_is_not_auto_paid \
  tests/test_claim_calculation_pipeline.py::test_fifth_generation_applied_three_major_nonpay_uses_special_case_rule \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add src/claim_calculation/pipeline.py tests/test_claim_calculation_pipeline.py tests/test_deductible_rules.py
git diff --name-only --cached
git commit -m "fix(claim): gate fifth generation special nonpay"
```

Expected staged files: the three paths listed in the `git add` command.

---

## Task 5: Grouped Deductible Engine Rule

**Files:**
- Modify: `src/claim_calculation/pipeline.py`
- Test: `tests/test_claim_calculation_pipeline.py`

- [ ] **Step 1: Add failing grouped deductible tests**

Add these tests to `tests/test_claim_calculation_pipeline.py`:

```python
def test_grouped_deductible_applies_once_for_same_fifth_benefit_outpatient_group():
    items = [
        ClaimItemInput(line_id="line_1", input_name="급여 외래진료비 A", claimed_amount="30000", user_category_hint="급여"),
        ClaimItemInput(line_id="line_2", input_name="급여 외래진료비 B", claimed_amount="30000", user_category_hint="급여"),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", facility_grade="clinic")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.claimed_amount == "60000"
    assert result.deductible == "12000"
    assert result.payable_amount == "48000"
    assert sum(int(line["deductible"]) for line in result.line_results) == 12000
    assert all(line["deductible_group"] == "benefit_group" for line in result.line_results)


def test_grouped_deductible_excludes_human_task_lines_from_group_amount():
    items = [
        ClaimItemInput(line_id="line_1", input_name="급여 외래진료비", claimed_amount="30000", user_category_hint="급여"),
        ClaimItemInput(line_id="line_2", input_name="도수치료", claimed_amount="100000", user_category_hint="3대비급여"),
    ]
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", facility_grade="clinic", special_calculation_status="unknown")

    with patch("src.db.standard_codes.search_by_name", side_effect=_matches_for(items)):
        result = run_claim_calculation(None, items, context, use_fake_planner=True)

    assert result.deductible == "10000"
    assert result.payable_amount == "20000"
    assert result.line_results[1]["calculation_status"] == "human_task"
    assert result.line_results[1]["deductible_group"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_grouped_deductible_applies_once_for_same_fifth_benefit_outpatient_group \
  tests/test_claim_calculation_pipeline.py::test_grouped_deductible_excludes_human_task_lines_from_group_amount \
  -q
```

Expected: FAIL because each line is currently deducted independently and `deductible_group` is absent.

- [ ] **Step 3: Add group helper functions**

In `src/claim_calculation/pipeline.py`, change the Decimal import:

```python
from decimal import Decimal, ROUND_HALF_UP
```

Add helpers before `_calculate_line_items()`:

```python
def _deductible_group_for_category(category: str) -> str:
    if "급여" == category:
        return "benefit_group"
    if category == "비급여자기공명영상진단":
        return "mri_mra_group"
    if category == "3대비급여":
        return "three_major_nonpay_group"
    if category in {"비급여", "비중증비급여", "중증비급여"}:
        return "general_nonpay_group"
    return ""


def _group_key(line: dict[str, str | bool | list[str]], context: ClaimCaseContext) -> tuple[str, str, str, str, str]:
    return (
        str(line.get("policy_generation") or ""),
        context.visit_type or "",
        context.facility_grade or "",
        _special_status(context),
        str(line.get("deductible_group") or ""),
    )


def _line_is_group_eligible(line: dict[str, str | bool | list[str]]) -> bool:
    if not line.get("deductible_group"):
        return False
    if line.get("excluded_from_calculation") is True:
        return False
    if line.get("calculation_status") in {"human_task", "partial_human_task"}:
        return False
    return Decimal(str(line.get("claimed_amount") or "0")) > 0


def _allocate_won(total: Decimal, amounts: list[Decimal]) -> list[Decimal]:
    if not amounts:
        return []
    amount_sum = sum(amounts, Decimal("0"))
    if amount_sum <= 0:
        return [Decimal("0") for _ in amounts]
    allocated: list[Decimal] = []
    running = Decimal("0")
    for amount in amounts[:-1]:
        part = (total * amount / amount_sum).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        allocated.append(part)
        running += part
    allocated.append(total - running)
    return allocated
```

- [ ] **Step 4: Mark groups on line results**

When appending a normal calculated line in `_calculate_line_items()`, add:

```python
                "deductible_group": _deductible_group_for_category(category),
```

When appending human task or blocked lines, add:

```python
                        "deductible_group": "",
```

For prescription and upper-room paths, set `deductible_group` to `""` because they use separate special rules.

- [ ] **Step 5: Recalculate grouped totals before returning**

Add this helper after `_calculate_line_items()`:

```python
def _apply_grouped_deductibles(
    line_results: list[dict[str, str | bool | list[str]]],
    context: ClaimCaseContext,
) -> tuple[Decimal, Decimal, list[str]]:
    groups: dict[tuple[str, str, str, str, str], list[dict[str, str | bool | list[str]]]] = {}
    for line in line_results:
        if not _line_is_group_eligible(line):
            continue
        groups.setdefault(_group_key(line, context), []).append(line)

    review_reasons: list[str] = []
    for group_lines in groups.values():
        if len(group_lines) < 2:
            continue
        category = str(group_lines[0].get("category") or "미분류")
        group_amounts = [Decimal(str(line.get("claimed_amount") or "0")) for line in group_lines]
        group_amount = sum(group_amounts, Decimal("0"))
        group_payable, group_deductible, group_rule, group_review = _apply_standard_deductible(
            group_amount,
            category,
            _normalize_policy_generation(context.policy_generation),
            context,
        )
        payable_parts = _allocate_won(group_payable, group_amounts)
        deductible_parts = _allocate_won(group_deductible, group_amounts)
        for line, payable, deductible in zip(group_lines, payable_parts, deductible_parts):
            line["payable_amount"] = _format_decimal_won(payable)
            line["deductible"] = _format_decimal_won(deductible)
            line["rule_summary"] = f"{line.get('rule_summary')}; 동일 공제 그룹 합산 적용: {group_rule}"
            reasons = list(line.get("review_reasons") or [])
            reasons.extend(group_review)
            line["review_reasons"] = reasons
            if group_review:
                line["requires_review"] = True
        review_reasons.extend(group_review)

    total_payable = sum(Decimal(str(line.get("payable_amount") or "0")) for line in line_results if line.get("excluded_from_calculation") is not True)
    total_deductible = sum(Decimal(str(line.get("deductible") or "0")) for line in line_results if line.get("excluded_from_calculation") is not True)
    return total_payable, total_deductible, review_reasons
```

At the end of `_calculate_line_items()`, replace the return with:

```python
    grouped_payable, grouped_deductible, grouped_reviews = _apply_grouped_deductibles(line_results, context)
    review_reasons.extend(grouped_reviews)
    return grouped_payable, grouped_deductible, line_results, review_reasons
```

This code-level rule is the approved fixed engine behavior: same deductible group, same case context, one deductible calculation.

- [ ] **Step 6: Run grouped deductible tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claim_calculation_pipeline.py::test_grouped_deductible_applies_once_for_same_fifth_benefit_outpatient_group \
  tests/test_claim_calculation_pipeline.py::test_grouped_deductible_excludes_human_task_lines_from_group_amount \
  -q
```

Expected: PASS.

- [ ] **Step 7: Run claim pipeline regression subset**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add src/claim_calculation/pipeline.py tests/test_claim_calculation_pipeline.py
git diff --name-only --cached
git commit -m "fix(claim): apply grouped deductible once"
```

Expected staged files: `src/claim_calculation/pipeline.py`, `tests/test_claim_calculation_pipeline.py`.

---

## Task 6: Source-Grounded Rule Candidate Replacement

**Files:**
- Modify: `src/claim_calculation/rule_candidates.py`
- Test: `tests/test_claim_rule_candidates.py`

- [ ] **Step 1: Add failing replacement candidate test**

Create `tests/test_claim_rule_candidates.py` if it does not exist. Add:

```python
from src.claim_calculation.rule_candidates import build_apply_plan


def _deductible_rule(rule_id: str, ratio: str) -> dict:
    return {
        "rule_id": rule_id,
        "generation": "5th",
        "category": "3대비급여",
        "visit_type": "outpatient",
        "facility_grade": "all",
        "copay_ratio": ratio,
        "min_deductible": "50000",
        "min_deductible_by_facility": {
            "clinic": "50000",
            "hospital": "50000",
            "general_hospital": "50000",
            "tertiary_hospital": "50000",
        },
        "per_visit_limit": "200000",
        "annual_limit": "50000000",
        "annual_visit_limit": None,
        "description": "5세대 3대비급여 통원 공제",
        "source_doc": "표준약관",
        "source_page": "1",
        "source_clause": "source_chunk_id:표준약관_ch_005607",
        "source_chunk_id": "표준약관_ch_005607",
        "additional_source_refs": [],
        "source_status": "source_grounded",
        "approval_status": "candidate",
    }


def test_apply_plan_allows_approved_replace_candidate_for_existing_rule():
    active_rule = _deductible_rule("deductible.5th.three_major_non_benefit.outpatient", "0.5")
    candidate_rule = _deductible_rule("deductible.5th.three_major_non_benefit.outpatient", "0.3")
    candidate = {
        "candidate_id": "rulecand.replace.5th.three_major_non_benefit.outpatient",
        "status": "approved",
        "rule_type": "deductible",
        "operation": "replace",
        "target_rule_id": active_rule["rule_id"],
        "proposed_rule": candidate_rule,
        "proposed_links": {
            "rule_id": candidate_rule["rule_id"],
            "source_refs": ["policy_chunk:표준약관_ch_005607"],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": ["source_chunk:표준약관_ch_005607"],
            "link_status": "candidate",
        },
        "source_refs": [{"kind": "policy_chunk", "doc_short": "표준약관", "chunk_id": "표준약관_ch_005607"}],
        "evidence_text": "산정특례 적용 대상자는 30%를 공제한다.",
    }

    plan = build_apply_plan(active_rules=[active_rule], active_links=[], candidates=[candidate])

    assert plan.rules_to_add == []
    assert plan.rules_to_replace[0]["rule_id"] == active_rule["rule_id"]
    assert plan.rules_to_replace[0]["copay_ratio"] == "0.3"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_candidates.py::test_apply_plan_allows_approved_replace_candidate_for_existing_rule -q
```

Expected: FAIL because `CandidateApplyPlan` has no `rules_to_replace`.

- [ ] **Step 3: Extend apply plan dataclass**

In `src/claim_calculation/rule_candidates.py`, change `CandidateApplyPlan` to:

```python
@dataclass(frozen=True)
class CandidateApplyPlan:
    rules_to_add: list[dict[str, Any]]
    links_to_add: list[dict[str, Any]]
    rules_to_replace: list[dict[str, Any]]
    links_to_replace: list[dict[str, Any]]
    applied_candidate_ids: list[str]
```

- [ ] **Step 4: Validate replacement metadata**

In `validate_candidate_record()`, add:

```python
    operation = str(record.get("operation") or "add")
    if operation not in {"add", "replace"}:
        raise CandidateValidationError(f"invalid operation: {operation}")
    if operation == "replace" and record.get("target_rule_id") != proposed_rule.get("rule_id"):
        raise CandidateValidationError("target_rule_id must match proposed_rule.rule_id for replace candidates")
```

- [ ] **Step 5: Implement replacement handling**

In `build_apply_plan()`, initialize:

```python
    rules_to_replace: list[dict[str, Any]] = []
    links_to_replace: list[dict[str, Any]] = []
```

Inside the approved candidate loop, replace duplicate logic with:

```python
        operation = str(candidate.get("operation") or "add")
        if operation == "replace":
            if rule_id not in seen_rules:
                raise CandidateValidationError(f"replace target rule_id not found: {rule_id}")
            rule["approval_status"] = "active"
            link["link_status"] = "active"
            _validate_rule_payload(str(candidate["rule_type"]), rule)
            rules_to_replace.append(rule)
            links_to_replace.append(link)
            applied_candidate_ids.append(str(candidate["candidate_id"]))
            continue
        if rule_id in seen_rules:
            raise CandidateValidationError(f"duplicate rule_id: {rule_id}")
```

Return:

```python
    return CandidateApplyPlan(rules_to_add, links_to_add, rules_to_replace, links_to_replace, applied_candidate_ids)
```

- [ ] **Step 6: Update apply script consumer**

Find consumers of `CandidateApplyPlan`:

```bash
rg -n "rules_to_add|links_to_add|CandidateApplyPlan" scripts src tests
```

In the script that applies candidates to active manifest, replace matching rule records by `rule_id` before appending new rules:

```python
def _replace_by_rule_id(records: list[dict], replacements: list[dict]) -> list[dict]:
    replacement_map = {record["rule_id"]: record for record in replacements}
    output = []
    for record in records:
        rule_id = record.get("rule_id")
        output.append(replacement_map.pop(rule_id, record))
    output.extend(replacement_map.values())
    return output
```

Use this for both rules and links before writing active JSON.

- [ ] **Step 7: Run candidate tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_candidates.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

Run:

```bash
git add src/claim_calculation/rule_candidates.py tests/test_claim_rule_candidates.py scripts/claim_rule_candidate_review.py
git diff --name-only --cached
git commit -m "feat(claim): support reviewed rule replacements"
```

Expected staged files include the candidate helper, candidate tests, and the script consumer if it was modified.

---

## Task 7: Scoped 5th-Generation Rule Candidate Extraction and Labels

**Files:**
- Modify: `scripts/extract_claim_rule_candidates.py`
- Modify: `scripts/claim_rule_candidate_review.py`
- Test: `tests/test_claim_rule_candidate_review.py`

- [ ] **Step 1: Add failing scoped extraction test**

Create `tests/test_claim_rule_candidate_review.py` if it does not exist. Add:

```python
from scripts.extract_claim_rule_candidates import extract_special_case_5th_candidates
from scripts.claim_rule_candidate_review import candidate_summary


def test_special_case_5th_extractor_builds_practitioner_named_candidates():
    chunks = [
        {
            "text": "5세대 산정특례 적용 대상자의 3대비급여는 본인부담금 30%를 공제한다.",
            "doc_short": "표준약관",
            "chunk_id": "표준약관_ch_005607",
            "page": 1,
            "article": "5세대 산정특례",
        },
        {
            "text": "산정특례 미적용 MRI MRA 자기공명영상진단은 비급여 자기공명영상진단으로 본인부담금 50%를 공제한다.",
            "doc_short": "표준약관",
            "chunk_id": "표준약관_ch_005628",
            "page": 2,
            "article": "자기공명영상진단",
        },
    ]

    candidates = extract_special_case_5th_candidates(chunks)

    assert len(candidates) >= 2
    summaries = [candidate_summary(candidate) for candidate in candidates]
    assert any("산정특례 적용" in summary for summary in summaries)
    assert any("자기공명영상진단" in summary for summary in summaries)
    assert all("unknown" not in summary for summary in summaries)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_candidate_review.py::test_special_case_5th_extractor_builds_practitioner_named_candidates -q
```

Expected: FAIL because `extract_special_case_5th_candidates` does not exist.

- [ ] **Step 3: Add scoped extractor**

In `scripts/extract_claim_rule_candidates.py`, add:

```python
SPECIAL_CASE_5TH_CHUNK_IDS = {
    "표준약관_ch_005379",
    "표준약관_ch_005394",
    "표준약관_ch_005395",
    "표준약관_ch_005397",
    "표준약관_ch_005421",
    "표준약관_ch_005434",
    "표준약관_ch_005435",
    "표준약관_ch_005447",
    "표준약관_ch_005452",
    "표준약관_ch_005599",
    "표준약관_ch_005607",
    "표준약관_ch_005628",
}


def _candidate_base(candidate_id: str, rule: dict[str, Any], chunk: dict[str, Any], evidence_text: str, operation: str = "add") -> dict[str, Any]:
    source_key = f"policy_chunk:{chunk['chunk_id']}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "candidate_id": candidate_id,
        "status": "pending",
        "rule_type": "deductible",
        "operation": operation,
        "target_rule_id": rule["rule_id"] if operation == "replace" else None,
        "proposed_rule": rule,
        "proposed_links": {
            "rule_id": rule["rule_id"],
            "source_refs": [source_key],
            "ontology_refs": ["cov.indemnity_medical"],
            "graph_refs": [f"source_chunk:{chunk['chunk_id']}"],
            "link_status": "candidate",
        },
        "source_refs": [{"kind": "policy_chunk", "doc_short": chunk["doc_short"], "chunk_id": chunk["chunk_id"], "page": chunk["page"], "article": chunk["article"]}],
        "evidence_text": evidence_text.strip(),
        "extraction_reason": "첨부 명세 범위의 5세대 산정특례/3대비급여/MRI-MRA 보완 후보",
        "risk_flags": ["manual_review_required"],
        "created_at": now,
        "reviewed_at": None,
        "reviewer": None,
        "review_note": "",
    }
```

Add:

```python
def _deductible_rule(
    *,
    rule_id: str,
    category: str,
    visit_type: str,
    copay_ratio: str,
    min_deductible: str,
    per_visit_limit: str | None,
    annual_limit: str | None,
    description: str,
    chunk: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "generation": "5th",
        "category": category,
        "visit_type": visit_type,
        "facility_grade": "all",
        "copay_ratio": copay_ratio,
        "min_deductible": min_deductible,
        "min_deductible_by_facility": {
            "clinic": min_deductible,
            "hospital": min_deductible,
            "general_hospital": min_deductible,
            "tertiary_hospital": min_deductible,
        },
        "per_visit_limit": per_visit_limit,
        "annual_limit": annual_limit,
        "annual_visit_limit": None,
        "description": description,
        "source_doc": chunk["doc_short"],
        "source_page": str(chunk["page"] or "unknown"),
        "source_clause": chunk["article"] or f"source_chunk_id:{chunk['chunk_id']}",
        "source_chunk_id": chunk["chunk_id"],
        "additional_source_refs": [],
        "source_status": "source_grounded",
        "approval_status": "candidate",
    }
```

Add:

```python
def extract_special_case_5th_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoped_chunks = [chunk for chunk in chunks if chunk.get("chunk_id") in SPECIAL_CASE_5TH_CHUNK_IDS]
    candidates: list[dict[str, Any]] = []
    for chunk in scoped_chunks:
        text = str(chunk.get("text") or "")
        if "산정특례" in text and "3대비급여" in text and "30%" in text:
            for visit_type, min_deductible, per_visit_limit in [
                ("hospitalization", "0", None),
                ("outpatient", "30000", "200000"),
            ]:
                rule = _deductible_rule(
                    rule_id=f"deductible.5th.three_major_non_benefit.{visit_type}",
                    category="3대비급여",
                    visit_type=visit_type,
                    copay_ratio="0.3",
                    min_deductible=min_deductible,
                    per_visit_limit=per_visit_limit,
                    annual_limit="50000000",
                    description=f"5세대 산정특례 적용 3대비급여 {visit_type} 본인부담금 30%",
                    chunk=chunk,
                )
                candidates.append(_candidate_base(f"rulecand.replace.{rule['rule_id']}", rule, chunk, text, operation="replace"))
        if ("MRI" in text or "MRA" in text or "자기공명영상" in text) and "50%" in text:
            for visit_type, min_deductible, per_visit_limit in [
                ("hospitalization", "0", None),
                ("outpatient", "50000", "200000"),
            ]:
                rule = _deductible_rule(
                    rule_id=f"deductible.5th.mri_mra.{visit_type}",
                    category="비급여자기공명영상진단",
                    visit_type=visit_type,
                    copay_ratio="0.5",
                    min_deductible=min_deductible,
                    per_visit_limit=per_visit_limit,
                    annual_limit="50000000",
                    description=f"5세대 산정특례 미적용 비급여 자기공명영상진단 {visit_type} 본인부담금 50%",
                    chunk=chunk,
                )
                candidates.append(_candidate_base(f"rulecand.add.{rule['rule_id']}", rule, chunk, text, operation="add"))
    for candidate in candidates:
        validate_candidate_record(candidate)
    return candidates
```

- [ ] **Step 4: Add CLI scope**

In `main()`, add:

```python
    parser.add_argument("--scope", choices=["generic", "special-case-5th"], default="generic")
```

Replace extraction loop with:

```python
    chunks = iter_policy_chunks(args.index_jsonl)
    if args.scope == "special-case-5th":
        candidates = extract_special_case_5th_candidates(chunks)
    else:
        candidates = []
        for chunk in chunks:
            candidates.extend(extract_candidates_from_text(**chunk))
            if args.limit and len(candidates) >= args.limit:
                candidates = candidates[: args.limit]
                break
```

- [ ] **Step 5: Improve practitioner labels**

In `scripts/claim_rule_candidate_review.py`, extend label maps:

```python
SPECIAL_STATUS_LABELS = {
    "unknown": "산정특례 여부 모름",
    "applied": "산정특례 적용",
    "not_applied": "산정특례 미적용",
}

CATEGORY_LABELS.update({
    "3대비급여": "3대비급여",
    "비급여자기공명영상진단": "비급여 자기공명영상진단(MRI/MRA)",
    "중증비급여": "산정특례 적용 비급여",
    "비중증비급여": "산정특례 미적용 비급여",
})
```

In `candidate_summary(candidate)`, include `operation == "replace"` as `기존 룰 수정 후보` and avoid exposing `unknown`, `outpatient`, or internal IDs as the primary label.

- [ ] **Step 6: Run scoped candidate test**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_candidate_review.py::test_special_case_5th_extractor_builds_practitioner_named_candidates -q
```

Expected: PASS.

- [ ] **Step 7: Run dry-run scoped extraction on DGX**

Run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python scripts/extract_claim_rule_candidates.py --scope special-case-5th --dry-run --index-jsonl data/processed/chunks_v1_v2_combined.jsonl'
```

Expected: JSON with `candidate_count` greater than `0`. If `candidate_count` is `0`, inspect the listed `SPECIAL_CASE_5TH_CHUNK_IDS` against the active chunks file before changing code.

- [ ] **Step 8: Commit Task 7**

Run:

```bash
git add scripts/extract_claim_rule_candidates.py scripts/claim_rule_candidate_review.py tests/test_claim_rule_candidate_review.py
git diff --name-only --cached
git commit -m "feat(claim): extract fifth generation rule candidates"
```

Expected staged files: the three paths listed in the `git add` command.

---

## Task 8: Follow-Up Recalculation Clarification

**Files:**
- Modify: `src/claim_calculation/thread_recalculation.py`
- Modify: `src/api/routes/chat.py`
- Test: `tests/test_api_chat_stream.py`

- [ ] **Step 1: Add failing follow-up clarification test**

In `tests/test_api_chat_stream.py`, add:

```python
def test_recalculation_needs_special_status_for_fifth_generation_three_major():
    from src.claim_calculation.thread_recalculation import (
        detect_recalculation_intent,
        find_target_line,
        needs_special_calculation_clarification,
    )

    snapshot = _claim_snapshot_source_for_chat()
    claim_snapshot = snapshot["claim_snapshot"]
    claim_snapshot["input"]["context"] = {
        "policy_generation": "5th",
        "visit_type": "outpatient",
        "coverage_topic": "실손",
        "special_calculation_status": "unknown",
    }
    query = "도수치료를 3대비급여로 보상한다면 다시 계산해줘"
    intent = detect_recalculation_intent(query)
    target_line = find_target_line(claim_snapshot, "도수치료")

    assert intent is not None
    assert target_line is not None
    assert needs_special_calculation_clarification(claim_snapshot, intent, target_line)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py::test_recalculation_needs_special_status_for_fifth_generation_three_major -q
```

Expected: FAIL because `needs_special_calculation_clarification` does not exist.

- [ ] **Step 3: Add special-status parsing helpers**

In `src/claim_calculation/thread_recalculation.py`, add:

```python
def special_status_from_query(query: str) -> str | None:
    text = " ".join(query.split())
    if "산정특례 미적용" in text:
        return "not_applied"
    if "산정특례 적용" in text:
        return "applied"
    return None


def apply_special_status_override(payload: dict, special_status: str | None) -> dict:
    if not special_status:
        return payload
    updated = dict(payload)
    context = dict(updated.get("context") or {})
    context["special_calculation_status"] = special_status
    updated["context"] = context
    return updated


def needs_special_calculation_clarification(snapshot: dict, intent: RecalculationIntent, target_line: dict) -> bool:
    context = (snapshot.get("input") or {}).get("context") or {}
    if context.get("policy_generation") != "5th":
        return False
    if context.get("special_calculation_status") in {"applied", "not_applied"}:
        return False
    if intent.action != "as_three_major_nonpay":
        return False
    target_text = " ".join([str(target_line.get("input_name") or ""), str(target_line.get("category") or "")])
    return any(keyword in target_text.lower() for keyword in ("도수", "체외충격파", "증식", "주사", "mri", "mra", "자기공명영상", "3대비급여"))
```

- [ ] **Step 4: Use the helper in chat route**

In `src/api/routes/chat.py`, in the claim follow-up handler before `build_recalculation_payload()`, add:

```python
special_status_override = special_status_from_query(payload.query)
if needs_special_calculation_clarification(claim_snapshot, intent, target_line) and not special_status_override:
    return "5세대 3대비급여 재계산에는 산정특례 적용 여부가 필요합니다. '산정특례 적용으로' 또는 '산정특례 미적용으로' 중 하나를 함께 알려주세요."

recalculation_payload = build_recalculation_payload(claim_snapshot, intent, target_line)
recalculation_payload = apply_special_status_override(recalculation_payload, special_status_override)
```

Import the three helpers from `src.claim_calculation.thread_recalculation`.

- [ ] **Step 5: Run follow-up tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py::test_recalculation_needs_special_status_for_fifth_generation_three_major -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add src/claim_calculation/thread_recalculation.py src/api/routes/chat.py tests/test_api_chat_stream.py
git diff --name-only --cached
git commit -m "feat(claim): clarify special status in follow-up recalculation"
```

Expected staged files: the three paths listed in the `git add` command.

---

## Task 9: Final Validation on DGX Main

**Files:**
- No new source file unless tests expose a defect.

- [ ] **Step 1: Sync implementation to DGX main**

Run from local after commits are ready:

```bash
git status --short --branch
git push origin master
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && git fetch origin && git status --short --branch'
```

Expected: local branch pushed, DGX branch can fast-forward or already matches origin.

- [ ] **Step 2: Run focused Python tests on DGX**

Run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py tests/test_deductible_rules.py tests/test_claim_rule_candidates.py tests/test_claim_rule_candidate_review.py tests/test_api_chat_stream.py -q'
```

Expected: PASS.

- [ ] **Step 3: Run frontend regression tests on DGX**

Run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && npm test -- tests/e2e/chat.spec.js'
```

If the repository uses a different frontend test command, run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && rg -n "playwright|vitest|npm test" package.json tests frontend'
```

Then run the discovered existing command. Expected: the claim mode test that verifies `special_calculation_status` passes.

- [ ] **Step 4: Run active rule manifest validation**

Run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python scripts/claim_rule_candidate_review.py --summary'
```

Expected: command exits `0`, and approved/applied rule counts are shown without validation errors.

- [ ] **Step 5: Perform self-inspection against 000번 규칙**

Run:

```bash
rg -n "90%|0\\.9|산정특례.*하드코딩|도수치료.*0\\.3|MRI.*0\\.5" src scripts frontend tests docs/superpowers/plans/2026-07-09-claim-special-case-group-deductible.md
```

Expected:
- No Python calculation code hardcodes insurance payout ratios for 5세대 산정특례.
- Test fixtures may contain expected values.
- The grouped deductible engine code contains no product-specific payout rate.

- [ ] **Step 6: Write implementation report**

Create `docs/266_CLAIM_SPECIAL_CASE_GROUP_DEDUCTIBLE_IMPLEMENTATION_REPORT.md` with:

```markdown
# 5세대 산정특례 및 그룹 합산 공제 구현 보고

## 변경 요약

## 검증 명령과 결과

## 000번 규칙 점검

## 남은 운영 절차

## 남은 위험
```

Fill each section with the actual test commands and observed results from this execution. Do not include raw secrets, user PII, or runtime receipt files.

- [ ] **Step 7: Commit final report**

Run:

```bash
git add docs/266_CLAIM_SPECIAL_CASE_GROUP_DEDUCTIBLE_IMPLEMENTATION_REPORT.md
git diff --name-only --cached
git commit -m "docs(claim): report special case deductible implementation"
```

Expected staged file: only the implementation report.

---

## Self-Review Result

- Spec coverage:
  - 케이스 단위 산정특례 선택: Task 1, Task 2, Task 3.
  - 5세대 3대비급여/MRI-MRA 분기: Task 4, Task 7.
  - 동일 공제 그룹 합산: Task 5.
  - 승인된 rule 유지 및 수정 후보 이력: Task 6, Task 7.
  - 조건부 재계산: Task 8.
  - 000번 규칙 점검: Task 9.
- Placeholder scan:
  - The plan contains no unresolved marker words or generic test instructions.
- Type consistency:
  - `special_calculation_status` is consistently used as `unknown | applied | not_applied`.
  - Replacement candidates consistently use `operation="replace"` and `target_rule_id`.
  - Grouped deductible line metadata consistently uses `deductible_group`.
