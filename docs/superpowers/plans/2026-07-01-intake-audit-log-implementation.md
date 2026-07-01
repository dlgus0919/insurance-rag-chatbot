# Intake Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 문서 intake job에 append-only 감사 로그를 붙이고, 관리자 페이지에서 현재 단계, 차단/실패 이유, 다음 조치를 확인하게 만든다.

**Architecture:** 기존 `job.json`은 현재 상태 저장소로 유지하고, 같은 job 디렉터리에 `audit_log.jsonl`만 추가한다. 상태 변경은 `IntakeJobStore.update_job()`에서 자동 기록하고, 실패/차단 경로만 `block_reason`, `next_action`, `details`를 더 채운다. 관리자 API/UI는 선택한 job의 로그를 읽어 보여준다.

**Tech Stack:** FastAPI, Pydantic, JSONL runtime artifacts, vanilla JS admin SPA, pytest, Node built-in test runner.

---

## Scope Check

이 계획은 하나의 작고 독립적인 확장이다.

- 추가 DB, queue, 전역 검색 인덱스는 만들지 않는다.
- 정상 흐름은 상태 전환만 기록한다.
- 실패/차단 경로만 세부 정보를 기록한다.
- 관리자 UI는 선택한 job 하나의 로그만 표시한다.

## File Structure

- Modify: `src/ingest/intake_store.py`
  - `audit_log.jsonl` append/read helper.
  - `update_job()` 상태 전환 자동 로그.
- Modify: `src/ingest/intake_runner.py`
  - 차단/실패 경로에 `block_reason`, `next_action`, 진단 details 전달.
- Modify: `src/api/schemas/knowledge.py`
  - 감사 이벤트/list 응답 schema.
- Modify: `src/api/routes/knowledge.py`
  - `GET /admin/knowledge/intake/jobs/{job_id}/audit`.
- Modify: `frontend/js/config.js`
  - 감사 로그 endpoint base 상수.
- Modify: `frontend/js/modules/admin.js`
  - `fetchKnowledgeIntakeAudit(jobId)`.
- Modify: `frontend/html/admin.html`
  - job audit detail 영역.
- Modify: `frontend/js/pages/admin.js`
  - job row `상세` 버튼과 audit detail 렌더링.
- Modify: `frontend/css/admin.css`
  - audit detail 최소 스타일.
- Test: `tests/test_intake_store.py`
- Test: `tests/test_intake_runner.py`
- Test: `tests/test_api_admin_knowledge.py`
- Test: `tests/test_admin_knowledge_frontend.mjs`
- Create: `docs/258_INTAKE_AUDIT_LOG_IMPLEMENTATION_REPORT.md`

---

### Task 1: Intake Store Audit Log

**Files:**
- Modify: `tests/test_intake_store.py`
- Modify: `src/ingest/intake_store.py`

- [ ] **Step 1: Add store tests**

Append to `tests/test_intake_store.py`:

```python
def test_create_job_appends_initial_audit_event(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)

    job = store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")

    events = store.load_audit_events(job.job_id)
    assert len(events) == 1
    assert events[0]["actor"] == "admin"
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "uploaded"
    assert events[0]["event_type"] == "status_changed"


def test_update_job_appends_blocked_audit_event(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")

    store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        block_reason="scanned_pdf_text_layer_missing",
        next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
        details={"text_page_count": 0},
    )

    events = store.load_audit_events(job.job_id)
    assert [event["to_status"] for event in events] == ["uploaded", "blocked_scanned_pdf"]
    assert events[-1]["event_type"] == "blocked"
    assert events[-1]["block_reason"] == "scanned_pdf_text_layer_missing"
    assert "디지털 PDF" in events[-1]["next_action"]
    assert events[-1]["details"]["text_page_count"] == 0
```

- [ ] **Step 2: Run store tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_store.py -q
```

Expected: FAIL because `load_audit_events()` and audit write support do not exist.

- [ ] **Step 3: Implement minimal audit append/read**

Modify `src/ingest/intake_store.py`:

```python
def _event_type(status: IntakeJobStatus) -> str:
    if status in {IntakeJobStatus.BLOCKED_SCANNED_PDF, IntakeJobStatus.BLOCKED_UNSUPPORTED}:
        return "blocked"
    if status == IntakeJobStatus.FAILED:
        return "failed"
    if status in {IntakeJobStatus.APPLYING_APPROVED, IntakeJobStatus.REBUILDING_ACTIVE, IntakeJobStatus.COMPLETED}:
        return "applied"
    return "status_changed"
```

Add methods to `IntakeJobStore`:

```python
    def append_audit_event(
        self,
        job_id: str,
        *,
        actor: str,
        from_status: IntakeJobStatus | None,
        to_status: IntakeJobStatus,
        message: str,
        event_type: str | None = None,
        block_reason: str | None = None,
        next_action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": uuid.uuid4().hex,
            "job_id": job_id,
            "timestamp": utc_now_iso(),
            "actor": actor,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value,
            "event_type": event_type or _event_type(to_status),
            "message": message,
            "block_reason": block_reason,
            "next_action": next_action,
            "details": details or {},
        }
        path = self._audit_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def load_audit_events(self, job_id: str) -> list[dict[str, Any]]:
        path = self._audit_path(job_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _audit_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "audit_log.jsonl"
```

In `create_job()`, after `_write(job)`:

```python
        self.append_audit_event(
            job.job_id,
            actor=uploaded_by,
            from_status=None,
            to_status=job.status,
            message=job.message,
        )
```

Update `update_job()` signature:

```python
        actor: str = "system",
        block_reason: str | None = None,
        next_action: str | None = None,
```

Inside `update_job()`, keep `previous_status = job.status` before mutation, and after `_write(job)` append:

```python
        self.append_audit_event(
            job.job_id,
            actor=actor,
            from_status=previous_status,
            to_status=job.status,
            message=message,
            block_reason=block_reason,
            next_action=next_action,
            details=details,
        )
```

- [ ] **Step 4: Run store tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

```bash
git add src/ingest/intake_store.py tests/test_intake_store.py
git commit -m "feat(admin): add intake audit log store"
```

---

### Task 2: Runner Failure and Block Details

**Files:**
- Modify: `tests/test_intake_runner.py`
- Modify: `src/ingest/document_intake.py`
- Modify: `src/ingest/intake_runner.py`

- [ ] **Step 1: Add runner audit assertions**

Update `tests/test_intake_runner.py::test_runner_blocks_ocr_unsupported_image`:

```python
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "ocr_file_unsupported"
    assert "디지털 PDF" in events[-1]["next_action"]
```

Update `test_runner_blocks_scanned_pdf_before_candidates`:

```python
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "scanned_pdf_text_layer_missing"
    assert "텍스트 레이어" in events[-1]["next_action"]
```

Add:

```python
def test_runner_logs_candidate_extraction_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="digital.pdf", uploaded_by="admin", document_kind="pdf")
    source = store.job_dir(job.job_id) / "source" / "digital.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": True,
                "block_reason": None,
                "user_message": "디지털 PDF입니다.",
                "as_dict": lambda self: {"has_text_layer": True},
            },
        )(),
    )
    monkeypatch.setattr("src.ingest.intake_runner.parse_pdf", lambda _path: [(1, "본문")])
    monkeypatch.setattr("src.ingest.intake_runner._write_candidate_outputs", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.FAILED
    events = store.load_audit_events(job.job_id)
    assert events[-1]["block_reason"] == "candidate_extraction_failed"
    assert events[-1]["details"]["error_type"] == "RuntimeError"
```

- [ ] **Step 2: Run runner tests and verify failure**

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py -q
```

Expected: FAIL because runner does not pass audit fields and candidate extraction exceptions are not converted to failed jobs.

- [ ] **Step 3: Add one block reason**

Add to `IntakeBlockReason` in `src/ingest/document_intake.py`:

```python
    CANDIDATE_EXTRACTION_FAILED = "candidate_extraction_failed"
```

- [ ] **Step 4: Pass block/failure details from runner**

Import:

```python
from src.ingest.document_intake import IntakeBlockReason, evaluate_pdf_text_layer
```

Update OCR unsupported branch:

```python
        return store.update_job(
            job_id,
            status=IntakeJobStatus.BLOCKED_UNSUPPORTED,
            message="이미지 또는 스캔 문서는 OCR 자동화 대상이 아니므로 후보 추출을 진행하지 않습니다.",
            block_reason=IntakeBlockReason.OCR_FILE_UNSUPPORTED.value,
            next_action="텍스트 레이어가 포함된 디지털 PDF 또는 구조화 가능한 Excel 파일을 업로드하세요.",
        )
```

Update scanned PDF branch:

```python
            block_reason=report.block_reason.value if report.block_reason else None,
            next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
```

Wrap candidate output generation:

```python
    try:
        candidate_details = _write_candidate_outputs(store.job_dir(job.job_id), chunks_path, job.job_id)
    except Exception as exc:
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="검토 후보 생성 중 오류가 발생했습니다.",
            block_reason=IntakeBlockReason.CANDIDATE_EXTRACTION_FAILED.value,
            next_action="문서 staging 결과와 후보 추출 로그를 확인한 뒤 다시 실행하세요.",
            details={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
```

- [ ] **Step 5: Run runner tests**

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```bash
git add src/ingest/document_intake.py src/ingest/intake_runner.py tests/test_intake_runner.py
git commit -m "feat(admin): log intake block reasons"
```

---

### Task 3: Admin Audit API

**Files:**
- Modify: `src/api/schemas/knowledge.py`
- Modify: `src/api/routes/knowledge.py`
- Modify: `tests/test_api_admin_knowledge.py`

- [ ] **Step 1: Add API test**

Append to `tests/test_api_admin_knowledge.py`:

```python
@pytest.mark.anyio
async def test_list_intake_job_audit_returns_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        block_reason="scanned_pdf_text_layer_missing",
        next_action="텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.",
    )
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)

    payload = await knowledge.list_intake_job_audit(job.job_id, _admin_user())

    assert payload["total"] == 2
    assert payload["items"][-1]["block_reason"] == "scanned_pdf_text_layer_missing"
```

- [ ] **Step 2: Run API test and verify failure**

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py::test_list_intake_job_audit_returns_events -q
```

Expected: FAIL because route function does not exist.

- [ ] **Step 3: Add response schemas**

Add to `src/api/schemas/knowledge.py`:

```python
class IntakeAuditEventResponse(BaseModel):
    event_id: str
    job_id: str
    timestamp: str
    actor: str
    from_status: str | None = None
    to_status: str
    event_type: str
    message: str
    block_reason: str | None = None
    next_action: str | None = None
    details: dict = Field(default_factory=dict)


class IntakeAuditListResponse(BaseModel):
    total: int
    items: list[IntakeAuditEventResponse]
```

- [ ] **Step 4: Add route**

Import schema in `src/api/routes/knowledge.py`:

```python
    IntakeAuditListResponse,
```

Add route:

```python
@router.get("/intake/jobs/{job_id}/audit", response_model=IntakeAuditListResponse)
async def list_intake_job_audit(
    job_id: str,
    _: User = Depends(require_permission("admin.knowledge.read")),
) -> dict:
    events = get_intake_store().load_audit_events(job_id)
    return {"total": len(events), "items": events}
```

- [ ] **Step 5: Run API tests**

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```bash
git add src/api/schemas/knowledge.py src/api/routes/knowledge.py tests/test_api_admin_knowledge.py
git commit -m "feat(admin): expose intake audit log api"
```

---

### Task 4: Admin UI Audit Detail

**Files:**
- Modify: `frontend/js/config.js`
- Modify: `frontend/js/modules/admin.js`
- Modify: `frontend/html/admin.html`
- Modify: `frontend/js/pages/admin.js`
- Modify: `frontend/css/admin.css`
- Modify: `tests/test_admin_knowledge_frontend.mjs`

- [ ] **Step 1: Add frontend tests**

Append to `tests/test_admin_knowledge_frontend.mjs`:

```javascript
test('admin page exposes intake audit panel', async () => {
  const html = await readFile('frontend/html/admin.html', 'utf8');

  assert.match(html, /id="knowledge-audit-detail"/);
  assert.match(html, /data-admin-action="load-knowledge-audit"/);
});

test('admin module exports intake audit helper', async () => {
  const module = await import('../frontend/js/modules/admin.js');

  assert.equal(typeof module.fetchKnowledgeIntakeAudit, 'function');
});
```

- [ ] **Step 2: Run frontend test and verify failure**

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: FAIL because panel/helper do not exist.

- [ ] **Step 3: Add endpoint helper**

In `frontend/js/config.js`, add:

```javascript
    ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE: '/admin/knowledge/intake/jobs',
```

In `frontend/js/modules/admin.js`, add:

```javascript
export function fetchKnowledgeIntakeAudit(jobId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE}/${encodeURIComponent(jobId)}/audit`);
}
```

- [ ] **Step 4: Add HTML panel and detail button**

In `frontend/html/admin.html`, inside the knowledge section near the job table, add:

```html
<section class="admin-card knowledge-audit-card">
  <div class="admin-section-header">
    <h3>문서 처리 감사 로그</h3>
  </div>
  <div id="knowledge-audit-detail" class="knowledge-audit-detail">
    문서 처리 작업의 상세 버튼을 누르면 현재 단계와 다음 조치가 표시됩니다.
  </div>
</section>
```

In `renderKnowledgeJobRow(job)`, add a detail button beside `처리`:

```javascript
        <button class="act-btn" type="button" data-admin-action="load-knowledge-audit" data-job-id="${escapeHTML(job.job_id || '')}">상세</button>
```

- [ ] **Step 5: Render audit detail**

Import `fetchKnowledgeIntakeAudit` in `frontend/js/pages/admin.js`.

Add helper functions:

```javascript
function formatBlockReason(reason) {
  const labels = {
    scanned_pdf_text_layer_missing: 'PDF에 텍스트 레이어가 없거나 부족합니다.',
    ocr_file_unsupported: '이미지 또는 스캔 문서는 현재 자동 OCR 대상이 아닙니다.',
    unsupported_file_type: '지원하지 않는 파일 형식입니다.',
    candidate_extraction_failed: '검토 후보 생성 중 오류가 발생했습니다.',
  };
  return labels[reason] || reason || '-';
}

function renderAuditDetail(events) {
  if (!events.length) return '<p class="knowledge-help">기록된 감사 로그가 없습니다.</p>';
  const latest = events[events.length - 1];
  const blocked = [...events].reverse().find((event) => event.block_reason || event.event_type === 'failed');
  return `
    <div class="audit-summary">
      <p><strong>현재 단계:</strong> ${escapeHTML(formatKnowledgeStatus(latest.to_status))}</p>
      <p><strong>막힌 이유:</strong> ${escapeHTML(formatBlockReason(blocked?.block_reason))}</p>
      <p><strong>다음 조치:</strong> ${escapeHTML(blocked?.next_action || '추가 조치가 필요하지 않습니다.')}</p>
    </div>
    <ul class="audit-events">
      ${events.map((event) => `<li>${escapeHTML(event.message || formatKnowledgeStatus(event.to_status))}</li>`).join('')}
    </ul>
  `;
}

async function loadKnowledgeAudit(jobId) {
  if (!jobId) return;
  const container = document.getElementById('knowledge-audit-detail');
  if (!container) return;
  container.textContent = '감사 로그를 불러오는 중입니다...';
  try {
    const data = normalizeListResponse(await fetchKnowledgeIntakeAudit(jobId));
    container.innerHTML = renderAuditDetail(data.items);
  } catch (error) {
    container.textContent = error.message || '감사 로그를 불러오지 못했습니다.';
  }
}
```

Add action handler:

```javascript
    } else if (action === 'load-knowledge-audit') {
      await loadKnowledgeAudit(actionTarget.dataset.jobId);
```

- [ ] **Step 6: Add minimal CSS**

In `frontend/css/admin.css`:

```css
.knowledge-audit-detail {
  display: grid;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.audit-summary {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  background: var(--surface-muted);
}

.audit-summary p {
  margin: 4px 0;
}

.audit-events {
  margin: 0;
  padding-left: 18px;
}
```

- [ ] **Step 7: Run frontend tests and build**

```bash
node --test tests/test_admin_knowledge_frontend.mjs
cd frontend && npm run build
```

Expected: PASS and `frontend/dist/app.min.js` changes.

- [ ] **Step 8: Commit task**

```bash
git add frontend/js/config.js frontend/js/modules/admin.js frontend/html/admin.html frontend/js/pages/admin.js frontend/css/admin.css frontend/dist/app.min.js tests/test_admin_knowledge_frontend.mjs
git commit -m "feat(admin): show intake audit log"
```

---

### Task 5: Report and Focused Validation

**Files:**
- Create: `docs/258_INTAKE_AUDIT_LOG_IMPLEMENTATION_REPORT.md`

- [ ] **Step 1: Run focused validation**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_intake_store.py \
  tests/test_intake_runner.py \
  tests/test_api_admin_knowledge.py \
  tests/test_admin_knowledge_frontend.mjs \
  tests/test_document_intake_detector.py \
  tests/test_file_intake_planner.py -q
```

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
bash -n ops/bin/insurance-rag-desktop-launcher
cd frontend && npm run build
git diff --check
```

Expected: pytest, Node test, launcher syntax check, frontend build, diff check all pass.

- [ ] **Step 2: Write report**

Create `docs/258_INTAKE_AUDIT_LOG_IMPLEMENTATION_REPORT.md`:

```markdown
# 258. Intake Audit Log Implementation Report

## Summary

관리자 문서 intake job에 job별 `audit_log.jsonl`을 추가하고, 관리자 페이지에서 현재 단계, 차단/실패 이유, 다음 조치를 확인할 수 있게 했다.

## Changed Files

- `src/ingest/intake_store.py`: audit event append/read.
- `src/ingest/intake_runner.py`: 차단/실패 경로의 block reason, next action, details 기록.
- `src/api/routes/knowledge.py`: job별 audit 조회 API.
- `src/api/schemas/knowledge.py`: audit response schema.
- `frontend/*`: 관리자 지식 확장 탭의 audit detail 표시.
- `tests/*`: store, runner, API, frontend 회귀 테스트.

## Guardrail Check

- 보험 지급 판단, 공제율, 한도 값을 추가하지 않았다.
- 로그는 운영 감사와 안내만 담당하며 active 지식 자산을 직접 수정하지 않는다.
- 스캔 PDF/OCR 자동화는 추가하지 않았다.

## Validation

- `.venv/bin/python -m pytest tests/test_intake_store.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_admin_knowledge_frontend.mjs tests/test_document_intake_detector.py tests/test_file_intake_planner.py -q`: 통과.
- `node --test tests/test_admin_knowledge_frontend.mjs`: 통과.
- `bash -n ops/bin/insurance-rag-desktop-launcher`: 통과.
- `cd frontend && npm run build`: 통과.
- `git diff --check`: 통과.

## Remaining Risks

- 전체 로그 검색/기간 필터는 아직 없다.
- Excel staging 연결 전에는 Excel intake 실패 로그만 남는다.
```

If any command fails, replace `통과` with the failing output summary before committing the report.

- [ ] **Step 3: Commit report**

```bash
git add docs/258_INTAKE_AUDIT_LOG_IMPLEMENTATION_REPORT.md
git commit -m "docs(admin): report intake audit log implementation"
```

---

## Self-Review Checklist

- Spec coverage:
  - JSONL audit storage: Task 1.
  - Normal status changes: Task 1.
  - Failure/block details: Task 2.
  - Admin API: Task 3.
  - Admin UI: Task 4.
  - Validation/report: Task 5.
- No new DB, queue, or global audit index.
- No OCR automation.
- No insurance payout/rule hardcoding.
- Existing `IntakeJobStatus` and `IntakeBlockReason` hooks remain, but only used where current flow needs them.
