# Claim Thread Conditional Recalculation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a normal chat message in an existing claim-calculation thread ask for a deterministic follow-up recalculation, while asking the user to clarify unsafe or ambiguous requests.

**Architecture:** Keep insurance money logic inside the existing claim calculation pipeline. The chat route only detects a narrow follow-up intent, selects one stored claim snapshot and one line item, builds a modified `ClaimCalculationRequest`, and persists the answer back into the same chat thread. Ambiguous requests return a Korean clarification answer and do not call RAG or the claim pipeline.

**Tech Stack:** FastAPI streaming route, SQLAlchemy chat history, Pydantic claim schemas, existing claim calculation pipeline, pytest/anyio.

---

## File Structure

- Modify `src/claim_calculation/thread_recalculation.py`
  Owns deterministic Korean intent parsing, target-line matching, snapshot selection helpers, and request-payload construction from stored `claim_snapshot`.

- Modify `src/api/routes/chat.py`
  Wires follow-up recalculation handling into `/chat/stream` before normal RAG retrieval. It persists clarification answers and recalculated claim answers as normal chat turns in the same session.

- Modify `tests/test_claim_thread_recalculation.py`
  Unit tests for parser, ambiguity detection, target matching, and request payload construction.

- Modify `tests/test_api_chat_stream.py`
  API streaming tests for clarification paths and one successful explicit-category recalculation path.

- Create `docs/256_CLAIM_THREAD_CONDITIONAL_RECALCULATION_REPORT.md`
  Implementation report with changed files, behavior boundaries, validation commands, and remaining risks.

This plan intentionally does not change frontend rendering. Existing history restoration already renders saved `claim_snapshot` cards; this patch makes chat-stream follow-up answers create the same metadata when a recalculation actually runs.

## Task 1: Deterministic Recalculation Helpers

**Files:**
- Modify: `src/claim_calculation/thread_recalculation.py`
- Modify: `tests/test_claim_thread_recalculation.py`

- [x] **Step 1: Add failing helper tests**

Append these tests to `tests/test_claim_thread_recalculation.py`:

```python
def test_find_target_lines_reports_ambiguous_substring_matches() -> None:
    snapshot = {
        "result": {
            "line_results": [
                {"line_id": "line-1", "input_name": "비타민D 주사", "category": "미분류 비급여"},
                {"line_id": "line-2", "input_name": "비타민D 검사", "category": "미분류 비급여"},
            ]
        }
    }

    matches = find_target_lines(snapshot, "비타민D")

    assert [line["line_id"] for line in matches] == ["line-1", "line-2"]


def test_select_claim_snapshot_requires_clarification_when_multiple_without_selector() -> None:
    snapshots = [{"claim_id": "claim-1"}, {"claim_id": "claim-2"}]

    selected, clarification = select_claim_snapshot(snapshots, "이 항목을 보상하지 않는다면?")

    assert selected is None
    assert "여러 건" in clarification
    assert "최근 계산" in clarification


def test_select_claim_snapshot_uses_latest_when_query_says_recent() -> None:
    snapshots = [{"claim_id": "claim-1"}, {"claim_id": "claim-2"}]

    selected, clarification = select_claim_snapshot(snapshots, "최근 계산 기준으로 비타민D 주사를 보상하지 않는다면?")

    assert selected == snapshots[-1]
    assert clarification == ""


def test_build_recalculation_payload_reclassifies_target_line_only() -> None:
    snapshot = {
        "input": {
            "items": [
                {
                    "line_id": "line-1",
                    "input_name": "도수치료",
                    "claimed_amount": "150000",
                    "insured_copay_amount": "0",
                    "nonpay_amount": "150000",
                    "quantity": "1",
                    "user_category_hint": "3대비급여",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "claimed_amount": "48000",
                    "insured_copay_amount": "0",
                    "nonpay_amount": "48000",
                    "quantity": "1",
                    "user_category_hint": "",
                },
            ],
            "context": {"policy_generation": "4th", "visit_type": "outpatient", "coverage_topic": "실손"},
        },
        "result": {
            "line_results": [
                {"line_id": "line-1", "input_name": "도수치료", "claimed_amount": "150000"},
                {"line_id": "line-2", "input_name": "비타민D 주사", "claimed_amount": "48000"},
            ]
        },
    }
    intent = RecalculationIntent(action="as_insured_copay", target_text="비타민D 주사")
    target_line = find_target_lines(snapshot, "비타민D 주사")[0]

    payload = build_recalculation_payload(snapshot, intent, target_line)

    assert payload["items"][0]["input_name"] == "도수치료"
    assert payload["items"][0]["user_category_hint"] == "3대비급여"
    assert payload["items"][1]["input_name"] == "비타민D 주사"
    assert payload["items"][1]["insured_copay_amount"] == "48000"
    assert payload["items"][1]["nonpay_amount"] == "0"
    assert payload["items"][1]["user_category_hint"] == "급여 본인부담"
    assert payload["context"]["policy_generation"] == "4th"
```

Update the import block in the same test file to include the new helper names:

```python
from src.claim_calculation.thread_recalculation import (
    RecalculationIntent,
    build_recalculation_payload,
    detect_recalculation_intent,
    find_target_line,
    find_target_lines,
    select_claim_snapshot,
)
```

- [x] **Step 2: Run helper tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_recalculation.py -q
```

Expected: fails because `find_target_lines`, `select_claim_snapshot`, and `build_recalculation_payload` are not implemented.

- [x] **Step 3: Implement helper functions**

Replace `src/claim_calculation/thread_recalculation.py` with this focused implementation:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


_GENERIC_CATEGORY_TARGETS = {"비급여", "3대비급여", "급여", "급여 본인부담"}


@dataclass(frozen=True)
class RecalculationIntent:
    action: str
    target_text: str
    needs_clarification: bool = False


def detect_recalculation_intent(query: str) -> RecalculationIntent | None:
    text = " ".join(query.split())
    target_text = _target_before_marker(text)
    if not target_text:
        return None

    if "보상하지 않는다면" in text or "보상 제외" in text:
        return RecalculationIntent(action="not_covered", target_text=target_text)
    if "급여 본인부담" in text:
        return RecalculationIntent(action="as_insured_copay", target_text=target_text)
    if "3대비급여" in text:
        return RecalculationIntent(action="as_three_major_nonpay", target_text=target_text)
    if "비급여로" in text and target_text != "비급여":
        return RecalculationIntent(action="as_nonpay", target_text=target_text)
    if "보상한다면" in text:
        return RecalculationIntent(
            action="covered_unspecified",
            target_text=target_text,
            needs_clarification=True,
        )

    return None


def select_claim_snapshot(snapshots: list[dict], query: str) -> tuple[dict | None, str]:
    if not snapshots:
        return None, "이 스레드에는 기준이 되는 보험금 계산 내역이 없습니다. 먼저 보험금 계산 기능으로 계산을 저장한 뒤 다시 질문해 주세요."
    if len(snapshots) == 1:
        return snapshots[0], ""

    normalized = " ".join(query.split())
    if any(marker in normalized for marker in ("최근 계산", "마지막 계산", "직전 계산")):
        return snapshots[-1], ""

    return (
        None,
        "이 스레드에 보험금 계산 내역이 여러 건 있습니다. 어떤 계산을 기준으로 바꿀지 명확하지 않습니다. 예: '최근 계산 기준으로 비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요.'",
    )


def find_target_line(snapshot: dict, target_text: str) -> dict | None:
    matches = find_target_lines(snapshot, target_text)
    return matches[0] if len(matches) == 1 else None


def find_target_lines(snapshot: dict, target_text: str) -> list[dict]:
    target = target_text.strip()
    if not target or target in _GENERIC_CATEGORY_TARGETS:
        return []

    lines = _snapshot_lines(snapshot)
    exact = [line for line in lines if str(line.get("input_name") or "") == target]
    if exact:
        return _unique_lines(exact)

    substring = [
        line
        for line in lines
        if (name := str(line.get("input_name") or ""))
        and (target in name or name in target)
    ]
    if substring:
        return _unique_lines(substring)

    category = [line for line in lines if str(line.get("category") or "") == target]
    return _unique_lines(category)


def build_recalculation_payload(snapshot: dict, intent: RecalculationIntent, target_line: dict) -> dict:
    input_payload = snapshot.get("input") or {}
    items = [item for item in input_payload.get("items") or [] if isinstance(item, dict)]
    context = dict(input_payload.get("context") or {})
    target_line_id = str(target_line.get("line_id") or "")
    target_name = str(target_line.get("input_name") or "")

    rebuilt_items = []
    for index, item in enumerate(items):
        rebuilt = _safe_item_payload(item, index)
        is_target = (
            target_line_id
            and str(item.get("line_id") or "") == target_line_id
        ) or (
            target_name
            and str(item.get("input_name") or "") == target_name
        )
        if is_target:
            amount = _target_amount(target_line, item)
            rebuilt.update(_category_override(intent.action, amount))
        rebuilt_items.append(rebuilt)

    if not rebuilt_items:
        for index, line in enumerate(_snapshot_lines(snapshot)):
            rebuilt = _line_to_item_payload(line, index)
            if line is target_line:
                amount = _target_amount(target_line, {})
                rebuilt.update(_category_override(intent.action, amount))
            rebuilt_items.append(rebuilt)

    return {"items": rebuilt_items, "context": context}


def line_payable_amount(line: dict) -> Decimal:
    return _money(line.get("payable_amount"))


def snapshot_payable_amount(snapshot: dict) -> Decimal:
    result = snapshot.get("result") or {}
    return _money(result.get("payable_amount"))


def money_text(value: Decimal) -> str:
    return f"{int(value):,}"


def _snapshot_lines(snapshot: dict) -> list[dict]:
    result = snapshot.get("result") or {}
    return [line for line in result.get("line_results") or [] if isinstance(line, dict)]


def _unique_lines(lines: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for line in lines:
        key = (str(line.get("line_id") or ""), str(line.get("input_name") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _safe_item_payload(item: dict, index: int) -> dict:
    return {
        "line_id": str(item.get("line_id") or f"line-{index + 1}"),
        "input_name": str(item.get("input_name") or f"항목 {index + 1}"),
        "input_code": str(item.get("input_code") or ""),
        "claimed_amount": str(item.get("claimed_amount") or "0"),
        "insured_copay_amount": str(item.get("insured_copay_amount") or "0"),
        "nonpay_amount": str(item.get("nonpay_amount") or "0"),
        "quantity": str(item.get("quantity") or "1"),
        "user_category_hint": str(item.get("user_category_hint") or ""),
        "extra_info": "",
    }


def _line_to_item_payload(line: dict, index: int) -> dict:
    return {
        "line_id": str(line.get("line_id") or f"line-{index + 1}"),
        "input_name": str(line.get("input_name") or f"항목 {index + 1}"),
        "input_code": str(line.get("input_code") or ""),
        "claimed_amount": str(line.get("claimed_amount") or "0"),
        "insured_copay_amount": str(line.get("insured_copay_amount") or "0"),
        "nonpay_amount": str(line.get("nonpay_amount") or "0"),
        "quantity": "1",
        "user_category_hint": str(line.get("category") or ""),
        "extra_info": "",
    }


def _target_amount(line: dict, item: dict) -> str:
    for key in ("claimed_amount", "human_task_amount", "nonpay_amount", "insured_copay_amount"):
        value = line.get(key)
        if _money(value) > 0:
            return str(value)
    for key in ("claimed_amount", "nonpay_amount", "insured_copay_amount"):
        value = item.get(key)
        if _money(value) > 0:
            return str(value)
    return "0"


def _category_override(action: str, amount: str) -> dict:
    if action == "as_insured_copay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": amount,
            "nonpay_amount": "0",
            "user_category_hint": "급여 본인부담",
        }
    if action == "as_three_major_nonpay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": "0",
            "nonpay_amount": amount,
            "user_category_hint": "3대비급여",
        }
    if action == "as_nonpay":
        return {
            "claimed_amount": amount,
            "insured_copay_amount": "0",
            "nonpay_amount": amount,
            "user_category_hint": "비급여",
        }
    return {}


def _money(value: Any) -> Decimal:
    text = str(value or "").replace(",", "").replace("원", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _target_before_marker(text: str) -> str:
    condition_markers = [
        "보상하지",
        "보상 제외",
        "급여 본인부담",
        "3대비급여",
        "비급여로",
        "보상한다면",
    ]
    condition_start = min(
        [text.find(marker) for marker in condition_markers if marker in text] or [len(text)]
    )
    specific_markers = ["항목을", "항목은"]
    for marker in specific_markers:
        index = text.rfind(marker, 0, condition_start)
        if index != -1:
            return text[:index].strip()

    target_markers = ["을", "를", "가", "이", "은", "는"]
    matches = [
        (index, -len(marker), marker)
        for marker in target_markers
        if (index := text.rfind(marker, 0, condition_start)) != -1
    ]
    if matches:
        index, _, _ = max(matches)
        return text[:index].strip()
    return ""
```

- [x] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_recalculation.py -q
```

Expected: all tests in this file pass.

## Task 2: Chat Stream Follow-Up Orchestration

**Files:**
- Modify: `src/api/routes/chat.py`
- Modify: `tests/test_api_chat_stream.py`

- [x] **Step 1: Add failing chat-stream tests**

Append these tests to `tests/test_api_chat_stream.py`:

```python
def _claim_snapshot_source_for_chat(
    *,
    claim_id: str = "claim-1",
    payable_amount: str = "105000",
    line_results: list[dict] | None = None,
    input_items: list[dict] | None = None,
) -> dict:
    return {
        "__kind": "assistant_meta",
        "claim_snapshot": {
            "schema_version": 1,
            "claim_id": claim_id,
            "input": {
                "items": input_items
                or [
                    {
                        "line_id": "line-1",
                        "input_name": "도수치료",
                        "claimed_amount": "150000",
                        "insured_copay_amount": "0",
                        "nonpay_amount": "150000",
                        "quantity": "1",
                        "user_category_hint": "3대비급여",
                    },
                    {
                        "line_id": "line-2",
                        "input_name": "비타민D 주사",
                        "claimed_amount": "48000",
                        "insured_copay_amount": "0",
                        "nonpay_amount": "48000",
                        "quantity": "1",
                        "user_category_hint": "",
                    },
                ],
                "context": {"policy_generation": "4th", "visit_type": "outpatient", "coverage_topic": "실손"},
            },
            "result": {
                "payable_amount": payable_amount,
                "deductible": "45000",
                "line_results": line_results
                or [
                    {
                        "line_id": "line-1",
                        "input_name": "도수치료",
                        "category": "3대비급여",
                        "claimed_amount": "150000",
                        "deductible": "45000",
                        "payable_amount": "105000",
                        "calculation_status": "calculated",
                        "human_task_amount": "0",
                    },
                    {
                        "line_id": "line-2",
                        "input_name": "비타민D 주사",
                        "category": "미분류 비급여",
                        "claimed_amount": "48000",
                        "deductible": "0",
                        "payable_amount": "0",
                        "calculation_status": "human_task",
                        "human_task_amount": "48000",
                        "review_reasons": ["급여/비급여 구분 확인 필요"],
                    },
                ],
                "review_reasons": ["급여/비급여 구분 확인 필요"],
            },
        },
    }


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_for_unspecified_covered_recalculation(db_session, monkeypatch) -> None:
    def fail_pipeline(*_args, **_kwargs):
        raise AssertionError("clarification path must not call RAG")

    monkeypatch.setattr(chat, "get_rag_pipeline", fail_pipeline)
    created = await sessions.create_session(SessionCreateRequest(title="보험금 계산"), _user(), db_session)
    db_session.add(ChatMessage(session_id=created.id, role="assistant", content="보험금 계산 결과", sources=[_claim_snapshot_source_for_chat()]))
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D 주사를 보상한다면 얼마인가요?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = "".join([chunk async for chunk in response.body_iterator])

    assert "급여 본인부담/비급여/3대비급여" in stream
    assert "event: done" in stream


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_when_multiple_claim_snapshots_are_unclear(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no RAG")))
    created = await sessions.create_session(SessionCreateRequest(title="여러 계산"), _user(), db_session)
    db_session.add_all(
        [
            ChatMessage(session_id=created.id, role="assistant", content="첫 계산", sources=[_claim_snapshot_source_for_chat(claim_id="claim-1")]),
            ChatMessage(session_id=created.id, role="assistant", content="둘째 계산", sources=[_claim_snapshot_source_for_chat(claim_id="claim-2")]),
        ]
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D 주사를 비급여로 보상한다면?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = "".join([chunk async for chunk in response.body_iterator])

    assert "여러 건" in stream
    assert "최근 계산" in stream


@pytest.mark.anyio
async def test_chat_stream_asks_clarification_when_target_line_is_ambiguous(db_session, monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_rag_pipeline", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no RAG")))
    created = await sessions.create_session(SessionCreateRequest(title="항목 모호"), _user(), db_session)
    db_session.add(
        ChatMessage(
            session_id=created.id,
            role="assistant",
            content="보험금 계산 결과",
            sources=[
                _claim_snapshot_source_for_chat(
                    line_results=[
                        {"line_id": "line-1", "input_name": "비타민D 주사", "category": "미분류 비급여", "claimed_amount": "48000"},
                        {"line_id": "line-2", "input_name": "비타민D 검사", "category": "미분류 비급여", "claimed_amount": "20000"},
                    ]
                )
            ],
        )
    )
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D를 비급여로 보상한다면?", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = "".join([chunk async for chunk in response.body_iterator])

    assert "여러 항목" in stream
    assert "비타민D 주사" in stream
    assert "비타민D 검사" in stream
```

- [x] **Step 2: Run chat-stream tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py -q
```

Expected: new tests fail because `/chat/stream` has not intercepted claim follow-up intents.

- [x] **Step 3: Implement chat-stream interception**

In `src/api/routes/chat.py`, add these imports near existing imports:

```python
from src.api.routes.claim import _claim_response_text, _claim_snapshot_source
from src.api.schemas.claim import ClaimCalculationRequest, ClaimCalculationResponse, ClaimItemRequest
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation
from src.claim_calculation.thread_recalculation import (
    build_recalculation_payload,
    detect_recalculation_intent,
    find_target_lines,
    line_payable_amount,
    money_text,
    select_claim_snapshot,
    snapshot_payable_amount,
)
```

Add a lightweight result dataclass after `MODEL_ALIAS`:

```python
class _ClaimFollowUpResult:
    def __init__(self, answer: str, sources: list[dict] | None = None):
        self.answer = answer
        self.sources = sources or []
```

In `event_generator`, after `yield _sse("status", "searching")` and before route resolution/RAG pipeline setup, call:

```python
            claim_follow_up = await _handle_claim_follow_up(
                db=db,
                chat_session_id=chat_session.id,
                query=chat_request.query,
                history=history,
                selected_model=selected_model,
                index_mode=effective_index_mode,
            )
            if claim_follow_up is not None:
                yield _sse("sources", claim_follow_up.sources)
                yield _sse("final", {"answer": claim_follow_up.answer})
                yield _sse("done", {"session_id": chat_session.id, "answer": claim_follow_up.answer})
                await _persist_turn(
                    db,
                    chat_session.id,
                    chat_request.query,
                    claim_follow_up.answer,
                    claim_follow_up.sources,
                )
                await log_audit_event(
                    db,
                    "CHAT_QUERY",
                    user_id=user.username,
                    ip_address=_client_ip(request),
                    detail={
                        "model": selected_model,
                        "mode": chat_request.mode,
                        "resolved_route": "claim_follow_up",
                        "top_k": chat_request.top_k,
                        "temperature": chat_request.temperature,
                        "index_mode": requested_index_mode,
                        "effective_index_mode": effective_index_mode,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        "session_id": chat_session.id,
                        "source_count": len(claim_follow_up.sources),
                        "query_preview": chat_request.query.strip()[:200],
                        "request_id": getattr(getattr(request, "state", None), "request_id", None),
                    },
                )
                return
```

Add helper functions before `_select_model`:

```python
async def _handle_claim_follow_up(
    *,
    db: AsyncSession,
    chat_session_id: str,
    query: str,
    history: list[ChatMessage],
    selected_model: str,
    index_mode: str,
) -> _ClaimFollowUpResult | None:
    intent = detect_recalculation_intent(query)
    if intent is None:
        return None

    snapshots = _claim_snapshots_from_history(history)
    snapshot, clarification = select_claim_snapshot(snapshots, query)
    if snapshot is None:
        return _ClaimFollowUpResult(clarification)
    if intent.needs_clarification:
        return _ClaimFollowUpResult(
            "어떤 기준으로 보상할지 명확하지 않습니다. 급여 본인부담/비급여/3대비급여 중 하나를 포함해 다시 질문해 주세요. 예: '비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요.'"
        )

    matches = find_target_lines(snapshot, intent.target_text)
    if not matches:
        return _ClaimFollowUpResult(_target_not_found_answer(snapshot, intent.target_text))
    if len(matches) > 1:
        return _ClaimFollowUpResult(_ambiguous_target_answer(matches))

    target_line = matches[0]
    if intent.action == "not_covered":
        return _ClaimFollowUpResult(_not_covered_answer(snapshot, target_line))

    payload_data = build_recalculation_payload(snapshot, intent, target_line)
    payload = ClaimCalculationRequest(
        session_id=chat_session_id,
        save_to_history=False,
        items=[ClaimItemRequest(**item) for item in payload_data["items"]],
        context=payload_data.get("context") or {},
        model=selected_model,
        provider=_provider_from_model_id(selected_model),
        index_mode=index_mode if index_mode in {"v2_only", "v1_v2_combined"} else "v2_only",
    )
    pipeline = _get_pipeline(selected_model, config.CLAIM_RAG_TOP_K, payload.index_mode)
    result = run_claim_calculation(
        rag_pipeline=pipeline,
        items=[
            ClaimItemInput(
                line_id=item.line_id or f"line-{idx + 1}",
                input_name=item.input_name,
                input_code=item.input_code,
                claimed_amount=item.claimed_amount,
                insured_copay_amount=item.insured_copay_amount,
                nonpay_amount=item.nonpay_amount,
                quantity=item.quantity,
                user_category_hint=item.user_category_hint,
                extra_info=item.extra_info,
            )
            for idx, item in enumerate(payload.items)
        ],
        context=ClaimCaseContext(**payload.context.model_dump()),
        basis_mode=payload.basis_mode,
        selected_basis_docs=payload.selected_basis_docs,
        use_fake_planner=payload.use_fake_planner,
        model_id=selected_model.split(":", 1)[1] if ":" in selected_model else selected_model,
        provider=payload.provider or _provider_from_model_id(selected_model),
    )
    response = ClaimCalculationResponse.from_result(result)
    sources = list(response.applied_basis or []) + [_claim_snapshot_source(payload, response)]
    return _ClaimFollowUpResult(_claim_response_text(response), sources)
```

Add these local helper functions below it:

```python
def _claim_snapshots_from_history(history: list[ChatMessage]) -> list[dict]:
    snapshots: list[dict] = []
    for message in history:
        if message.role != "assistant":
            continue
        for source in message.sources or []:
            if isinstance(source, dict) and source.get("__kind") == "assistant_meta":
                snapshot = source.get("claim_snapshot")
                if isinstance(snapshot, dict):
                    snapshots.append(snapshot)
    return snapshots


def _target_not_found_answer(snapshot: dict, target_text: str) -> str:
    names = _snapshot_line_names(snapshot)
    suffix = f" 현재 계산에 저장된 항목은 {', '.join(names[:8])}입니다." if names else ""
    return f"'{target_text}'에 해당하는 계산 항목을 찾지 못했습니다. 항목명을 계산 결과의 항목명과 같게 적어 다시 질문해 주세요.{suffix}"


def _ambiguous_target_answer(matches: list[dict]) -> str:
    names = [str(line.get("input_name") or "항목명 없음") for line in matches[:8]]
    return "요청한 항목명이 여러 항목과 맞습니다. 다음 중 하나의 항목명을 그대로 적어 다시 질문해 주세요: " + ", ".join(names)


def _not_covered_answer(snapshot: dict, target_line: dict) -> str:
    previous = snapshot_payable_amount(snapshot)
    removed = line_payable_amount(target_line)
    updated = previous - removed
    if updated < 0:
        updated = type(previous)("0")
    target_name = str(target_line.get("input_name") or "해당 항목")
    if removed == 0:
        return (
            f"{target_name}은 기존 계산에서 예상 지급금액 0원으로 반영되어 있었습니다. "
            f"따라서 보상하지 않는다고 보아도 기존 예상 지급금액 {money_text(previous)}원은 변하지 않습니다."
        )
    return (
        f"{target_name}을 보상하지 않는다고 보면 기존 예상 지급금액 {money_text(previous)}원에서 "
        f"해당 항목 지급액 {money_text(removed)}원을 제외해 예상 지급금액은 {money_text(updated)}원입니다."
    )


def _snapshot_line_names(snapshot: dict) -> list[str]:
    result = snapshot.get("result") or {}
    names = []
    for line in result.get("line_results") or []:
        if isinstance(line, dict) and line.get("input_name"):
            names.append(str(line["input_name"]))
    return list(dict.fromkeys(names))


def _provider_from_model_id(model: str) -> str:
    if ":" in model:
        return model.split(":", 1)[0]
    return "openai" if model.startswith("gpt-") else "vllm"
```

- [x] **Step 4: Run chat-stream tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py -q
```

Expected: all tests in this file pass.

## Task 3: Successful Explicit Recalculation Test

**Files:**
- Modify: `tests/test_api_chat_stream.py`
- Modify: `src/api/routes/chat.py` only if the test exposes a defect in Task 2.

- [x] **Step 1: Add a successful recalculation stream test**

Append this test to `tests/test_api_chat_stream.py`:

```python
@pytest.mark.anyio
async def test_chat_stream_runs_recalculation_when_category_and_target_are_clear(db_session, monkeypatch) -> None:
    captured = {}

    class FakeClaimPipeline:
        pass

    def fake_pipeline(model, top_k, index_mode="v2_only"):
        captured["pipeline"] = {"model": model, "top_k": top_k, "index_mode": index_mode}
        return FakeClaimPipeline()

    def fake_run_claim_calculation(**kwargs):
        captured["items"] = kwargs["items"]
        captured["context"] = kwargs["context"]
        from src.claim_calculation.models import CalculationResult

        return CalculationResult(
            claimed_amount="198000",
            payable_amount="143400",
            deductible="54600",
            formula_intent="thread_recalculation",
            executed_code="",
            applied_basis=[{"source": "테스트 근거", "content": "재계산 근거"}],
            requires_review=False,
            review_reasons=[],
            notes="재계산 완료",
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
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
                {
                    "line_id": "line-2",
                    "input_name": "비타민D 주사",
                    "category": "비급여",
                    "claimed_amount": "48000",
                    "deductible": "9600",
                    "payable_amount": "38400",
                    "calculation_status": "calculated",
                    "human_task_amount": "0",
                },
            ],
            calculation_status="auto_calculated",
        )

    monkeypatch.setattr(chat, "get_rag_pipeline", fake_pipeline)
    monkeypatch.setattr(chat, "run_claim_calculation", fake_run_claim_calculation)
    created = await sessions.create_session(SessionCreateRequest(title="재계산"), _user(), db_session)
    db_session.add(ChatMessage(session_id=created.id, role="assistant", content="보험금 계산 결과", sources=[_claim_snapshot_source_for_chat()]))
    await db_session.commit()

    response = await chat.chat_stream(
        ChatRequest(query="비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요", session_id=created.id, model="gemma3:4b"),
        None,
        _user(),
        db_session,
    )
    stream = "".join([chunk async for chunk in response.body_iterator])
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == created.id).order_by(ChatMessage.id.asc())
    )
    messages = list(result.scalars())

    assert captured["pipeline"]["top_k"] == chat.config.CLAIM_RAG_TOP_K
    assert captured["items"][1].input_name == "비타민D 주사"
    assert captured["items"][1].nonpay_amount == "48000"
    assert captured["items"][1].user_category_hint == "비급여"
    assert "예상 지급금액: 143400원" in stream
    assert messages[-1].role == "assistant"
    assert messages[-1].sources[-1]["__kind"] == "assistant_meta"
    assert messages[-1].sources[-1]["claim_snapshot"]["result"]["payable_amount"] == "143400"
```

- [x] **Step 2: Run targeted test and fix only exposed defects**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py::test_chat_stream_runs_recalculation_when_category_and_target_are_clear -q
```

Expected: pass. If it fails, adjust only `src/api/routes/chat.py` or `src/claim_calculation/thread_recalculation.py` to satisfy this explicit flow.

- [x] **Step 3: Run all claim-thread related tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
```

Expected: all selected tests pass.

## Task 4: Report and Self-Inspection

**Files:**
- Create: `docs/256_CLAIM_THREAD_CONDITIONAL_RECALCULATION_REPORT.md`

- [x] **Step 1: Write implementation report**

Create `docs/256_CLAIM_THREAD_CONDITIONAL_RECALCULATION_REPORT.md`:

```markdown
# 256. 보험금 계산 스레드 조건부 재계산 구현 보고서

## 목적

보험금 계산 결과가 저장된 하나의 채팅 스레드 안에서, 실무자가 추가 확인 결과를 일반 질의로 말했을 때 명확한 경우에는 기존 계산 항목을 바탕으로 재계산하고, 불명확한 경우에는 안전하게 되묻는다.

## 구현 범위

- `보상하지 않는다면`, `비급여로 보상한다면`, `3대비급여로 보상한다면`, `급여 본인부담으로 확인됐다면`처럼 좁은 문장 패턴만 처리한다.
- `보상한다면`처럼 보상 분류가 없는 요청은 급여 본인부담/비급여/3대비급여 중 하나를 명시하라고 되묻는다.
- 항목명이 여러 계산 항목과 매칭되거나, 스레드 안에 계산 스냅샷이 여러 건인데 기준 계산이 명확하지 않으면 되묻는다.
- 명확한 카테고리 변경은 기존 `run_claim_calculation`을 재사용한다. 코드가 직접 보험금 산식이나 보상률을 새로 계산하지 않는다.

## 안전장치

- 스냅샷에 저장된 허용 목록 필드만 재사용한다.
- 자유기재 원문, 원문 근거 본문, OCR 원문은 재계산 요청 생성에 사용하지 않는다.
- 모호한 요청은 RAG 검색이나 LLM 답변 생성으로 넘기지 않고 정형 안내로 종료한다.
- `보상하지 않는다면`은 기존 항목별 지급액 차감만 설명하며, 항목 지급액이 0원이면 기존 예상 지급액이 변하지 않는다고 안내한다.

## 검증

```bash
.venv/bin/python -m pytest tests/test_claim_thread_recalculation.py -q
.venv/bin/python -m pytest tests/test_api_chat_stream.py -q
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
```

## 남은 위험

- 현재 자연어 탐지는 좁은 패턴 기반이다. 실무 문장이 다양해지면 지원 문장 패턴을 추가하되, 불명확한 경우 되묻는 원칙을 유지해야 한다.
- 여러 계산 스냅샷 중 특정 번호를 선택하는 UX는 아직 텍스트 기반이다. 현재는 `최근 계산`, `마지막 계산`, `직전 계산`만 명시 선택으로 지원한다.
- 이번 패치는 기존 문서 근거 기반 계산 파이프라인을 재사용한다. 새로운 보험 지식이나 비율은 코드에 추가하지 않았다.
```

- [x] **Step 2: Run final focused validation**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
```

Expected: all selected tests pass.

- [x] **Step 3: Self-inspection**

Confirm these items before final report:

- The patch only touches claim-thread follow-up recalculation, tests, and the report.
- No raw OCR text, raw evidence text, or user free-text fields are newly persisted.
- No new hardcoded insurance payout rate, deductible, limit, or coverage judgment is added.
- Ambiguous requests are answered with clarification text and do not call the RAG pipeline.
- Existing claim calculation API behavior is preserved.
- No commit or push is performed unless the user separately requests it.

---

## Plan Self-Review

- Spec coverage: The plan includes explicit handling for missing category, ambiguous item name, multiple calculation snapshots, successful category-change recalculation, and deterministic non-coverage subtraction.
- Placeholder scan: No deferred implementation placeholders are present. The only intentionally unsupported behavior is described as a risk, not a plan step.
- Type consistency: Helper names used in tests are defined in Task 1, and chat route uses existing `ClaimCalculationRequest`, `ClaimItemRequest`, `ClaimCalculationResponse`, `ClaimItemInput`, and `ClaimCaseContext` types.
