# P1 Runtime Operations Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align runtime model metadata, official app guidance, clause detail index defaults, and new-file ingestion entrypoints with the current source-grounded FastAPI + SPA architecture.

**Architecture:** Keep the runtime code as a thin orchestrator: model metadata reports what can actually run, retrieval defaults always include corrected OCR data, and new-file ingestion starts as a dry-run plan generator before any DB mutation. Insurance knowledge discovered from newly added files must become pending candidates and move through the practitioner approval workflow before becoming active ontology or rule knowledge.

**Tech Stack:** Python 3.11, FastAPI, pytest, shell launchers under `ops/bin`, static SPA under `frontend/`, JSON manifests, existing ontology review scripts.

---

## Guardrails From `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`

- Code must not encode insurance payout, exemption, reduction, deductible, or limit knowledge.
- Runtime defaults must not provide a normal user path that excludes corrected OCR documents.
- LLM formula generation must not be final calculation authority.
- New ontology, alias, relation, and rule knowledge starts as candidate or pending state.
- When there are multiple solutions for ontology hardcoding prevention, prefer practitioner approval over silent policy-file promotion.
- Streamlit is legacy only and must not become the target for new feature work.

## File Structure

- Modify: `src/llm/factory.py`  
  Report model availability from explicit runtime metadata and keep `gpt-oss-120b` out of ordinary selectable candidates on DGX Spark.
- Modify: `src/api/routes/system.py`  
  Ensure `/api/system/models` exposes disabled/unsupported status only as diagnostics, not as selectable defaults.
- Modify: `ops/bin/insurance-rag-common`  
  Keep launcher defaults on supported models and mark 120B as unsupported on DGX Spark.
- Modify: `ops/bin/insurance-rag-desktop-launcher`  
  Prevent desktop launch messages from presenting 120B as a normal model choice.
- Modify: `src/rag/index_profiles.py` or the existing index-mode module discovered by `rg "v2_only|index_mode|clause_detail_rows" src`  
  Make corrected OCR `v2_only` the resolved default for ordinary chat/search paths.
- Modify: `src/api/routes/chat.py`  
  Reject or normalize user-facing `default` index mode so OCR-corrected data remains included.
- Modify: `src/rag/clause_detail_rows.py`  
  Surface row-manifest existence and row count for diagnostics.
- Create: `src/ingest/file_intake_planner.py`  
  Generate a dry-run plan for Excel, digital PDF, scanned PDF, and image inputs without mutating indexes.
- Create: `tests/test_runtime_model_metadata.py`  
  Regression tests for 120B unsupported status and selectable model filtering.
- Create: `tests/test_index_mode_defaults.py`  
  Regression tests for corrected OCR default behavior.
- Create: `tests/test_file_intake_planner.py`  
  Tests for new-file plan generation and ontology candidate gating.
- Modify: `README.md`  
  Replace legacy-first app guidance with FastAPI + SPA official workflow.

---

## Task 1: Encode 120B Runtime Status As Unsupported On DGX Spark

**Files:**
- Modify: `src/llm/factory.py`
- Modify: `src/api/routes/system.py`
- Modify: `ops/bin/insurance-rag-common`
- Modify: `ops/bin/insurance-rag-desktop-launcher`
- Test: `tests/test_runtime_model_metadata.py`

- [ ] **Step 1: Locate the existing model metadata and status fields**

Run:

```bash
rg -n "gpt-oss-120b|120b|system/models|available_models|MODEL" src ops tests
```

Expected: The command prints the current Python metadata location, system route, and launcher references for model selection.

- [ ] **Step 2: Write the failing model metadata test**

Create `tests/test_runtime_model_metadata.py` with this content, adjusting only the imported function names after Step 1 identifies the exact local API:

```python
from __future__ import annotations


def test_gpt_oss_120b_is_not_selectable_on_dgx_spark(monkeypatch):
    from src.llm.factory import list_runtime_models

    monkeypatch.setenv("INSURANCE_RAG_RUNTIME_PROFILE", "dgx_spark")

    models = list_runtime_models(provider="trtllm", include_diagnostics=True)
    target = next(model for model in models if model["id"] == "openai/gpt-oss-120b")

    assert target["status"] in {"disabled", "unsupported_on_dgx_spark"}
    assert target["selectable"] is False
    assert "DGX Spark" in target["reason"]


def test_system_models_excludes_unsupported_120b_from_selectable_list(monkeypatch):
    from src.llm.factory import list_runtime_models

    monkeypatch.setenv("INSURANCE_RAG_RUNTIME_PROFILE", "dgx_spark")

    selectable = [
        model
        for model in list_runtime_models(provider="trtllm", include_diagnostics=False)
        if model.get("selectable", True)
    ]

    assert all(model["id"] != "openai/gpt-oss-120b" for model in selectable)
```

- [ ] **Step 3: Run the failing test**

Run:

```bash
.venv/bin/python -m pytest tests/test_runtime_model_metadata.py -q
```

Expected: FAIL because the current metadata still exposes TRTLLM 120B as experimental or lacks `selectable`/`reason` fields.

- [ ] **Step 4: Add the minimal runtime metadata contract**

In `src/llm/factory.py`, add or adapt a model metadata helper with this shape. Keep existing public function names if they already exist; the contract below is the target behavior:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeModel:
    id: str
    provider: str
    label: str
    status: str
    selectable: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "status": self.status,
            "selectable": self.selectable,
            "reason": self.reason,
        }


def _trtllm_runtime_models() -> list[RuntimeModel]:
    return [
        RuntimeModel(
            id="openai/gpt-oss-120b",
            provider="trtllm",
            label="GPT-OSS 120B",
            status="unsupported_on_dgx_spark",
            selectable=False,
            reason="DGX Spark single-device runtime was tested and classified as not usable for this project.",
        ),
    ]


def list_runtime_models(provider: str | None = None, include_diagnostics: bool = False) -> list[dict[str, Any]]:
    models = _trtllm_runtime_models()
    if provider:
        models = [model for model in models if model.provider == provider]
    if not include_diagnostics:
        models = [model for model in models if model.selectable]
    return [model.as_dict() for model in models]
```

If `list_runtime_models` already exists, merge the `unsupported_on_dgx_spark` entry into the existing return structure instead of introducing a duplicate registry.

- [ ] **Step 5: Filter system route output through the selectable flag**

In `src/api/routes/system.py`, ensure the user-facing model list only includes selectable models unless the route already has a diagnostics mode:

```python
@router.get("/models")
def get_system_models(include_diagnostics: bool = False) -> dict[str, object]:
    from src.llm.factory import list_runtime_models

    return {
        "models": list_runtime_models(include_diagnostics=include_diagnostics),
        "diagnostics_included": include_diagnostics,
    }
```

If the existing route returns a larger object, preserve its keys and replace only the model-list construction.

- [ ] **Step 6: Keep launchers from suggesting 120B as a normal choice**

In `ops/bin/insurance-rag-common`, keep 120B out of defaults and add this comment beside any remaining 120B branch:

```bash
# GPT-OSS 120B is retained only as historical diagnostics. It is not a selectable
# DGX Spark runtime model for this project.
```

In `ops/bin/insurance-rag-desktop-launcher`, change any user-facing menu text from “experimental” or “available” to “unsupported on this DGX Spark project state” when it mentions 120B.

- [ ] **Step 7: Run the metadata and shell syntax tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_runtime_model_metadata.py -q
bash -n ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher
```

Expected: PASS for pytest and no output from `bash -n`.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/llm/factory.py src/api/routes/system.py ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher tests/test_runtime_model_metadata.py
git commit -m "fix(llm): mark 120b unsupported on dgx spark"
```

---

## Task 2: Make Corrected OCR Index The Ordinary Chat Default

**Files:**
- Modify: `src/rag/index_profiles.py` or existing index-mode module found by search
- Modify: `src/api/routes/chat.py`
- Modify: `src/rag/clause_detail_rows.py`
- Test: `tests/test_index_mode_defaults.py`

- [ ] **Step 1: Find the current index-mode resolution code**

Run:

```bash
rg -n "v2_only|v1_v2_combined|clause_detail_rows|index_mode|default index|기본 인덱스" src frontend tests
```

Expected: The command identifies the index-mode resolver and chat route parameter handling.

- [ ] **Step 2: Write the failing default-resolution tests**

Create `tests/test_index_mode_defaults.py`:

```python
from __future__ import annotations


def test_user_default_index_resolves_to_corrected_ocr_profile():
    from src.rag.index_profiles import resolve_index_profile

    profile = resolve_index_profile("default", user_facing=True)

    assert profile.name == "v2_only"
    assert profile.includes_corrected_ocr is True
    assert profile.includes_ocr_documents is True


def test_empty_index_mode_resolves_to_corrected_ocr_profile():
    from src.rag.index_profiles import resolve_index_profile

    profile = resolve_index_profile(None, user_facing=True)

    assert profile.name == "v2_only"
    assert profile.includes_corrected_ocr is True


def test_clause_detail_rows_diagnostics_reports_missing_file(tmp_path):
    from src.rag.clause_detail_rows import describe_clause_detail_rows

    missing = tmp_path / "clause_detail_rows.jsonl"

    diagnostics = describe_clause_detail_rows(missing)

    assert diagnostics["exists"] is False
    assert diagnostics["row_count"] == 0
    assert diagnostics["status"] == "missing"
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_index_mode_defaults.py -q
```

Expected: FAIL because `resolve_index_profile` or diagnostics do not yet expose this exact behavior.

- [ ] **Step 4: Implement a focused index profile resolver**

In the existing index-mode module, or in a new `src/rag/index_profiles.py` if no focused module exists, implement this contract:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexProfile:
    name: str
    includes_corrected_ocr: bool
    includes_ocr_documents: bool


_PROFILES: dict[str, IndexProfile] = {
    "v2_only": IndexProfile(
        name="v2_only",
        includes_corrected_ocr=True,
        includes_ocr_documents=True,
    ),
    "v1_v2_combined": IndexProfile(
        name="v1_v2_combined",
        includes_corrected_ocr=True,
        includes_ocr_documents=True,
    ),
}


def resolve_index_profile(index_mode: str | None, *, user_facing: bool = True) -> IndexProfile:
    normalized = (index_mode or "v2_only").strip()
    if user_facing and normalized in {"", "default", "basic"}:
        normalized = "v2_only"
    if normalized not in _PROFILES:
        raise ValueError(f"Unsupported index mode: {normalized}")
    return _PROFILES[normalized]
```

If existing code already defines profile objects, add `includes_corrected_ocr` and `includes_ocr_documents` to that object instead of creating a parallel type.

- [ ] **Step 5: Normalize chat route input before pipeline execution**

In `src/api/routes/chat.py`, route user-facing index input through `resolve_index_profile`:

```python
from src.rag.index_profiles import resolve_index_profile


def _resolve_chat_index_mode(index_mode: str | None) -> str:
    return resolve_index_profile(index_mode, user_facing=True).name
```

Use `_resolve_chat_index_mode(request.index_mode)` before passing options into the RAG pipeline.

- [ ] **Step 6: Add clause-detail row diagnostics**

In `src/rag/clause_detail_rows.py`, add:

```python
from __future__ import annotations

from pathlib import Path


def describe_clause_detail_rows(path: str | Path) -> dict[str, object]:
    row_path = Path(path)
    if not row_path.exists():
        return {"path": str(row_path), "exists": False, "row_count": 0, "status": "missing"}
    with row_path.open("r", encoding="utf-8") as handle:
        row_count = sum(1 for line in handle if line.strip())
    return {"path": str(row_path), "exists": True, "row_count": row_count, "status": "ready"}
```

Wire this diagnostic into the existing admin/system diagnostics response if that response already reports index files.

- [ ] **Step 7: Run index and chat tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_index_mode_defaults.py tests/test_api_chat_stream.py -q
```

Expected: PASS. If `tests/test_api_chat_stream.py` does not exist in the current checkout, run the closest chat route test found by `rg -n "chat_stream|/chat|ChatRequest" tests`.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/rag/index_profiles.py src/api/routes/chat.py src/rag/clause_detail_rows.py tests/test_index_mode_defaults.py
git commit -m "fix(rag): default chat index to corrected ocr"
```

---

## Task 3: Update README To Current FastAPI + SPA Operations

**Files:**
- Modify: `README.md`
- Test: shell grep checks

- [ ] **Step 1: Identify legacy guidance that conflicts with the current app**

Run:

```bash
rg -n "Streamlit|streamlit|Discord|Ollama|Stage 2|FastAPI|SPA|insurance-rag-up|desktop" README.md docs ops
```

Expected: The command lists legacy and current operational references.

- [ ] **Step 2: Replace README with a current operational outline**

Update `README.md` so its top-level sections are:

```markdown
# Insurance RAG Chatbot

## Current Official Runtime

The official app runtime is FastAPI plus the static SPA under `frontend/`.

## DGX Runtime

Use the DGX launcher scripts under `ops/bin/` for the main project runtime.

## Local Development

Use local Python tests and static frontend checks for code changes. Local data and generated artifacts are not committed.

## Data And Evidence Policy

Insurance knowledge must come from source documents, approved ontology manifests, rule tables, GraphDB evidence, or row-level table evidence.

## Testing

Run `.venv/bin/python -m pytest -q` for the default test suite when the DGX virtual environment is available.

## Legacy Streamlit

Streamlit files are retained as legacy references only. New features target the FastAPI + SPA runtime.

## Documents

Start with `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md` before changing project logic.
```

Keep existing useful setup commands if they still point to FastAPI + SPA and do not contradict the sections above.

- [ ] **Step 3: Verify README no longer presents Streamlit as official**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path("README.md").read_text(encoding="utf-8")
assert "FastAPI" in text
assert "SPA" in text
legacy = [line for line in text.splitlines() if "Streamlit" in line or "streamlit" in line]
assert all("legacy" in line.lower() or "retained" in line.lower() for line in legacy)
print("README runtime guidance OK")
PY
```

Expected:

```text
README runtime guidance OK
```

- [ ] **Step 4: Commit Task 3**

```bash
git add README.md
git commit -m "docs(readme): align runtime guidance with fastapi spa"
```

---

## Task 4: Add New-File Intake Dry-Run Planner

**Files:**
- Create: `src/ingest/file_intake_planner.py`
- Create: `tests/test_file_intake_planner.py`
- Modify: `src/ingest/__init__.py` if the package already exists

- [ ] **Step 1: Find existing ingestion and indexing entrypoints**

Run:

```bash
rg -n "ingest|index|OCR|digital PDF|xlsx|ontology candidate|extract_ontology_candidates" src scripts tests docs
```

Expected: The command identifies existing indexing scripts and ontology candidate generation commands.

- [ ] **Step 2: Write failing dry-run planner tests**

Create `tests/test_file_intake_planner.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_excel_file_generates_excel_intake_plan(tmp_path):
    from src.ingest.file_intake_planner import plan_file_intake

    path = tmp_path / "sample.xlsx"
    path.write_bytes(b"PK\x03\x04")

    plan = plan_file_intake(path)

    assert plan.file_type == "excel"
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is True
    assert "extract_rows" in plan.steps
    assert "ontology_candidates_pending" in plan.steps


def test_pdf_file_starts_with_document_type_detection(tmp_path):
    from src.ingest.file_intake_planner import plan_file_intake

    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.7\n")

    plan = plan_file_intake(path)

    assert plan.file_type == "pdf"
    assert plan.steps[0] == "detect_pdf_text_layer"
    assert plan.requires_practitioner_approval is True


def test_unsupported_file_is_rejected_before_processing(tmp_path):
    from src.ingest.file_intake_planner import plan_file_intake

    path = tmp_path / "sample.zip"
    path.write_bytes(b"not an intake document")

    plan = plan_file_intake(path)

    assert plan.file_type == "unsupported"
    assert plan.mutates_indexes is False
    assert plan.steps == ["reject_unsupported_file"]
```

- [ ] **Step 3: Run the failing planner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_file_intake_planner.py -q
```

Expected: FAIL because `src.ingest.file_intake_planner` does not exist or lacks the contract.

- [ ] **Step 4: Implement the dry-run planner**

Create `src/ingest/file_intake_planner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntakePlan:
    path: str
    file_type: str
    steps: list[str]
    mutates_indexes: bool
    requires_practitioner_approval: bool


def _suffix(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def plan_file_intake(path: str | Path) -> IntakePlan:
    source = Path(path)
    suffix = _suffix(source)

    if suffix in {"xlsx", "xls", "csv"}:
        return IntakePlan(
            path=str(source),
            file_type="excel",
            steps=[
                "extract_rows",
                "validate_source_columns",
                "build_search_chunks",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
            mutates_indexes=False,
            requires_practitioner_approval=True,
        )

    if suffix == "pdf":
        return IntakePlan(
            path=str(source),
            file_type="pdf",
            steps=[
                "detect_pdf_text_layer",
                "choose_digital_or_scanned_pipeline",
                "extract_tables_or_ocr",
                "build_search_chunks",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
            mutates_indexes=False,
            requires_practitioner_approval=True,
        )

    if suffix in {"png", "jpg", "jpeg", "tif", "tiff"}:
        return IntakePlan(
            path=str(source),
            file_type="image",
            steps=[
                "run_scanned_document_pipeline",
                "build_review_artifacts",
                "ontology_candidates_pending",
                "wait_for_practitioner_approval",
            ],
            mutates_indexes=False,
            requires_practitioner_approval=True,
        )

    return IntakePlan(
        path=str(source),
        file_type="unsupported",
        steps=["reject_unsupported_file"],
        mutates_indexes=False,
        requires_practitioner_approval=False,
    )
```

If `src/ingest/__init__.py` exists, export the function:

```python
from src.ingest.file_intake_planner import IntakePlan, plan_file_intake

__all__ = ["IntakePlan", "plan_file_intake"]
```

- [ ] **Step 5: Run planner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_file_intake_planner.py -q
```

Expected: PASS.

- [ ] **Step 6: Confirm no new-file path mutates production data**

Run:

```bash
python - <<'PY'
from pathlib import Path
from src.ingest.file_intake_planner import plan_file_intake
for name in ["a.xlsx", "b.pdf", "c.jpg"]:
    plan = plan_file_intake(Path(name))
    assert plan.mutates_indexes is False
    assert "wait_for_practitioner_approval" in plan.steps
print("intake dry-run plans are approval-gated")
PY
```

Expected:

```text
intake dry-run plans are approval-gated
```

- [ ] **Step 7: Commit Task 4**

```bash
git add src/ingest/file_intake_planner.py src/ingest/__init__.py tests/test_file_intake_planner.py
git commit -m "feat(ingest): add approval gated intake planner"
```

---

## Task 5: P1 Integrated Verification And Self-Inspection

**Files:**
- Review: all files changed in Tasks 1-4

- [ ] **Step 1: Run focused P1 tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_runtime_model_metadata.py \
  tests/test_index_mode_defaults.py \
  tests/test_file_intake_planner.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run route and shell checks**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_chat_stream.py -q
bash -n ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher
```

Expected: PASS and no shell syntax output. If `tests/test_api_chat_stream.py` is absent, run the chat route test located by `rg -n "ChatRequest|chat stream|api chat" tests`.

- [ ] **Step 3: Search for P1 guardrail regressions**

Run:

```bash
rg -n "gpt-oss-120b|Streamlit|streamlit|default index|기본 인덱스|wait_for_practitioner_approval|mutates_indexes" README.md src ops tests
```

Expected:

- `gpt-oss-120b` appears only with disabled or unsupported status.
- Streamlit appears only as legacy.
- New-file intake plans contain `wait_for_practitioner_approval`.
- No user-facing “basic/default index” path excludes corrected OCR.

- [ ] **Step 4: Run the default test suite when DGX resources are available**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. If DGX resource contention blocks this run, record the blocker and the focused tests that passed.

- [ ] **Step 5: Write the P1 self-inspection note**

Add a short section to the task completion report or final response:

```markdown
### P1 Self-Inspection

- 000 compliance: 120B metadata is operational status, not insurance knowledge.
- OCR default: ordinary chat/search paths resolve to corrected OCR data.
- Ontology hardcoding prevention: new-file intake produces pending candidates and requires practitioner approval.
- Legacy boundary: Streamlit is documented as retained legacy only.
- Remaining risk: dry-run intake does not yet execute DB rebuild; that belongs to the later ingestion implementation phase.
```

- [ ] **Step 6: Commit Task 5 if the report is stored in the repository**

```bash
git add docs
git commit -m "docs(p1): record runtime alignment verification"
```
