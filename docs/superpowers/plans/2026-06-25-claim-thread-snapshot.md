# Claim Thread Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store insurance claim calculations as structured thread snapshots so claim calculation, follow-up general questions, and conditional recalculation can continue in one chat thread.

**Architecture:** Reuse existing `ChatMessage.sources` internal `assistant_meta` storage. Add a `claim_snapshot` payload beside existing graph metadata, render it back into the current claim result card, and summarize all snapshots into general-query prompt context. Conditional recalculation remains deterministic: natural language only selects an existing line and a supported change intent; actual money calculation uses the existing claim pipeline.

**Tech Stack:** FastAPI, SQLAlchemy async models, existing claim calculation pipeline, vanilla frontend JS, pytest, Playwright.

---

## File Structure

Modify:

- `src/api/routes/claim.py`
  Build detailed saved claim text and add internal `claim_snapshot` metadata when persisting claim turns.
- `src/api/rag_service.py`
  Extract all claim snapshots from thread history and inject a compact calculation context into RAG prompts.
- `frontend/js/pages/chat.js`
  Restore claim result cards from `claim_snapshot` when a history thread is opened.
- `frontend/dist/app.min.js`
  Rebuild with `npm --prefix frontend run build` after JS changes.

Create:

- `src/claim_calculation/thread_recalculation.py`
  Minimal deterministic parser and request builder for supported follow-up phrases.
- `tests/test_claim_thread_snapshot.py`
  Backend snapshot text/meta and prompt-context tests.
- `tests/test_claim_thread_recalculation.py`
  Conditional recalculation intent tests.

Modify tests:

- `tests/e2e/chat.spec.js`
  Add one history reload test for claim snapshot card restoration.

Do not modify:

- `src/ui/streamlit_app.py`
- Claim rule manifests
- Ontology manifests
- Raw data or OCR output folders

---

## Task 1: Persist Detailed Claim Snapshots

**Files:**
- Modify: `src/api/routes/claim.py`
- Create: `tests/test_claim_thread_snapshot.py`

- [ ] **Step 1: Write failing backend snapshot tests**

Create `tests/test_claim_thread_snapshot.py` with:

```python
from __future__ import annotations

from src.api.routes import claim
from src.api.schemas.claim import ClaimCalculationRequest, ClaimCalculationResponse, ClaimItemReques


def _response() -> ClaimCalculationResponse:
    return ClaimCalculationResponse(
        session_id="session-1",
        claimed_amount="300000",
        payable_amount="105000",
        deductible="45000",
        formula_intent="deterministic",
        executed_code="",
        applied_basis=[{"source": "약관", "content": "3대비급여 공제 근거"}],
        requires_review=True,
        review_reasons=["미분류 비급여는 급여/비급여 구분 확인이 필요합니다."],
        notes="검토 필요",
        candidates=[],
        policy_generation="4th",
        line_results=[
            {
                "line_id": "line-1",
                "input_name": "도수치료",
                "category": "3대비급여",
                "claimed_amount": "150000",
                "deductible": "45000",
                "payable_amount": "105000",
                "review_reasons": [],
                "calculation_status": "calculated",
                "excluded_from_calculation": False,
                "human_task_amount": "0",
            },
            {
                "line_id": "line-2",
                "input_name": "미분류 비급여",
                "category": "미분류 비급여",
                "claimed_amount": "150000",
                "deductible": "0",
                "payable_amount": "0",
                "review_reasons": ["급여/비급여 구분 확인 필요"],
                "calculation_status": "human_task",
                "excluded_from_calculation": True,
                "human_task_amount": "150000",
            },
        ],
        calculation_status="estimated_review_required",
    )


def test_claim_response_text_includes_line_and_human_task_details() -> None:
    text = claim._claim_response_text(_response())

    assert "항목별 계산" in tex
    assert "도수치료" in tex
    assert "추가 확인 필요 항목" in tex
    assert "미분류 비급여" in tex
    assert "급여/비급여 구분 확인 필요" in tex
    assert "적용 근거 요약" in tex


def test_claim_snapshot_source_stores_structured_payload_without_raw_document() -> None:
    payload = ClaimCalculationRequest(
        items=[ClaimItemRequest(input_name="도수치료", claimed_amount="150000")],
        context={"policy_generation": "4th", "coverage_topic": "실손"},
    )

    source = claim._claim_snapshot_source(payload, _response())

    assert source["__kind"] == "assistant_meta"
    snapshot = source["claim_snapshot"]
    assert snapshot["schema_version"] == 1
    assert snapshot["input"]["items"][0]["input_name"] == "도수치료"
    assert snapshot["result"]["line_results"][1]["calculation_status"] == "human_task"
    assert "raw_text" not in str(snapshot)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py -q
```

Expected: FAIL because `_claim_snapshot_source` does not exist and `_claim_response_text` is still short.

- [ ] **Step 3: Implement minimal snapshot helpers**

In `src/api/routes/claim.py`, add imports:

```python
from datetime import datetime, timezone
from uuid import uuid4
```

Replace `_persist_claim_turn` source handling with:

```python
assistant_sources = list(response.applied_basis or [])
assistant_sources.append(_claim_snapshot_source(payload, response))
```

Use `assistant_sources or None` for the assistant message.

Add:

```python
def _claim_snapshot_source(payload: ClaimCalculationRequest, response: ClaimCalculationResponse) -> dict:
    return {
        "__kind": "assistant_meta",
        "claim_snapshot": {
            "schema_version": 1,
            "claim_id": f"claim-{uuid4().hex[:12]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "items": [item.model_dump(mode="json") for item in payload.items],
                "context": payload.context.model_dump(mode="json"),
            },
            "result": {
                "claimed_amount": response.claimed_amount,
                "deductible": response.deductible,
                "payable_amount": response.payable_amount,
                "policy_generation": response.policy_generation,
                "calculation_status": response.calculation_status,
                "line_results": response.line_results,
                "review_reasons": response.review_reasons,
                "applied_basis": response.applied_basis,
                "notes": response.notes,
                "requires_review": response.requires_review,
            },
        },
    }
```

Replace `_claim_response_text` with a detailed text builder:

```python
def _claim_response_text(response: ClaimCalculationResponse) -> str:
    status = "검토 필요" if response.requires_review else "계산 완료"
    lines = [
        f"보험금 계산 결과: {status}",
        f"- 계산 기준: {'5세대 실손 표준약관' if response.policy_generation == '5th' else '4세대 실손 기준'}",
        f"- 총 청구금액: {response.claimed_amount}원",
        f"- 예상 공제금액: {response.deductible}원",
        f"- 예상 지급금액: {response.payable_amount}원",
        f"- 메모: {response.notes}",
    ]
    if response.line_results:
        lines.append("")
        lines.append("항목별 계산:")
        for line in response.line_results:
            if line.get("calculation_status") == "human_task":
                continue
            lines.append(
                f"- {line.get('input_name', '')} ({line.get('category', '미분류')}): "
                f"청구 {line.get('claimed_amount', '0')}원 / 공제 {line.get('deductible', '0')}원 / "
                f"지급 {line.get('payable_amount', '0')}원"
            )
        human_task_lines = [
            line for line in response.line_results
            if line.get("calculation_status") == "human_task"
            or line.get("calculation_status") == "partial_human_task"
            or str(line.get("human_task_amount", "0")) not in {"", "0"}
        ]
        if human_task_lines:
            lines.append("")
            lines.append("추가 확인 필요 항목:")
            for line in human_task_lines:
                reason = "; ".join(line.get("review_reasons") or [])
                amount = line.get("human_task_amount") or line.get("claimed_amount") or "0"
                suffix = f" - {reason}" if reason else ""
                lines.append(
                    f"- {line.get('input_name', '')} ({line.get('category', '미분류')}): "
                    f"{amount}원은 자동 지급 산정에서 제외됨{suffix}"
                )
    if response.review_reasons:
        lines.append("")
        lines.append("검토 사유:")
        lines.extend(f"- {reason}" for reason in response.review_reasons)
    if response.applied_basis:
        lines.append("")
        lines.append("적용 근거 요약:")
        for basis in response.applied_basis[:4]:
            source = basis.get("source") or basis.get("filename") or "근거"
            content = " ".join(str(basis.get("content") or "").split())[:180]
            lines.append(f"- {source}: {content}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run backend snapshot tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/api/routes/claim.py tests/test_claim_thread_snapshot.py
git commit -m "feat(claim): persist detailed thread snapshots"
```

---

## Task 2: Restore Claim Result Cards From History

**Files:**
- Modify: `frontend/js/pages/chat.js`
- Modify: `frontend/dist/app.min.js`
- Modify: `tests/e2e/chat.spec.js`

- [ ] **Step 1: Add failing Playwright history test**

Append to `tests/e2e/chat.spec.js`:

```javascrip
test('보험금 계산 스냅샷이 있는 내역을 계산 결과 카드로 복원함', async ({ page }) => {
  await page.route('**/api/sessions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 'claim-session', title: '보험금 계산: 도수치료', updated_at: '2026-06-25T00:00:00Z' }]),
    });
  });
  await page.route('**/api/sessions/claim-session/messages', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { role: 'user', content: '[보험금 계산/4세대] 도수치료', sources: [] },
        {
          role: 'assistant',
          content: '보험금 계산 결과: 검토 필요',
          sources: [
            {
              __kind: 'assistant_meta',
              claim_snapshot: {
                schema_version: 1,
                claim_id: 'claim-test',
                input: { items: [], context: {} },
                result: {
                  claimed_amount: '300000',
                  deductible: '45000',
                  payable_amount: '105000',
                  policy_generation: '4th',
                  calculation_status: 'estimated_review_required',
                  requires_review: true,
                  notes: '검토 필요',
                  review_reasons: ['급여/비급여 구분 확인 필요'],
                  applied_basis: [{ source: '약관', content: '근거' }],
                  line_results: [
                    {
                      input_name: '도수치료',
                      category: '3대비급여',
                      claimed_amount: '150000',
                      deductible: '45000',
                      payable_amount: '105000',
                      calculation_status: 'calculated',
                      human_task_amount: '0',
                    },
                    {
                      input_name: '미분류 비급여',
                      category: '미분류 비급여',
                      claimed_amount: '150000',
                      deductible: '0',
                      payable_amount: '0',
                      calculation_status: 'human_task',
                      human_task_amount: '150000',
                      review_reasons: ['급여/비급여 구분 확인 필요'],
                    },
                  ],
                },
              },
            },
          ],
        },
      ]),
    });
  });

  await page.reload();
  await page.click('[data-session-id="claim-session"]');

  await expect(page.locator('.claim-result')).toBeVisible();
  await expect(page.locator('.claim-result')).toContainText('항목별 계산');
  await expect(page.locator('.claim-result')).toContainText('Human Task 분류');
  await expect(page.locator('.claim-result')).toContainText('미분류 비급여');
});
```

- [ ] **Step 2: Run failing frontend test**

Run:

```bash
npm run test:e2e -- tests/e2e/chat.spec.js -g "보험금 계산 스냅샷"
```

Expected: FAIL because `claim_snapshot` is ignored by `extractAssistantUiPayload`.

- [ ] **Step 3: Restore snapshot in existing message renderer**

In `frontend/js/pages/chat.js`, update `extractAssistantUiPayload`:

```javascrip
function extractAssistantUiPayload(sources) {
  const meta = (Array.isArray(sources) ? sources : []).find((source) => source?.__kind === 'assistant_meta');
  if (!meta) return null;
  return {
    graphResult: meta.graph_result || null,
    warnings: Array.isArray(meta.warnings) ? meta.warnings : [],
    claimSnapshot: meta.claim_snapshot || null,
  };
}
```

In `appendMsg`, before building `row.innerHTML`, add:

```javascrip
  const claimSnapshot = role === 'bot' ? (uiPayload?.claimSnapshot || null) : null;
  const claimSnapshotHtml = claimSnapshot?.result ? renderClaimResultHtml(claimSnapshot.result) : '';
  const bubbleContent = claimSnapshotHtml || `${renderAssistantContent(messageText)}${botExtras}${sourceHtml}`;
```

Then replace the current `row.innerHTML = ...` line with:

```javascrip
  row.innerHTML = `${avatar}<div><div class="msg-bubble">${bubbleContent}</div><div class="msg-meta">${time}</div></div>`;
```

- [ ] **Step 4: Build frontend bundle**

Run:

```bash
npm --prefix frontend run build
```

Expected: `frontend/dist/app.min.js` updates successfully.

- [ ] **Step 5: Run frontend test**

Run:

```bash
npm run test:e2e -- tests/e2e/chat.spec.js -g "보험금 계산 스냅샷"
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add frontend/js/pages/chat.js frontend/dist/app.min.js tests/e2e/chat.spec.js
git commit -m "feat(frontend): restore claim snapshots in history"
```

---

## Task 3: Add Claim Snapshot Context to General Queries

**Files:**
- Modify: `src/api/rag_service.py`
- Modify: `tests/test_claim_thread_snapshot.py`

- [ ] **Step 1: Add failing prompt-context test**

Append to `tests/test_claim_thread_snapshot.py`:

```python
from src.api.models import ChatMessage
from src.api.rag_service import build_claim_snapshot_context, build_history_contex


def test_build_claim_snapshot_context_includes_all_thread_calculations() -> None:
    messages = [
        ChatMessage(
            role="assistant",
            content="계산 1",
            sources=[
                {
                    "__kind": "assistant_meta",
                    "claim_snapshot": {
                        "schema_version": 1,
                        "claim_id": "claim-1",
                        "result": {
                            "payable_amount": "105000",
                            "deductible": "45000",
                            "line_results": [
                                {"input_name": "도수치료", "category": "3대비급여", "payable_amount": "105000"},
                                {
                                    "input_name": "미분류 비급여",
                                    "category": "미분류 비급여",
                                    "human_task_amount": "150000",
                                    "calculation_status": "human_task",
                                    "review_reasons": ["급여/비급여 구분 확인 필요"],
                                },
                            ],
                            "review_reasons": ["급여/비급여 구분 확인 필요"],
                        },
                    },
                }
            ],
        ),
        ChatMessage(
            role="assistant",
            content="계산 2",
            sources=[
                {
                    "__kind": "assistant_meta",
                    "claim_snapshot": {
                        "schema_version": 1,
                        "claim_id": "claim-2",
                        "result": {
                            "payable_amount": "80000",
                            "deductible": "20000",
                            "line_results": [{"input_name": "진찰료", "category": "급여", "payable_amount": "80000"}],
                            "review_reasons": [],
                        },
                    },
                }
            ],
        ),
    ]

    context = build_claim_snapshot_context(messages)

    assert "[이 스레드의 보험금 계산 내역]" in contex
    assert "계산 1" in contex
    assert "계산 2" in contex
    assert "미분류 비급여" in contex
    assert "급여/비급여 구분 확인 필요" in contex


def test_build_history_context_prepends_claim_snapshot_context() -> None:
    messages = [
        ChatMessage(
            role="assistant",
            content="보험금 계산 결과",
            sources=[
                {
                    "__kind": "assistant_meta",
                    "claim_snapshot": {
                        "schema_version": 1,
                        "claim_id": "claim-1",
                        "result": {"payable_amount": "105000", "deductible": "45000", "line_results": [], "review_reasons": []},
                    },
                }
            ],
        )
    ]

    context = build_history_context(messages)

    assert context.startswith("[이 스레드의 보험금 계산 내역]")
    assert "예상 지급금액: 105000원" in contex
```

- [ ] **Step 2: Run failing prompt-context tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py -q
```

Expected: FAIL because `build_claim_snapshot_context` does not exist.

- [ ] **Step 3: Implement compact context builder**

In `src/api/rag_service.py`, add:

```python
def _extract_claim_snapshots(messages: list[ChatMessage]) -> list[dict]:
    snapshots = []
    for message in messages:
        for source in message.sources or []:
            if source.get("__kind") == "assistant_meta" and isinstance(source.get("claim_snapshot"), dict):
                snapshots.append(source["claim_snapshot"])
    return snapshots


def build_claim_snapshot_context(messages: list[ChatMessage], max_chars: int = 4000) -> str:
    snapshots = _extract_claim_snapshots(messages)
    if not snapshots:
        return ""
    lines = ["[이 스레드의 보험금 계산 내역]"]
    for index, snapshot in enumerate(snapshots, start=1):
        result = snapshot.get("result") or {}
        lines.append(f"계산 {index}:")
        lines.append(f"- 예상 지급금액: {result.get('payable_amount', '0')}원")
        lines.append(f"- 예상 공제금액: {result.get('deductible', '0')}원")
        human_lines = [
            line for line in result.get("line_results") or []
            if line.get("calculation_status") in {"human_task", "partial_human_task"}
            or str(line.get("human_task_amount", "0")) not in {"", "0"}
        ]
        if human_lines:
            lines.append("- 추가 확인 필요:")
            for line in human_lines:
                reason = "; ".join(line.get("review_reasons") or [])
                amount = line.get("human_task_amount") or line.get("claimed_amount") or "0"
                lines.append(f"  - {line.get('input_name', '')} ({line.get('category', '미분류')}): {amount}원 / {reason}")
        for reason in result.get("review_reasons") or []:
            lines.append(f"- 검토 사유: {reason}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return tex
    return text[: max_chars - 1].rstrip() + "…"
```

Update `build_history_context`:

```python
def build_history_context(messages: list[ChatMessage]) -> str:
    if not messages:
        return ""
    parts = []
    claim_context = build_claim_snapshot_context(messages)
    if claim_context:
        parts.append(claim_context)
    recent = messages[-4:]
    lines = ["[최근 대화 참고]"]
    for message in recent:
        content = " ".join(message.content.split())
        lines.append(f"{message.role}: {content[:260]}")
    parts.append("\n".join(lines))
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run prompt-context tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py -q
```

Expected: PASS.

- [ ] **Step 5: Run chat-stream regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/api/rag_service.py tests/test_claim_thread_snapshot.py
git commit -m "feat(chat): include claim snapshots in thread context"
```

---

## Task 4: Add Conditional Recalculation Intent Skeleton

**Files:**
- Create: `src/claim_calculation/thread_recalculation.py`
- Create: `tests/test_claim_thread_recalculation.py`

This task does not wire the parser into `/chat/stream` yet. It creates the safe deterministic core first. Wiring it into chat should be a separate follow-up after the parser behavior is stable.

- [ ] **Step 1: Write failing deterministic parser tests**

Create `tests/test_claim_thread_recalculation.py`:

```python
from __future__ import annotations

from src.claim_calculation.thread_recalculation import detect_recalculation_intent, find_target_line


SNAPSHOT = {
    "result": {
        "line_results": [
            {"input_name": "도수치료", "category": "3대비급여", "claimed_amount": "150000"},
            {
                "input_name": "미분류 비급여",
                "category": "미분류 비급여",
                "claimed_amount": "120000",
                "human_task_amount": "120000",
                "calculation_status": "human_task",
            },
        ]
    }
}


def test_detects_not_covered_condition() -> None:
    intent = detect_recalculation_intent("미분류 비급여 항목을 보상하지 않는다면 얼마인가요?")

    assert intent.action == "not_covered"
    assert intent.target_text == "미분류 비급여"


def test_detects_insured_copay_condition() -> None:
    intent = detect_recalculation_intent("미분류 비급여가 급여 본인부담으로 확인됐다면 다시 계산해 주세요")

    assert intent.action == "as_insured_copay"
    assert intent.target_text == "미분류 비급여"


def test_covered_without_category_requires_clarification() -> None:
    intent = detect_recalculation_intent("미분류 비급여를 보상한다면 얼마인가요?")

    assert intent.action == "covered_unspecified"
    assert intent.needs_clarification is True


def test_find_target_line_by_substring() -> None:
    line = find_target_line(SNAPSHOT, "미분류 비급여")

    assert line["claimed_amount"] == "120000"
```

- [ ] **Step 2: Run failing parser tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_recalculation.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement minimal parser**

Create `src/claim_calculation/thread_recalculation.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecalculationIntent:
    action: str
    target_text: str
    needs_clarification: bool = False


def detect_recalculation_intent(query: str) -> RecalculationIntent | None:
    text = " ".join(query.split())
    target = _target_before_marker(text)
    if not target:
        return None
    if "보상하지 않는다면" in text or "보상 제외" in text:
        return RecalculationIntent("not_covered", target)
    if "급여 본인부담" in text:
        return RecalculationIntent("as_insured_copay", target)
    if "3대비급여" in text:
        return RecalculationIntent("as_three_major_nonpay", target)
    if "비급여" in text and target != "비급여":
        return RecalculationIntent("as_nonpay", target)
    if "보상한다면" in text:
        return RecalculationIntent("covered_unspecified", target, needs_clarification=True)
    return None


def find_target_line(snapshot: dict, target_text: str) -> dict | None:
    target = target_text.strip()
    if not target:
        return None
    for line in (snapshot.get("result") or {}).get("line_results") or []:
        name = str(line.get("input_name") or "")
        category = str(line.get("category") or "")
        if target in name or target in category or name in target:
            return line
    return None


def _target_before_marker(text: str) -> str:
    markers = ["항목을", "항목은", "을", "를", "가", "이"]
    for marker in markers:
        if marker in text:
            return text.split(marker, 1)[0].strip()
    return ""
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_recalculation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/claim_calculation/thread_recalculation.py tests/test_claim_thread_recalculation.py
git commit -m "feat(claim): add thread recalculation intent parser"
```

---

## Final Validation

- [ ] Run backend focused tests:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
```

Expected: PASS.

- [ ] Run frontend build:

```bash
npm --prefix frontend run build
```

Expected: build completes and `frontend/dist/app.min.js` is updated.

- [ ] Run focused e2e:

```bash
npm run test:e2e -- tests/e2e/chat.spec.js -g "보험금 계산 스냅샷"
```

Expected: PASS.

- [ ] Self-inspection:

```bash
git status --shor
rg -n "T[B]D|TO[D]O|F[I]XME|raw_text|주민등록|전화번호" src frontend/js tests docs/superpowers/plans/2026-06-25-claim-thread-snapshot.md
```

Expected: no new placeholder text, no raw document or sensitive-field snapshot storage.

---

## Deferred Work

Do not wire conditional recalculation into `/chat/stream` in this plan. Task 4 creates the safe deterministic core only. A follow-up plan should connect the parser to chat streaming, build modified `ClaimCalculationRequest` objects, and call `run_claim_calculation` only when the target line and change intent are unambiguous.
