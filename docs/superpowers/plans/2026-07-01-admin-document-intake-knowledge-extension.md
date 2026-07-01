# Admin Document Intake Knowledge Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 페이지에서 문서를 추가하면 디지털 문서만 자동으로 staging 및 후보 생성까지 진행하고, 관리자가 후보를 검토/승인한 뒤 active ontology/rule/index/GraphDB에 반영하는 2단계 지식 확장 흐름을 만든다.

**Architecture:** 신규 문서 처리는 `src/ingest`의 job/store/runner 계층으로 격리하고, 관리자 API는 그 계층을 호출한다. 후보 검토는 기존 ontology/rule review 저장소와 검증 로직을 재사용하되, Zenity 실행기 UI에서 관리자 웹 UI로 이동한다. 스캔 PDF/OCR은 자동 수행하지 않고 텍스트 레이어 판독 gate에서 차단한다.

**Tech Stack:** FastAPI, Pydantic, SQLite/JSON runtime artifacts, existing parser/chunker/index builders, existing ontology/rule review stores, vanilla JS admin SPA, pytest, frontend Node tests.

---

## Scope Check

이 계획은 하나의 기능군이지만 네 계층을 순차적으로 건드린다.

- 문서 intake job과 스캔 PDF 차단
- 관리자 API와 관리자 UI
- 온톨로지/rule 후보 생성 및 검토 UI
- 승인 후 active manifest/index/GraphDB 반영

각 태스크는 독립 테스트와 커밋 단위를 가진다. 구현자는 태스크 순서대로 진행하고, 각 태스크 종료 시 지정된 테스트를 통과시킨 뒤 커밋한다. DGX에서 실행 중인 LLM 서버 교체는 이 계획의 범위가 아니다.

## File Structure

### New Backend Files

- `src/ingest/document_intake.py`
  - 파일 유형 판정, PDF 텍스트 레이어 검사, 스캔 PDF 차단 사유 생성.
- `src/ingest/intake_store.py`
  - `data/intake/jobs/<job_id>/job.json` 기반 job 저장/조회/상태 갱신.
- `src/ingest/intake_runner.py`
  - job을 실행해 source 파일 staging, chunks 생성, 후보 추출까지 진행.
- `src/api/schemas/knowledge.py`
  - 관리자 지식 확장 API 응답/요청 schema.
- `src/api/routes/knowledge.py`
  - `/admin/knowledge/*` 관리자 전용 API.
- `src/ingest/knowledge_apply.py`
  - 승인 후보 apply, active index/GraphDB rebuild orchestration.

### Modified Backend Files

- `src/api/main.py`
  - `knowledge.py` router 등록.
- `src/ingest/file_intake_planner.py`
  - 스캔 PDF/이미지 OCR 자동 실행 단계 제거, 차단 단계 명시.
- `scripts/extract_claim_rule_candidates.py`
  - staging chunk JSONL과 job metadata를 입력으로 받을 수 있게 유지/확장.
- `scripts/extract_ontology_candidates.py`
  - 이미 `--source` 반복 입력을 지원하므로 runner에서 호출한다.
- `scripts/build_graph_index.py`
  - 기존 `--rule-links` 흐름을 그대로 사용한다.

### Modified Frontend Files

- `frontend/html/admin.html`
  - `지식 확장` 관리자 메뉴와 문서 추가/후보 검토/반영 이력 sections 추가.
- `frontend/js/config.js`
  - `/admin/knowledge/*` endpoint 상수 추가.
- `frontend/js/modules/admin.js`
  - knowledge API wrapper 추가.
- `frontend/js/pages/admin.js`
  - 지식 확장 탭 렌더링, 업로드, 상태 조회, 후보 decision 처리.
- `frontend/css/admin.css`
  - 지식 확장 화면, 상태 badge, 후보 detail panel 스타일.
- `frontend/dist/app.min.js`
  - `npm run build`로 재생성한다.

### New Tests

- `tests/test_document_intake_detector.py`
- `tests/test_intake_store.py`
- `tests/test_api_admin_knowledge.py`
- `tests/test_intake_runner.py`
- `tests/test_admin_knowledge_frontend.mjs`
- `tests/test_knowledge_apply.py`

---

### Task 1: Document Type Gate and OCR Block Policy

**Files:**
- Create: `src/ingest/document_intake.py`
- Modify: `src/ingest/file_intake_planner.py`
- Test: `tests/test_document_intake_detector.py`
- Test: `tests/test_file_intake_planner.py`

- [ ] **Step 1: Write failing tests for PDF text-layer classification**

Add `tests/test_document_intake_detector.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.document_intake import (
    DocumentKind,
    IntakeBlockReason,
    classify_source_file,
    evaluate_pdf_text_layer,
)


def test_classify_source_file_accepts_digital_pdf_suffix() -> None:
    assert classify_source_file(Path("신규_약관.pdf")) == DocumentKind.PDF


def test_classify_source_file_accepts_excel_suffix() -> None:
    assert classify_source_file(Path("신규_요율.xlsx")) == DocumentKind.EXCEL


def test_classify_source_file_blocks_image_ocr() -> None:
    assert classify_source_file(Path("스캔본.jpg")) == DocumentKind.OCR_UNSUPPORTED


def test_pdf_text_layer_passes_when_pages_have_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.ingest.document_intake.parse_pdf",
        lambda _path: [(1, "약관 본문 " * 80), (2, "공제율 및 보상 비율 " * 60)],
    )

    report = evaluate_pdf_text_layer(Path("digital.pdf"))

    assert report.has_text_layer is True
    assert report.block_reason is None
    assert report.text_page_count == 2


def test_pdf_text_layer_blocks_scanned_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.ingest.document_intake.parse_pdf",
        lambda _path: [(1, ""), (2, "  "), (3, "")],
    )

    report = evaluate_pdf_text_layer(Path("scan.pdf"))

    assert report.has_text_layer is False
    assert report.block_reason == IntakeBlockReason.SCANNED_PDF_TEXT_LAYER_MISSING
    assert "텍스트 레이어" in report.user_message
```

- [ ] **Step 2: Update existing planner tests for OCR block policy**

Modify `tests/test_file_intake_planner.py` image test:

```python
def test_image_intake_plan_blocks_ocr_auto_run():
    plan = plan_file_intake("영수증.jpg")

    assert plan.file_type == "ocr_unsupported"
    assert "block_ocr_required" in plan.steps
    assert "run_scanned_document_ocr" not in plan.steps
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False
```

Modify PDF test to assert the scan gate:

```python
def test_pdf_intake_plan_detects_text_layer_before_pipeline_choice():
    plan = plan_file_intake("신규_약관.pdf")

    assert plan.file_type == "pdf"
    assert plan.steps[:3] == [
        "detect_pdf_text_layer",
        "block_if_scanned_pdf",
        "choose_digital_pdf_pipeline",
    ]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is True
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_document_intake_detector.py tests/test_file_intake_planner.py -q
```

Expected: FAIL because `src.ingest.document_intake` does not exist and planner still uses `run_scanned_document_ocr`.

- [ ] **Step 4: Implement detector and planner changes**

Create `src/ingest/document_intake.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from src.parser.pdf_parser import parse_pdf


class DocumentKind(StrEnum):
    PDF = "pdf"
    EXCEL = "excel"
    OCR_UNSUPPORTED = "ocr_unsupported"
    UNSUPPORTED = "unsupported"


class IntakeBlockReason(StrEnum):
    SCANNED_PDF_TEXT_LAYER_MISSING = "scanned_pdf_text_layer_missing"
    OCR_FILE_UNSUPPORTED = "ocr_file_unsupported"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"


EXCEL_SUFFIXES = {".xlsx", ".xls", ".csv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}

MIN_TEXT_CHARS_TOTAL = 200
MIN_TEXT_PAGE_RATIO = 0.5


@dataclass(frozen=True)
class PdfTextLayerReport:
    path: str
    page_count: int
    text_page_count: int
    total_text_chars: int
    text_page_ratio: float
    has_text_layer: bool
    block_reason: IntakeBlockReason | None
    user_message: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["block_reason"] = self.block_reason.value if self.block_reason else None
        return data


def classify_source_file(path: str | Path) -> DocumentKind:
    suffix = Path(path).suffix.lower()
    if suffix in PDF_SUFFIXES:
        return DocumentKind.PDF
    if suffix in EXCEL_SUFFIXES:
        return DocumentKind.EXCEL
    if suffix in IMAGE_SUFFIXES:
        return DocumentKind.OCR_UNSUPPORTED
    return DocumentKind.UNSUPPORTED


def evaluate_pdf_text_layer(path: str | Path) -> PdfTextLayerReport:
    source_path = Path(path)
    pages = parse_pdf(source_path)
    page_count = len(pages)
    text_lengths = [len(str(text or "").strip()) for _, text in pages]
    text_page_count = sum(1 for length in text_lengths if length > 0)
    total_text_chars = sum(text_lengths)
    text_page_ratio = (text_page_count / page_count) if page_count else 0.0
    has_text_layer = total_text_chars >= MIN_TEXT_CHARS_TOTAL and text_page_ratio >= MIN_TEXT_PAGE_RATIO
    block_reason = None if has_text_layer else IntakeBlockReason.SCANNED_PDF_TEXT_LAYER_MISSING
    user_message = (
        "디지털 PDF로 판정되었습니다. 텍스트 레이어 기반 후보 추출을 진행할 수 있습니다."
        if has_text_layer
        else "이 PDF는 텍스트 레이어가 없거나 부족한 스캔본으로 보입니다. "
        "현재 시스템은 스캔 PDF OCR 자동화를 수행하지 않으므로 후보 추출과 DB 반영을 진행하지 않습니다. "
        "텍스트 레이어가 포함된 디지털 PDF 또는 Excel 파일을 추가해 주세요."
    )
    return PdfTextLayerReport(
        path=str(source_path),
        page_count=page_count,
        text_page_count=text_page_count,
        total_text_chars=total_text_chars,
        text_page_ratio=round(text_page_ratio, 4),
        has_text_layer=has_text_layer,
        block_reason=block_reason,
        user_message=user_message,
    )
```

Modify `src/ingest/file_intake_planner.py` so image files are blocked:

```python
from src.ingest.document_intake import EXCEL_SUFFIXES, IMAGE_SUFFIXES, PDF_SUFFIXES
```

Replace PDF steps with:

```python
[
    "detect_pdf_text_layer",
    "block_if_scanned_pdf",
    "choose_digital_pdf_pipeline",
    "stage_source_documents",
    "ontology_candidates_pending",
    "claim_rule_candidates_pending",
    "wait_for_practitioner_approval",
]
```

Replace image branch with:

```python
if suffix in IMAGE_SUFFIXES:
    return IntakePlan(
        path=str(source_path),
        file_type="ocr_unsupported",
        steps=["block_ocr_required"],
        mutates_indexes=False,
        requires_practitioner_approval=False,
    )
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_document_intake_detector.py tests/test_file_intake_planner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ingest/document_intake.py src/ingest/file_intake_planner.py tests/test_document_intake_detector.py tests/test_file_intake_planner.py
git commit -m "feat(ingest): gate scanned documents before intake"
```

### Task 2: Runtime Intake Job Store

**Files:**
- Create: `src/ingest/intake_store.py`
- Test: `tests/test_intake_store.py`

- [ ] **Step 1: Write failing job store tests**

Create `tests/test_intake_store.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def test_create_job_writes_runtime_job_json(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)

    job = store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")

    assert job.job_id.startswith("intake_")
    assert job.status == IntakeJobStatus.UPLOADED
    assert (tmp_path / job.job_id / "job.json").exists()


def test_update_status_persists_block_reason(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")

    updated = store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
        message="텍스트 레이어가 없습니다.",
        details={"block_reason": "scanned_pdf_text_layer_missing"},
    )

    loaded = store.load_job(job.job_id)
    assert updated.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert loaded.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert loaded.message == "텍스트 레이어가 없습니다."
    assert loaded.details["block_reason"] == "scanned_pdf_text_layer_missing"


def test_list_jobs_returns_newest_first(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    first = store.create_job(original_filename="a.pdf", uploaded_by="admin", document_kind="pdf")
    second = store.create_job(original_filename="b.pdf", uploaded_by="admin", document_kind="pdf")

    jobs = store.list_jobs()

    assert [job.job_id for job in jobs] == [second.job_id, first.job_id]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_store.py -q
```

Expected: FAIL because `src.ingest.intake_store` does not exist.

- [ ] **Step 3: Implement the job store**

Create `src/ingest/intake_store.py`:

```python
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class IntakeJobStatus(StrEnum):
    UPLOADED = "uploaded"
    DETECTING_DOCUMENT_TYPE = "detecting_document_type"
    BLOCKED_SCANNED_PDF = "blocked_scanned_pdf"
    BLOCKED_UNSUPPORTED = "blocked_unsupported"
    STAGING_SOURCE = "staging_source"
    BUILDING_STAGING_CHUNKS = "building_staging_chunks"
    EXTRACTING_CANDIDATES = "extracting_candidates"
    WAITING_REVIEW = "waiting_review"
    APPLYING_APPROVED = "applying_approved"
    REBUILDING_ACTIVE = "rebuilding_active"
    COMPLETED = "completed"
    FAILED = "failed"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class IntakeJob:
    job_id: str
    original_filename: str
    uploaded_by: str
    document_kind: str
    status: IntakeJobStatus
    message: str
    created_at: str
    updated_at: str
    source_path: str | None = None
    staging_chunks_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeJob":
        payload = dict(data)
        payload["status"] = IntakeJobStatus(payload["status"])
        return cls(**payload)


class IntakeJobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def create_job(self, *, original_filename: str, uploaded_by: str, document_kind: str) -> IntakeJob:
        self.root.mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        job = IntakeJob(
            job_id=f"intake_{now.replace(':', '').replace('+', 'Z')}_{uuid.uuid4().hex[:8]}",
            original_filename=Path(original_filename).name,
            uploaded_by=uploaded_by,
            document_kind=document_kind,
            status=IntakeJobStatus.UPLOADED,
            message="문서가 업로드되었습니다.",
            created_at=now,
            updated_at=now,
        )
        self._write(job)
        return job

    def load_job(self, job_id: str) -> IntakeJob:
        path = self._job_path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"intake job not found: {job_id}")
        return IntakeJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_jobs(self) -> list[IntakeJob]:
        if not self.root.exists():
            return []
        jobs = []
        for path in self.root.glob("intake_*/job.json"):
            jobs.append(IntakeJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def update_job(
        self,
        job_id: str,
        *,
        status: IntakeJobStatus,
        message: str,
        details: dict[str, Any] | None = None,
        source_path: str | None = None,
        staging_chunks_path: str | None = None,
    ) -> IntakeJob:
        job = self.load_job(job_id)
        job.status = status
        job.message = message
        job.updated_at = utc_now_iso()
        if details:
            job.details.update(details)
        if source_path is not None:
            job.source_path = source_path
        if staging_chunks_path is not None:
            job.staging_chunks_path = staging_chunks_path
        self._write(job)
        return job

    def job_dir(self, job_id: str) -> Path:
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ValueError("invalid intake job id")
        return self.root / job_id

    def _job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def _write(self, job: IntakeJob) -> None:
        path = self._job_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/intake_store.py tests/test_intake_store.py
git commit -m "feat(ingest): add runtime intake job store"
```

### Task 3: Admin Knowledge API Skeleton

**Files:**
- Create: `src/api/schemas/knowledge.py`
- Create: `src/api/routes/knowledge.py`
- Modify: `src/api/main.py`
- Modify: `src/api/schemas/admin.py` only if import aggregation is used in this repo
- Test: `tests/test_api_admin_knowledge.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api_admin_knowledge.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import UploadFile

from src.api.routes import knowledge
from src.auth.users import User
from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def _admin_user() -> User:
    return User(
        username="admin",
        password_hash="x",
        role="admin",
        display_name="관리자",
        email=None,
        status="active",
        created_at="2026-07-01T00:00:00+09:00",
        updated_at=None,
        last_login=None,
    )


@pytest.mark.asyncio
async def test_list_intake_jobs_returns_runtime_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    store.create_job(original_filename="약관.pdf", uploaded_by="admin", document_kind="pdf")
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)

    payload = await knowledge.list_intake_jobs(_admin_user())

    assert payload["total"] == 1
    assert payload["items"][0]["original_filename"] == "약관.pdf"


@pytest.mark.asyncio
async def test_run_intake_job_blocks_scanned_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    source = tmp_path / job.job_id / "source" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(knowledge, "get_intake_store", lambda: store)
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": False,
                "block_reason": type("Reason", (), {"value": "scanned_pdf_text_layer_missing"})(),
                "user_message": "텍스트 레이어가 없습니다.",
                "as_dict": lambda self: {"has_text_layer": False, "block_reason": "scanned_pdf_text_layer_missing"},
            },
        )(),
    )

    payload = await knowledge.run_intake_job(job.job_id, _admin_user())

    assert payload["status"] == "blocked_scanned_pdf"
    assert "텍스트 레이어" in payload["message"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py -q
```

Expected: FAIL because `src.api.routes.knowledge` and schemas do not exist.

- [ ] **Step 3: Add schemas**

Create `src/api/schemas/knowledge.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class IntakeJobResponse(BaseModel):
    job_id: str
    original_filename: str
    uploaded_by: str
    document_kind: str
    status: str
    message: str
    created_at: str
    updated_at: str
    source_path: str | None = None
    staging_chunks_path: str | None = None
    details: dict = Field(default_factory=dict)


class IntakeJobListResponse(BaseModel):
    total: int
    items: list[IntakeJobResponse]
```

- [ ] **Step 4: Add routes**

Create `src/api/routes/knowledge.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status

from src import config
from src.api.deps import require_permission
from src.api.exceptions import ValidationException
from src.api.schemas.knowledge import IntakeJobListResponse, IntakeJobResponse
from src.auth.users import User
from src.ingest.document_intake import DocumentKind, classify_source_file
from src.ingest.intake_runner import run_intake_job_once
from src.ingest.intake_store import IntakeJobStore

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])

DEFAULT_INTAKE_ROOT = config.ROOT_DIR / "data" / "intake" / "jobs"


def get_intake_store() -> IntakeJobStore:
    return IntakeJobStore(DEFAULT_INTAKE_ROOT)


def _response(job) -> dict:
    return job.as_dict()


@router.get("/intake/jobs", response_model=IntakeJobListResponse)
async def list_intake_jobs(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    jobs = get_intake_store().list_jobs()
    return {"total": len(jobs), "items": [_response(job) for job in jobs]}


@router.post("/intake/jobs", response_model=IntakeJobResponse, status_code=status.HTTP_201_CREATED)
async def create_intake_job(
    file: UploadFile = File(...),
    current: User = Depends(require_permission("admin.stats")),
) -> dict:
    original_name = Path(file.filename or "").name
    if not original_name:
        raise ValidationException(detail="파일명이 비어 있습니다.")
    document_kind = classify_source_file(original_name)
    if document_kind == DocumentKind.UNSUPPORTED:
        raise ValidationException(detail="지원하지 않는 파일 형식입니다.")
    store = get_intake_store()
    job = store.create_job(
        original_filename=original_name,
        uploaded_by=current.username,
        document_kind=document_kind.value,
    )
    source_dir = store.job_dir(job.job_id) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / original_name
    with source_path.open("wb") as fp:
        shutil.copyfileobj(file.file, fp)
    job = store.update_job(job.job_id, status=job.status, message=job.message, source_path=str(source_path))
    return _response(job)


@router.post("/intake/jobs/{job_id}/run", response_model=IntakeJobResponse)
async def run_intake_job(
    job_id: str,
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    job = run_intake_job_once(get_intake_store(), job_id)
    return _response(job)
```

- [ ] **Step 5: Register router**

Modify `src/api/main.py` so it imports and includes the router:

```python
from src.api.routes import knowledge
```

Add with the other routers:

```python
app.include_router(knowledge.router)
```

- [ ] **Step 6: Run tests and verify pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/api/schemas/knowledge.py src/api/routes/knowledge.py src/api/main.py tests/test_api_admin_knowledge.py
git commit -m "feat(admin): add knowledge intake API"
```

### Task 4: Intake Runner for Digital Documents and Candidate Generation

**Files:**
- Create: `src/ingest/intake_runner.py`
- Modify: `scripts/extract_claim_rule_candidates.py`
- Test: `tests/test_intake_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_intake_runner.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.intake_runner import run_intake_job_once
from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus


def test_runner_blocks_ocr_unsupported_image(tmp_path: Path) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.jpg", uploaded_by="admin", document_kind="ocr_unsupported")

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.BLOCKED_UNSUPPORTED
    assert "OCR 자동화" in result.message


def test_runner_blocks_scanned_pdf_before_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntakeJobStore(tmp_path)
    job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
    source = store.job_dir(job.job_id) / "source" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))
    monkeypatch.setattr(
        "src.ingest.intake_runner.evaluate_pdf_text_layer",
        lambda _path: type(
            "Report",
            (),
            {
                "has_text_layer": False,
                "block_reason": type("Reason", (), {"value": "scanned_pdf_text_layer_missing"})(),
                "user_message": "텍스트 레이어가 없습니다.",
                "as_dict": lambda self: {"has_text_layer": False},
            },
        )(),
    )

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.BLOCKED_SCANNED_PDF
    assert not (store.job_dir(job.job_id) / "staging" / "chunks.jsonl").exists()


def test_runner_writes_staging_chunks_for_digital_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr("src.ingest.intake_runner.parse_pdf", lambda _path: [(1, "4세대 급여 통원 80% 보상")])

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.WAITING_REVIEW
    chunks_path = Path(result.staging_chunks_path)
    rows = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["text"] == "4세대 급여 통원 80% 보상"
    assert rows[0]["metadata"]["doc_short"].startswith("intake_")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py -q
```

Expected: FAIL because `src.ingest.intake_runner` does not exist.

- [ ] **Step 3: Implement runner**

Create `src/ingest/intake_runner.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.ingest.document_intake import evaluate_pdf_text_layer
from src.ingest.intake_store import IntakeJob, IntakeJobStatus, IntakeJobStore
from src.parser.pdf_parser import parse_pdf


def run_intake_job_once(store: IntakeJobStore, job_id: str) -> IntakeJob:
    job = store.load_job(job_id)
    if job.document_kind == "ocr_unsupported":
        return store.update_job(
            job_id,
            status=IntakeJobStatus.BLOCKED_UNSUPPORTED,
            message="이미지 또는 스캔 문서는 OCR 자동화 대상이 아니므로 후보 추출을 진행하지 않습니다.",
        )
    if job.document_kind == "pdf":
        return _run_pdf_job(store, job)
    if job.document_kind == "excel":
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.FAILED,
            message="Excel intake는 이 구현 계획의 P2에서 row staging으로 연결됩니다.",
        )
    return store.update_job(
        job.job_id,
        status=IntakeJobStatus.BLOCKED_UNSUPPORTED,
        message="지원하지 않는 문서 형식입니다.",
    )


def _run_pdf_job(store: IntakeJobStore, job: IntakeJob) -> IntakeJob:
    source_path = Path(job.source_path or "")
    if not source_path.exists():
        return store.update_job(job.job_id, status=IntakeJobStatus.FAILED, message="업로드 원본 파일을 찾을 수 없습니다.")

    store.update_job(job.job_id, status=IntakeJobStatus.DETECTING_DOCUMENT_TYPE, message="PDF 텍스트 레이어를 검사합니다.")
    report = evaluate_pdf_text_layer(source_path)
    if not report.has_text_layer:
        return store.update_job(
            job.job_id,
            status=IntakeJobStatus.BLOCKED_SCANNED_PDF,
            message=report.user_message,
            details={"pdf_text_layer": report.as_dict()},
        )

    store.update_job(job.job_id, status=IntakeJobStatus.BUILDING_STAGING_CHUNKS, message="디지털 PDF staging chunk를 생성합니다.")
    chunks_path = _write_pdf_staging_chunks(store.job_dir(job.job_id), source_path, job.job_id)
    return store.update_job(
        job.job_id,
        status=IntakeJobStatus.WAITING_REVIEW,
        message="문서 staging이 완료되었습니다. 후보 검토를 진행할 수 있습니다.",
        staging_chunks_path=str(chunks_path),
        details={"pdf_text_layer": report.as_dict()},
    )


def _write_pdf_staging_chunks(job_dir: Path, source_path: Path, job_id: str) -> Path:
    staging_dir = job_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = staging_dir / "chunks.jsonl"
    rows = []
    doc_short = f"{job_id}_{source_path.stem}"
    for page_no, text in parse_pdf(source_path):
        cleaned = str(text or "").strip()
        if not cleaned:
            continue
        rows.append(
            {
                "id": f"{doc_short}_p{page_no:03d}",
                "chunk_id": f"{doc_short}_p{page_no:03d}",
                "text": cleaned,
                "metadata": {
                    "doc_short": doc_short,
                    "source": doc_short,
                    "pdf_filename": source_path.name,
                    "page_start": page_no,
                    "page_end": page_no,
                    "intake_job_id": job_id,
                },
            }
        )
    chunks_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return chunks_path
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/intake_runner.py tests/test_intake_runner.py
git commit -m "feat(ingest): stage digital PDFs for knowledge review"
```

### Task 5: Candidate Extraction From Intake Staging

**Files:**
- Modify: `src/ingest/intake_runner.py`
- Modify: `scripts/extract_claim_rule_candidates.py`
- Test: `tests/test_intake_runner.py`
- Test: `tests/test_extract_claim_rule_candidates.py`

- [ ] **Step 1: Add failing test for candidate extraction paths**

Append to `tests/test_intake_runner.py`:

```python
def test_runner_records_candidate_outputs_for_digital_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr("src.ingest.intake_runner.parse_pdf", lambda _path: [(1, "4세대 급여 통원 80% 보상")])

    result = run_intake_job_once(store, job.job_id)

    assert result.details["ontology_candidates_path"].endswith("ontology_candidates.jsonl")
    assert result.details["rule_candidates_path"].endswith("rule_candidates.jsonl")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py::test_runner_records_candidate_outputs_for_digital_pdf -q
```

Expected: FAIL because the runner does not generate candidate output files.

- [ ] **Step 3: Add candidate output generation to runner**

Add to `src/ingest/intake_runner.py`:

```python
from scripts.extract_claim_rule_candidates import extract_candidates_from_text, iter_policy_chunks
from src.ontology.candidate_extractor import (
    extract_reinforcement_candidates,
    load_manifest_concepts,
    load_processed_chunks,
)
from src.ontology.policy import load_candidate_extraction_policy, load_review_policy
from src.ontology.registry import BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import utc_now_iso
from src.claim_calculation.rule_candidates import write_jsonl
```

Add helper functions:

```python
def _write_candidate_outputs(job_dir: Path, chunks_path: Path, job_id: str) -> dict[str, str]:
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    ontology_path = review_dir / "ontology_candidates.jsonl"
    rule_path = review_dir / "rule_candidates.jsonl"

    concept_policy = load_candidate_extraction_policy(None)
    review_policy = load_review_policy(None)
    concepts = load_manifest_concepts(str(BASE_ONTOLOGY_MANIFEST))
    chunks = load_processed_chunks([chunks_path], limit=2000)
    ontology_result = extract_reinforcement_candidates(
        concepts=concepts,
        chunks=chunks,
        extraction_run_id=f"intake-ontology-{job_id}-{utc_now_iso()}",
        candidate_limit=100,
        candidate_type=concept_policy.default_reinforcement_type,
        extraction_policy=concept_policy,
        review_policy=review_policy,
        previous_review_candidates=[],
    )
    ontology_path.write_text(
        "\n".join(json.dumps(candidate.to_dict(), ensure_ascii=False) for candidate in ontology_result.candidates)
        + ("\n" if ontology_result.candidates else ""),
        encoding="utf-8",
    )

    rule_candidates = []
    for chunk in iter_policy_chunks(chunks_path):
        rule_candidates.extend(extract_candidates_from_text(**chunk))
    write_jsonl(rule_path, rule_candidates)
    return {
        "ontology_candidates_path": str(ontology_path),
        "rule_candidates_path": str(rule_path),
        "ontology_candidate_count": str(len(ontology_result.candidates)),
        "rule_candidate_count": str(len(rule_candidates)),
    }
```

In `_run_pdf_job`, after writing chunks:

```python
candidate_details = _write_candidate_outputs(store.job_dir(job.job_id), chunks_path, job.job_id)
return store.update_job(
    job.job_id,
    status=IntakeJobStatus.WAITING_REVIEW,
    message="문서 staging과 후보 생성이 완료되었습니다. 후보 검토를 진행할 수 있습니다.",
    staging_chunks_path=str(chunks_path),
    details={"pdf_text_layer": report.as_dict(), **candidate_details},
)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py tests/test_extract_claim_rule_candidates.py tests/test_extract_ontology_candidates_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/intake_runner.py scripts/extract_claim_rule_candidates.py tests/test_intake_runner.py
git commit -m "feat(ingest): generate review candidates from intake staging"
```

### Task 6: Admin UI for Document Intake

**Files:**
- Modify: `frontend/html/admin.html`
- Modify: `frontend/js/config.js`
- Modify: `frontend/js/modules/admin.js`
- Modify: `frontend/js/pages/admin.js`
- Modify: `frontend/css/admin.css`
- Test: `tests/test_admin_knowledge_frontend.mjs`

- [ ] **Step 1: Write failing frontend test**

Create `tests/test_admin_knowledge_frontend.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('admin page exposes knowledge extension section', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-sub="knowledge"/);
  assert.match(html, /문서 추가/);
  assert.match(html, /후보 검토/);
});

test('admin module exports knowledge intake API helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchKnowledgeIntakeJobs, 'function');
  assert.equal(typeof module.createKnowledgeIntakeJob, 'function');
  assert.equal(typeof module.runKnowledgeIntakeJob, 'function');
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: FAIL because the section and exports do not exist.

- [ ] **Step 3: Add endpoints to config**

Modify `frontend/js/config.js` `API_CONFIG.ENDPOINTS`:

```javascript
ADMIN_KNOWLEDGE_INTAKE_JOBS: '/admin/knowledge/intake/jobs',
ADMIN_KNOWLEDGE_APPLY_APPROVED: '/admin/knowledge/apply-approved',
```

- [ ] **Step 4: Add API wrappers**

Append to `frontend/js/modules/admin.js`:

```javascript
export function fetchKnowledgeIntakeJobs() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS);
}

export function createKnowledgeIntakeJob(file) {
  const formData = new FormData();
  formData.append('file', file);
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS, {
    method: 'POST',
    body: formData,
    headers: {},
  });
}

export function runKnowledgeIntakeJob(jobId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS}/${encodeURIComponent(jobId)}/run`, {
    method: 'POST',
  });
}
```

- [ ] **Step 5: Add admin HTML section**

Add a nav item to `frontend/html/admin.html`:

```html
<div class="nav-item" data-admin-sub="knowledge">
  <svg fill="none" viewBox="0 0 24 24"><path d="M4 5h16M4 12h16M4 19h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
  지식 확장
</div>
```

Add section inside `.admin-body`:

```html
<div class="a-sub" id="sub-knowledge">
  <div class="knowledge-grid">
    <section class="data-card">
      <div class="data-card-hd"><h3>문서 추가</h3><span class="cnt-badge">관리자 전용</span></div>
      <div class="knowledge-upload">
        <input id="knowledge-file-input" class="fi" type="file" accept=".pdf,.xlsx,.xls,.csv"/>
        <button class="topbar-btn pri" type="button" data-admin-action="upload-knowledge-document">업로드</button>
      </div>
      <p class="knowledge-help">디지털 PDF와 Excel만 후보 추출을 진행합니다. 스캔 PDF는 텍스트 레이어 검사 후 차단됩니다.</p>
    </section>
    <section class="data-card">
      <div class="data-card-hd"><h3>문서 처리 상태</h3><span class="cnt-badge" id="knowledge-job-count">0건</span></div>
      <table>
        <thead><tr><th>파일</th><th>상태</th><th>메시지</th><th>관리</th></tr></thead>
        <tbody id="knowledge-job-body"></tbody>
      </table>
    </section>
    <section class="data-card">
      <div class="data-card-hd"><h3>후보 검토</h3></div>
      <div id="knowledge-review-summary" class="rag-info">문서 처리 완료 후 온톨로지/rule 후보가 표시됩니다.</div>
    </section>
  </div>
</div>
```

- [ ] **Step 6: Wire admin page behavior**

Modify imports in `frontend/js/pages/admin.js`:

```javascript
  fetchKnowledgeIntakeJobs,
  createKnowledgeIntakeJob,
  runKnowledgeIntakeJob,
```

Add `loadKnowledgeDashboard` to `loadAdminDashboard()`:

```javascript
loadKnowledgeDashboard().catch(() => null),
```

Add tab loading:

```javascript
if (sub === 'knowledge') await loadKnowledgeDashboard();
```

Add action handler cases:

```javascript
if (action === 'upload-knowledge-document') {
  await uploadKnowledgeDocument();
  return;
}
if (action === 'run-knowledge-intake') {
  await runKnowledgeIntake(actionTarget.dataset.jobId);
  return;
}
```

Add functions:

```javascript
async function loadKnowledgeDashboard() {
  const tbody = document.getElementById('knowledge-job-body');
  const badge = document.getElementById('knowledge-job-count');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="4">불러오는 중...</td></tr>';
  const data = normalizeListResponse(await fetchKnowledgeIntakeJobs());
  if (badge) badge.textContent = `${data.total}건`;
  tbody.innerHTML = data.items.map((job) => `
    <tr>
      <td>${escapeHTML(job.original_filename || '-')}</td>
      <td><span class="kb-status ${escapeHTML(job.status || '')}">${escapeHTML(job.status || '-')}</span></td>
      <td>${escapeHTML(job.message || '')}</td>
      <td>
        <button class="act-btn" type="button" data-admin-action="run-knowledge-intake" data-job-id="${escapeHTML(job.job_id)}">처리</button>
      </td>
    </tr>
  `).join('');
}

async function uploadKnowledgeDocument() {
  const input = document.getElementById('knowledge-file-input');
  const file = input?.files?.[0];
  if (!file) {
    toast('추가할 문서를 선택하세요.', 'warn');
    return;
  }
  const job = await createKnowledgeIntakeJob(file);
  toast(`${job.original_filename} 업로드가 등록되었습니다.`, 'success');
  await loadKnowledgeDashboard();
}

async function runKnowledgeIntake(jobId) {
  const job = await runKnowledgeIntakeJob(jobId);
  if (job.status === 'blocked_scanned_pdf') {
    toast(job.message, 'warn');
  } else {
    toast(job.message || '문서 처리가 완료되었습니다.', 'success');
  }
  await loadKnowledgeDashboard();
}
```

- [ ] **Step 7: Add focused styles**

Append to `frontend/css/admin.css`:

```css
.knowledge-grid {
  display: grid;
  gap: 14px;
}
.knowledge-upload {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.knowledge-help {
  margin: 10px 0 0;
  color: var(--gray);
  font-size: 12px;
  line-height: 1.5;
}
.kb-status {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  background: #eef4ff;
  color: var(--primary);
}
.kb-status.blocked_scanned_pdf,
.kb-status.blocked_unsupported,
.kb-status.failed {
  background: #fff2f0;
  color: #c2410c;
}
.kb-status.waiting_review,
.kb-status.completed {
  background: #edfdf3;
  color: #047857;
}
```

- [ ] **Step 8: Run frontend tests and build**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
cd frontend && npm run build
```

Expected: PASS and `frontend/dist/app.min.js` regenerated.

- [ ] **Step 9: Commit**

```bash
git add frontend/html/admin.html frontend/js/config.js frontend/js/modules/admin.js frontend/js/pages/admin.js frontend/css/admin.css frontend/dist/app.min.js tests/test_admin_knowledge_frontend.mjs
git commit -m "feat(admin): add document intake UI"
```

### Task 7: Admin Candidate Review APIs

**Files:**
- Modify: `src/api/routes/knowledge.py`
- Modify: `src/api/schemas/knowledge.py`
- Test: `tests/test_api_admin_knowledge.py`

- [ ] **Step 1: Add failing candidate API tests**

Append to `tests/test_api_admin_knowledge.py`:

```python
@pytest.mark.asyncio
async def test_list_rule_candidates_returns_pending_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = tmp_path / "rule_candidates.jsonl"
    candidates.write_text(
        '{"candidate_id":"rulecand.demo","status":"pending","proposed_rule":{"rule_id":"demo"},"proposed_links":{"source_refs":["chunk:1"]}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge, "RULE_CANDIDATES_PATH", candidates)

    payload = await knowledge.list_rule_candidates(_admin_user())

    assert payload["total"] == 1
    assert payload["items"][0]["candidate_id"] == "rulecand.demo"


@pytest.mark.asyncio
async def test_decide_rule_candidate_updates_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = tmp_path / "rule_candidates.jsonl"
    candidates.write_text(
        '{"candidate_id":"rulecand.demo","status":"pending","proposed_rule":{"rule_id":"demo"},"proposed_links":{"source_refs":["chunk:1"]}}\n',
        encoding="utf-8",
    )
    review_log = tmp_path / "review_log.jsonl"
    monkeypatch.setattr(knowledge, "RULE_CANDIDATES_PATH", candidates)
    monkeypatch.setattr(knowledge, "RULE_REVIEW_LOG_PATH", review_log)

    payload = await knowledge.decide_rule_candidate(
        "rulecand.demo",
        knowledge.CandidateDecisionRequest(decision="approve", reason="근거와 값이 일치합니다."),
        _admin_user(),
    )

    assert payload["status"] == "approved"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py::test_list_rule_candidates_returns_pending_items tests/test_api_admin_knowledge.py::test_decide_rule_candidate_updates_status -q
```

Expected: FAIL because endpoints/functions are not implemented.

- [ ] **Step 3: Add candidate schemas**

Extend `src/api/schemas/knowledge.py`:

```python
from typing import Literal


class CandidateDecisionRequest(BaseModel):
    decision: Literal["approve", "hold", "reject"]
    reason: str = Field(..., min_length=1, max_length=1000)


class CandidateListResponse(BaseModel):
    total: int
    items: list[dict]
```

- [ ] **Step 4: Add rule candidate API functions**

In `src/api/routes/knowledge.py`, add imports:

```python
import json
from src.api.schemas.knowledge import CandidateDecisionRequest, CandidateListResponse
from scripts.claim_rule_candidate_review import decide_candidate, load_jsonl, write_jsonl, append_log
```

Add constants:

```python
RULE_CANDIDATES_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "candidates.jsonl"
RULE_REVIEW_LOG_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "review_log.jsonl"
```

Add routes:

```python
@router.get("/rule-candidates", response_model=CandidateListResponse)
async def list_rule_candidates(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    records = load_jsonl(RULE_CANDIDATES_PATH)
    return {"total": len(records), "items": records}


@router.post("/rule-candidates/{candidate_id}/decision")
async def decide_rule_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    current: User = Depends(require_permission("admin.stats")),
) -> dict:
    records = load_jsonl(RULE_CANDIDATES_PATH)
    event = decide_candidate(records, candidate_id, payload.decision, current.username, payload.reason)
    write_jsonl(RULE_CANDIDATES_PATH, records)
    append_log(RULE_REVIEW_LOG_PATH, event)
    return next(record for record in records if record.get("candidate_id") == candidate_id)
```

- [ ] **Step 5: Add ontology candidate list/decision API**

Use existing `OntologyReviewStore`:

```python
from src.ontology.review_store import OntologyReviewStore

ONTOLOGY_CANDIDATES_PATH = config.ROOT_DIR / "data" / "ontology" / "review" / "candidates.jsonl"


@router.get("/ontology-candidates", response_model=CandidateListResponse)
async def list_ontology_candidates(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    store = OntologyReviewStore(candidates_path=ONTOLOGY_CANDIDATES_PATH)
    records = [candidate.to_dict() for candidate in store.load_candidates()]
    return {"total": len(records), "items": records}
```

For ontology decision, call the store method used by `scripts/ontology_review.py`; if the store exposes no direct method for the same transition, add a small helper in `knowledge.py` that loads candidate objects, updates `status`, reviewer fields, and writes through `OntologyReviewStore` APIs already present in the file.

- [ ] **Step 6: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_admin_knowledge.py tests/test_claim_rule_candidate_review.py tests/test_ontology_review_store.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/knowledge.py src/api/schemas/knowledge.py tests/test_api_admin_knowledge.py
git commit -m "feat(admin): expose candidate review APIs"
```

### Task 8: Admin Candidate Review UI

**Files:**
- Modify: `frontend/js/config.js`
- Modify: `frontend/js/modules/admin.js`
- Modify: `frontend/js/pages/admin.js`
- Modify: `frontend/html/admin.html`
- Modify: `frontend/css/admin.css`
- Test: `tests/test_admin_knowledge_frontend.mjs`

- [ ] **Step 1: Add failing frontend test for candidate review controls**

Append to `tests/test_admin_knowledge_frontend.mjs`:

```javascript
test('admin module exports candidate review helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchOntologyCandidates, 'function');
  assert.equal(typeof module.fetchRuleCandidates, 'function');
  assert.equal(typeof module.decideRuleCandidate, 'function');
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: FAIL because candidate helpers do not exist.

- [ ] **Step 3: Add frontend endpoints and wrappers**

In `frontend/js/config.js`:

```javascript
ADMIN_ONTOLOGY_CANDIDATES: '/admin/knowledge/ontology-candidates',
ADMIN_RULE_CANDIDATES: '/admin/knowledge/rule-candidates',
```

In `frontend/js/modules/admin.js`:

```javascript
export function fetchOntologyCandidates() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_ONTOLOGY_CANDIDATES);
}

export function fetchRuleCandidates() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_RULE_CANDIDATES);
}

export function decideRuleCandidate(candidateId, decision, reason) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_RULE_CANDIDATES}/${encodeURIComponent(candidateId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, reason }),
  });
}
```

- [ ] **Step 4: Render candidate summaries**

Add to `frontend/js/pages/admin.js`:

```javascript
async function loadKnowledgeCandidates() {
  const container = document.getElementById('knowledge-review-summary');
  if (!container) return;
  const [ontology, rules] = await Promise.all([
    fetchOntologyCandidates().catch(() => ({ items: [] })),
    fetchRuleCandidates().catch(() => ({ items: [] })),
  ]);
  container.innerHTML = `
    <div class="candidate-columns">
      <section>
        <h4>온톨로지 후보 ${Number(ontology.items?.length || 0)}건</h4>
        ${renderCandidateList(ontology.items || [], 'ontology')}
      </section>
      <section>
        <h4>계산 룰 후보 ${Number(rules.items?.length || 0)}건</h4>
        ${renderCandidateList(rules.items || [], 'rule')}
      </section>
    </div>
  `;
}

function renderCandidateList(items, kind) {
  if (!items.length) return '<p class="knowledge-help">검토할 후보가 없습니다.</p>';
  return items.slice(0, 100).map((item) => `
    <article class="candidate-card">
      <div class="candidate-title">${escapeHTML(item.canonical_name || item.proposed_rule?.description || item.candidate_id || '-')}</div>
      <div class="candidate-meta">${escapeHTML(item.status || '-')} · ${escapeHTML(item.candidate_id || '-')}</div>
      <pre>${escapeHTML((item.evidence_text || item.description || '').slice(0, 700))}</pre>
      ${kind === 'rule' ? `
        <div class="candidate-actions">
          <button class="act-btn" type="button" data-admin-action="approve-rule-candidate" data-candidate-id="${escapeHTML(item.candidate_id)}">승인</button>
          <button class="act-btn del" type="button" data-admin-action="reject-rule-candidate" data-candidate-id="${escapeHTML(item.candidate_id)}">거절</button>
        </div>` : ''}
    </article>
  `).join('');
}
```

Call `loadKnowledgeCandidates()` inside `loadKnowledgeDashboard()` after job load.

Add action handler:

```javascript
if (action === 'approve-rule-candidate' || action === 'reject-rule-candidate') {
  const decision = action === 'approve-rule-candidate' ? 'approve' : 'reject';
  const reason = window.prompt('실무자 판단 사유를 입력하세요.');
  if (!reason) return;
  await decideRuleCandidate(actionTarget.dataset.candidateId, decision, reason);
  toast('후보 처리 결과를 저장했습니다.', 'success');
  await loadKnowledgeDashboard();
  return;
}
```

- [ ] **Step 5: Add candidate styles**

Append to `frontend/css/admin.css`:

```css
.candidate-columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}
.candidate-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 10px;
  background: #fff;
}
.candidate-title {
  font-weight: 700;
  font-size: 13px;
}
.candidate-meta {
  margin-top: 4px;
  color: var(--gray);
  font-size: 11px;
}
.candidate-card pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 160px;
  overflow: auto;
  background: #f8fafc;
  padding: 8px;
  border-radius: 6px;
  font-size: 11px;
}
.candidate-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
```

- [ ] **Step 6: Run frontend tests and build**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/js/config.js frontend/js/modules/admin.js frontend/js/pages/admin.js frontend/html/admin.html frontend/css/admin.css frontend/dist/app.min.js tests/test_admin_knowledge_frontend.mjs
git commit -m "feat(admin): move candidate review into admin UI"
```

### Task 9: Apply Approved Candidates and Rebuild Active Knowledge

**Files:**
- Create: `src/ingest/knowledge_apply.py`
- Modify: `src/api/routes/knowledge.py`
- Test: `tests/test_knowledge_apply.py`
- Test: `tests/test_api_admin_knowledge.py`

- [ ] **Step 1: Write failing apply orchestration tests**

Create `tests/test_knowledge_apply.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.ingest.knowledge_apply import KnowledgeApplyResult, apply_approved_knowledge


def test_apply_approved_knowledge_runs_steps_in_order(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda: calls.append("ontology") or {"merged_candidate_count": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda: calls.append("rules") or {"applied": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert isinstance(result, KnowledgeApplyResult)
    assert calls == ["ontology", "rules", "graph"]
    assert result.status == "completed"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_apply.py -q
```

Expected: FAIL because `src.ingest.knowledge_apply` does not exist.

- [ ] **Step 3: Implement apply orchestration**

Create `src/ingest/knowledge_apply.py`:

```python
from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src import config


@dataclass(frozen=True)
class KnowledgeApplyResult:
    status: str
    ontology: dict[str, Any]
    rules: dict[str, Any]
    graph_rebuilt: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_json_command(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=config.ROOT_DIR,
        text=True,
        capture_output=True,
        check=True,
    )
    return {"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def apply_ontology_reviews() -> dict[str, Any]:
    return _run_json_command(["scripts/ontology_review.py", "--apply"])


def apply_rule_candidates() -> dict[str, Any]:
    return _run_json_command(["scripts/claim_rule_candidate_review.py", "--apply"])


def rebuild_graph() -> None:
    subprocess.run(
        [sys.executable, "scripts/build_graph_index.py", "--rebuild"],
        cwd=config.ROOT_DIR,
        check=True,
    )


def apply_approved_knowledge() -> KnowledgeApplyResult:
    ontology = apply_ontology_reviews()
    rules = apply_rule_candidates()
    rebuild_graph()
    return KnowledgeApplyResult(
        status="completed",
        ontology=ontology,
        rules=rules,
        graph_rebuilt=True,
    )
```

- [ ] **Step 4: Add admin API endpoint**

In `src/api/routes/knowledge.py`, import:

```python
from src.ingest.knowledge_apply import apply_approved_knowledge
```

Add route:

```python
@router.post("/apply-approved")
async def apply_approved(
    _: User = Depends(require_permission("admin.stats")),
) -> dict:
    return apply_approved_knowledge().as_dict()
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_apply.py tests/test_api_admin_knowledge.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ingest/knowledge_apply.py src/api/routes/knowledge.py tests/test_knowledge_apply.py tests/test_api_admin_knowledge.py
git commit -m "feat(admin): apply approved knowledge from admin API"
```

### Task 10: Frontend Apply Button and Executioner UI Demotion

**Files:**
- Modify: `frontend/js/modules/admin.js`
- Modify: `frontend/js/pages/admin.js`
- Modify: `frontend/html/admin.html`
- Modify: `ops/bin/insurance-rag-desktop-launcher`
- Test: `tests/test_admin_knowledge_frontend.mjs`
- Test: `tests/test_desktop_launcher_choices.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_admin_knowledge_frontend.mjs`:

```javascript
test('knowledge section has apply approved button', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-action="apply-approved-knowledge"/);
});
```

Update `tests/test_desktop_launcher_choices.py` with an assertion that executioner labels mention fallback:

```python
def test_desktop_launcher_marks_review_gui_as_fallback():
    source = Path("ops/bin/insurance-rag-desktop-launcher").read_text(encoding="utf-8")
    assert "관리자 페이지 우선" in source
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
.venv/bin/python -m pytest tests/test_desktop_launcher_choices.py -q
```

Expected: FAIL until the apply button and launcher wording are added.

- [ ] **Step 3: Add apply wrapper and UI action**

In `frontend/js/modules/admin.js`:

```javascript
export function applyApprovedKnowledge() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_APPLY_APPROVED, {
    method: 'POST',
  });
}
```

In `frontend/html/admin.html`, add button in the knowledge review section:

```html
<button class="topbar-btn pri" type="button" data-admin-action="apply-approved-knowledge">승인 항목 반영</button>
```

In `frontend/js/pages/admin.js`, add import and action:

```javascript
if (action === 'apply-approved-knowledge') {
  await applyApprovedKnowledge();
  toast('승인된 지식 항목을 active DB에 반영했습니다.', 'success');
  await loadKnowledgeDashboard();
  return;
}
```

- [ ] **Step 4: Adjust launcher wording without removing fallback**

Modify `ops/bin/insurance-rag-desktop-launcher` label strings for ontology/rule review rows:

```bash
rows+=("FALSE" "ontology|review|${ontology_pending_count:-0}" "온톨로지 승인 검토" "관리자 페이지 우선, 실행기 fallback")
rows+=("FALSE" "rules|candidate|${candidate_count:-0}" "액티브 룰 신규 후보" "관리자 페이지 우선, 실행기 fallback")
rows+=("FALSE" "rules|review|active" "액티브 룰 검토" "관리자 페이지 우선, 실행기 fallback")
```

- [ ] **Step 5: Run tests, shell syntax, and frontend build**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
.venv/bin/python -m pytest tests/test_desktop_launcher_choices.py -q
bash -n ops/bin/insurance-rag-desktop-launcher
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/js/modules/admin.js frontend/js/pages/admin.js frontend/html/admin.html frontend/dist/app.min.js ops/bin/insurance-rag-desktop-launcher tests/test_admin_knowledge_frontend.mjs tests/test_desktop_launcher_choices.py
git commit -m "feat(admin): apply approved knowledge from admin UI"
```

### Task 11: DGX Integration Validation

**Files:**
- Modify: `docs/257_ADMIN_DOCUMENT_INTAKE_KNOWLEDGE_EXTENSION_REPORT.md`
- Test: DGX commands

- [ ] **Step 1: Run local focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_document_intake_detector.py \
  tests/test_file_intake_planner.py \
  tests/test_intake_store.py \
  tests/test_intake_runner.py \
  tests/test_api_admin_knowledge.py \
  tests/test_knowledge_apply.py \
  tests/test_claim_rule_candidate_review.py \
  tests/test_ontology_review_store.py \
  tests/test_desktop_launcher_choices.py -q
node --test tests/test_admin_knowledge_frontend.mjs
cd frontend && npm run build
```

Expected: all Python tests pass, Node test passes, frontend build succeeds.

- [ ] **Step 2: Patch DGX master and run focused tests**

Run from Mac:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && git status --short --branch'
```

Expected: DGX worktree is clean or only has known runtime artifacts outside Git.

After applying the branch or pushing and pulling on DGX, run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest tests/test_document_intake_detector.py tests/test_file_intake_planner.py tests/test_intake_store.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_knowledge_apply.py tests/test_desktop_launcher_choices.py -q'
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot/frontend && npm run build'
```

Expected: pytest pass and frontend build succeeds.

- [ ] **Step 3: DGX scanned PDF gate smoke**

Run a minimal smoke with a synthetic no-text PDF fixture created in `/tmp` or an existing safe fixture:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python - <<'"'"'PY'"'"'
from pathlib import Path
from src.ingest.intake_store import IntakeJobStore, IntakeJobStatus
from src.ingest.intake_runner import run_intake_job_once

root = Path("data/intake/jobs-smoke")
store = IntakeJobStore(root)
job = store.create_job(original_filename="scan.pdf", uploaded_by="admin", document_kind="pdf")
src = store.job_dir(job.job_id) / "source" / "scan.pdf"
src.parent.mkdir(parents=True, exist_ok=True)
src.write_bytes(b"%PDF-1.4\n% empty smoke file\n")
store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(src))
result = run_intake_job_once(store, job.job_id)
print(result.status.value)
print(result.message)
PY'
```

Expected: command finishes without active DB mutation. If the parser rejects the empty PDF, result may be `failed`; record that the formal scan gate needs a valid image-only PDF fixture for final QA.

- [ ] **Step 4: Write implementation report**

Create `docs/257_ADMIN_DOCUMENT_INTAKE_KNOWLEDGE_EXTENSION_REPORT.md`:

```markdown
# 257. Admin Document Intake Knowledge Extension Report

## Summary

관리자 페이지에 문서 추가, 문서 처리 상태, 후보 검토, 승인 항목 반영 흐름을 추가했다. 스캔 PDF/OCR 자동화는 수행하지 않으며, 텍스트 레이어가 없는 PDF는 후보 추출 전에 차단한다.

## Changed Files

- `src/ingest/document_intake.py`
- `src/ingest/intake_store.py`
- `src/ingest/intake_runner.py`
- `src/ingest/knowledge_apply.py`
- `src/api/routes/knowledge.py`
- `src/api/schemas/knowledge.py`
- `frontend/html/admin.html`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`
- `frontend/css/admin.css`
- `ops/bin/insurance-rag-desktop-launcher`

## Validation

- Python focused tests: passed
- Frontend Node tests: passed
- Frontend build: passed
- DGX focused tests: passed

## 000 Guardrail Check

- 승인 전 후보는 active ontology/rule/index에 반영되지 않는다.
- 스캔 PDF는 OCR/LLM 추정으로 메우지 않고 차단한다.
- 계산값은 active rule manifest만 실행 원천으로 유지한다.
- GraphDB는 source/ontology/rule 연결을 추적하는 계층으로만 사용한다.

## Remaining Risks

- 대용량 PDF 처리 시간은 문서 크기에 비례한다.
- 디지털 PDF 표 구조 추출 품질은 기존 table extraction 성능에 의존한다.
- 기존 실행기 승인 UI는 fallback으로 남아 있어 운영 정책상 제거 여부를 별도 결정할 수 있다.
```

- [ ] **Step 5: Commit report and final implementation**

```bash
git add docs/257_ADMIN_DOCUMENT_INTAKE_KNOWLEDGE_EXTENSION_REPORT.md
git commit -m "docs(admin): report document intake knowledge extension"
```

## Self-Review

### Spec Coverage

- 관리자 UI 기반 2단계 확장 플로우: Tasks 3, 6, 8, 10.
- 스캔 PDF/OCR 자동화 금지와 텍스트 레이어 차단: Tasks 1, 4, 11.
- 문서 추가 후 후보 자동 생성: Tasks 4, 5.
- 후보 승인 UI를 실행기에서 관리자 페이지로 이동: Tasks 7, 8, 10.
- 승인 후 DB/index/GraphDB 반영: Task 9.
- 000번 규칙 준수: Tasks 1, 5, 9, 11.

### Placeholder Scan

이 계획은 구현자가 작성할 구체 파일, 함수명, 테스트명, 명령, 기대 결과를 포함한다. 의도적으로 구현을 미루는 미정 항목은 없다.

### Type Consistency

- `IntakeJobStatus` 값은 `intake_store.py`, `intake_runner.py`, API 응답, frontend badge class에서 같은 snake_case 문자열을 사용한다.
- `IntakeJob.as_dict()` 결과는 `IntakeJobResponse` 필드와 일치한다.
- 관리자 frontend helper 이름은 `fetchKnowledgeIntakeJobs`, `createKnowledgeIntakeJob`, `runKnowledgeIntakeJob`, `fetchRuleCandidates`, `decideRuleCandidate`, `applyApprovedKnowledge`로 일관된다.
