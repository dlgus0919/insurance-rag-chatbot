# P2 Data OCR Test Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make storage inventory, hospital receipt OCR boundaries, and test selection explicit without deleting operational data or promoting unverified OCR rows into insurance calculation.

**Architecture:** P2 introduces read-only inventory and classification tools, keeps receipt OCR as human-review input unless row-level arithmetic and provenance checks pass, and splits tests with markers so ordinary development does not depend on LLM servers or OCR-heavy jobs. No data deletion or production DB mutation is performed by default.

**Tech Stack:** Python 3.11, pytest markers, JSON reports, existing `src/hospital_receipt_ocr/` package, existing claim calculation tests, shell diagnostics.

---

## Guardrails From `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`

- Deletion of data, indexes, DB files, model files, or user workspaces is a separately approved operation.
- Hospital receipt OCR output is not insurance truth unless row provenance, numeric fields, and arithmetic checks pass.
- LLMs must not fill missing receipt numbers or infer claimable amounts from image context.
- Test defaults must not require DGX model servers, OCR-heavy jobs, or external APIs.
- Sensitive medical and personal information must not appear in logs, reports, committed fixtures, or terminal output.
- When OCR-derived concepts or aliases affect ontology, send them through practitioner approval instead of converting them directly to active knowledge.

## File Structure

- Create: `scripts/audit_runtime_artifacts.py`  
  Read-only inventory of large project artifacts and suggested action categories.
- Create: `tests/test_audit_runtime_artifacts.py`  
  Unit tests for artifact classification without touching real DGX data.
- Modify: `src/hospital_receipt_ocr/claim_adapter.py` or the current claim-export adapter found by `rg "claim_items_ready|export_claim|claimed_amount" src scripts tests`  
  Keep OCR rows as draft claim input unless all required checks pass.
- Modify: `src/hospital_receipt_ocr/validation.py`  
  Ensure row arithmetic, component sum, bbox/source metadata, and redaction checks create human tasks on failure.
- Create: `tests/test_hospital_receipt_claim_promotion.py`  
  Regression tests for verified-row-only claim promotion.
- Modify: `pytest.ini` or `pyproject.toml`  
  Register markers for `unit`, `api`, `rag`, `graph`, `ocr`, `llm`, `dgx`, and `slow`.
- Create: `docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md`  
  Human-readable checklist for storage cleanup approval, OCR operating boundary, and test command selection.

---

## Task 1: Add Read-Only Runtime Artifact Inventory

**Files:**
- Create: `scripts/audit_runtime_artifacts.py`
- Create: `tests/test_audit_runtime_artifacts.py`

- [ ] **Step 1: Write artifact classifier tests**

Create `tests/test_audit_runtime_artifacts.py`:

```python
from __future__ import annotations

from scripts.audit_runtime_artifacts import classify_artifact


def test_operational_index_is_preserved():
    result = classify_artifact("data/index/v2_only/chroma.sqlite3", 10_000)

    assert result.category == "preserve"
    assert result.reason == "operational_index_or_database"


def test_hospital_receipt_runtime_output_is_review_candidate():
    result = classify_artifact("data/hospital_receipts/manual_20260609/runs/opencv_paddle/run_summary.json", 10_000)

    assert result.category == "review"
    assert result.reason == "runtime_experiment_output"


def test_mac_appledouble_file_is_cleanup_candidate():
    result = classify_artifact("data/index/._chunks.jsonl", 4096)

    assert result.category == "cleanup_candidate"
    assert result.reason == "macos_appledouble"


def test_git_pack_requires_separate_project():
    result = classify_artifact(".git/objects/pack/pack-abc.pack", 27 * 1024 * 1024 * 1024)

    assert result.category == "separate_project"
    assert result.reason == "git_history_pack"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
.venv/bin/python -m pytest tests/test_audit_runtime_artifacts.py -q
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the read-only classifier and CLI**

Create `scripts/audit_runtime_artifacts.py`:

```python
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactClassification:
    path: str
    size_bytes: int
    category: str
    reason: str


def classify_artifact(path: str, size_bytes: int) -> ArtifactClassification:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name

    if normalized.startswith(".git/objects/pack/"):
        return ArtifactClassification(path, size_bytes, "separate_project", "git_history_pack")
    if name.startswith("._"):
        return ArtifactClassification(path, size_bytes, "cleanup_candidate", "macos_appledouble")
    if "/__pycache__/" in normalized or normalized.endswith(".pyc"):
        return ArtifactClassification(path, size_bytes, "cleanup_candidate", "python_cache")
    if normalized.startswith("data/index/") or normalized.endswith(".db") or normalized.endswith(".sqlite"):
        return ArtifactClassification(path, size_bytes, "preserve", "operational_index_or_database")
    if normalized.startswith("data/ontology/"):
        return ArtifactClassification(path, size_bytes, "preserve", "ontology_manifest_or_review_log")
    if normalized.startswith("data/hospital_receipts/") and "/runs/" in normalized:
        return ArtifactClassification(path, size_bytes, "review", "runtime_experiment_output")
    if normalized.startswith("reports/") or normalized.startswith("docs/"):
        return ArtifactClassification(path, size_bytes, "review", "project_report_or_document")
    return ArtifactClassification(path, size_bytes, "review", "unclassified_project_artifact")


def iter_artifacts(root: Path) -> list[ArtifactClassification]:
    results: list[ArtifactClassification] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        results.append(classify_artifact(relative, path.stat().st_size))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only runtime artifact inventory")
    parser.add_argument("--root", default=".", help="Project root to inspect")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = iter_artifacts(root)
    payload = {
        "root": str(root),
        "summary": {
            category: sum(item.size_bytes for item in results if item.category == category)
            for category in sorted({item.category for item in results})
        },
        "artifacts": [asdict(item) for item in results],
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run classifier tests and a no-delete inventory smoke**

Run:

```bash
.venv/bin/python -m pytest tests/test_audit_runtime_artifacts.py -q
.venv/bin/python scripts/audit_runtime_artifacts.py --root . --output /tmp/insurance-rag-artifact-audit.json
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/insurance-rag-artifact-audit.json").read_text(encoding="utf-8"))
assert "artifacts" in payload
assert "summary" in payload
print("artifact audit is read-only")
PY
```

Expected:

```text
artifact audit is read-only
```

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/audit_runtime_artifacts.py tests/test_audit_runtime_artifacts.py
git commit -m "feat(ops): add read-only artifact audit"
```

---

## Task 2: Keep Hospital Receipt OCR As Verified Draft Input Only

**Files:**
- Modify: `src/hospital_receipt_ocr/claim_adapter.py`
- Modify: `src/hospital_receipt_ocr/validation.py`
- Test: `tests/test_hospital_receipt_claim_promotion.py`

- [ ] **Step 1: Locate claim item export logic**

Run:

```bash
rg -n "claim_items_ready|claimed_amount|export_claim|validation_report|human_tasks" src scripts tests
```

Expected: The command prints the current OCR claim adapter and validation modules.

- [ ] **Step 2: Write failing verified-only promotion tests**

Create `tests/test_hospital_receipt_claim_promotion.py`:

```python
from __future__ import annotations


def test_verified_row_is_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "row_id": "row-1",
            "item_name": "진찰료",
            "total_amount": 13370,
            "source": {"document_id": "doc-1", "page": 1, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "verified", "issues": []},
        }
    ]

    drafts = build_claim_item_drafts(rows)

    assert drafts == [
        {
            "source_row_id": "row-1",
            "item_name": "진찰료",
            "claimed_amount": 13370,
            "quantity": 1,
            "status": "draft_verified",
        }
    ]


def test_unverified_row_is_not_promoted_to_claim_draft():
    from src.hospital_receipt_ocr.claim_adapter import build_claim_item_drafts

    rows = [
        {
            "row_id": "row-2",
            "item_name": "MRI진단료",
            "total_amount": 490000,
            "source": {"document_id": "doc-1", "page": 2, "bbox": [1, 2, 3, 4]},
            "validation": {"status": "review_required", "issues": ["component_sum_mismatch"]},
        }
    ]

    assert build_claim_item_drafts(rows) == []
```

- [ ] **Step 3: Run the failing promotion tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_hospital_receipt_claim_promotion.py -q
```

Expected: FAIL because the adapter does not exist or does not enforce verified-only promotion.

- [ ] **Step 4: Implement verified-only claim draft adapter**

In `src/hospital_receipt_ocr/claim_adapter.py`, add or adapt:

```python
from __future__ import annotations

from typing import Any


def _has_source_bbox(row: dict[str, Any]) -> bool:
    source = row.get("source") or {}
    bbox = source.get("bbox")
    return bool(source.get("document_id")) and bool(source.get("page")) and isinstance(bbox, list) and len(bbox) == 4


def build_claim_item_drafts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    for row in rows:
        validation = row.get("validation") or {}
        if validation.get("status") != "verified":
            continue
        if not _has_source_bbox(row):
            continue
        amount = row.get("total_amount")
        if not isinstance(amount, int) or amount < 0:
            continue
        drafts.append(
            {
                "source_row_id": row["row_id"],
                "item_name": row.get("item_name", ""),
                "claimed_amount": amount,
                "quantity": 1,
                "status": "draft_verified",
            }
        )
    return drafts
```

This adapter must not apply deductible rules, payout decisions, or item classification knowledge. It only copies verified source-row totals into draft input.

- [ ] **Step 5: Ensure validation failures create human tasks**

In `src/hospital_receipt_ocr/validation.py`, keep or add a function with this contract:

```python
from __future__ import annotations

from typing import Any


def build_human_task(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source_row_id": row.get("row_id"),
        "reason": reason,
        "status": "review_required",
        "message": "OCR row requires human review before claim calculation input.",
    }
```

Wire existing validation failures such as `row_arithmetic_mismatch`, `component_sum_mismatch`, `missing_bbox`, and `ocr_uncertain_text` to this task shape.

- [ ] **Step 6: Run OCR claim adapter tests and existing claim pipeline tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_hospital_receipt_claim_promotion.py \
  tests/test_claim_calculation_pipeline.py \
  -q
```

Expected: PASS. Claim calculation tests must not depend on hospital OCR rows being auto-promoted.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/hospital_receipt_ocr/claim_adapter.py src/hospital_receipt_ocr/validation.py tests/test_hospital_receipt_claim_promotion.py
git commit -m "fix(ocr): require verified rows for claim drafts"
```

---

## Task 3: Register Test Markers And Separate Heavy Runtime Checks

**Files:**
- Modify: `pytest.ini` or `pyproject.toml`
- Modify: selected OCR/LLM/DGX tests to add markers, only where the marker matches an existing dependency

- [ ] **Step 1: Find the current pytest configuration**

Run:

```bash
find . -maxdepth 2 \( -name "pytest.ini" -o -name "pyproject.toml" -o -name "setup.cfg" \) -print
rg -n "pytestmark|@pytest.mark|llm|dgx|ocr|slow|vllm|sglang|paddle|surya" tests
```

Expected: The command identifies the config file and tests that touch heavy dependencies.

- [ ] **Step 2: Add marker declarations**

If `pytest.ini` exists, add:

```ini
[pytest]
markers =
    unit: pure unit tests without external services
    api: FastAPI route and request/response tests
    rag: retrieval and source-grounded answer tests
    graph: GraphRAG and ontology graph tests
    ocr: OCR pipeline tests
    llm: tests requiring a local or remote LLM endpoint
    dgx: DGX runtime smoke tests
    slow: tests expected to run longer than ordinary development tests
```

If pytest options live in `pyproject.toml`, add the equivalent:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: pure unit tests without external services",
  "api: FastAPI route and request/response tests",
  "rag: retrieval and source-grounded answer tests",
  "graph: GraphRAG and ontology graph tests",
  "ocr: OCR pipeline tests",
  "llm: tests requiring a local or remote LLM endpoint",
  "dgx: DGX runtime smoke tests",
  "slow: tests expected to run longer than ordinary development tests",
]
```

- [ ] **Step 3: Mark existing heavy tests**

For each test file identified in Step 1:

```python
import pytest

pytestmark = [pytest.mark.ocr, pytest.mark.slow]
```

Use these mappings:

- OCR image/table extraction tests: `pytest.mark.ocr`
- OCR real-sample tests: `pytest.mark.ocr` and `pytest.mark.slow`
- LLM endpoint smoke tests: `pytest.mark.llm` and `pytest.mark.slow`
- DGX launcher tests: `pytest.mark.dgx` and `pytest.mark.slow`

Do not mark ordinary mocked OCR unit tests as slow.

- [ ] **Step 4: Verify marker registration**

Run:

```bash
.venv/bin/python -m pytest --markers | rg "unit:|api:|rag:|graph:|ocr:|llm:|dgx:|slow:"
```

Expected: All eight marker descriptions are printed.

- [ ] **Step 5: Verify default tests still run without external services**

Run:

```bash
.venv/bin/python -m pytest -m "not llm and not dgx and not slow" -q
```

Expected: PASS. If a test fails because it still requires a model server or OCR binary, mark that specific test with the matching marker and rerun.

- [ ] **Step 6: Commit Task 3**

```bash
git add pytest.ini pyproject.toml tests
git commit -m "test: mark heavy runtime test groups"
```

---

## Task 4: Document P2 Operating Boundaries

**Files:**
- Create: `docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md`

- [ ] **Step 1: Create the checklist document**

Create `docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md`:

```markdown
# 247. P2 Data, OCR, And Test Operation Checklist

작성일: 2026-06-17

## 1. Storage Cleanup Boundary

- This phase provides read-only inventory only.
- Deleting data, indexes, DB files, model files, or workspace archives requires a separate explicit approval.
- Operational indexes, ontology manifests, review logs, approved rule tables, and active DB files are preserve targets.
- `.git` pack size reduction is a separate history-maintenance project.

## 2. Hospital Receipt OCR Boundary

- A-D on-device OCR outputs are not sufficient by themselves for automatic insurance benefit calculation.
- Verified OCR rows may become claim input drafts only when row provenance, bbox, arithmetic, and amount checks pass.
- Failed or uncertain rows become human tasks.
- The UI wording should be "input draft" or "review helper", not "automatic claim calculation complete".

## 3. Ontology And Rule Knowledge Boundary

- OCR-derived terms, aliases, relation candidates, and rule candidates start as pending candidates.
- Practitioner approval is preferred over silent policy-file promotion when a candidate could affect insurance knowledge.
- Source evidence and approval status must be visible before active ontology or rule table application.

## 4. Test Command Groups

Default local check:

```bash
.venv/bin/python -m pytest -m "not llm and not dgx and not slow" -q
```

Full ordinary suite:

```bash
.venv/bin/python -m pytest -q
```

OCR-specific check:

```bash
.venv/bin/python -m pytest -m "ocr" -q
```

DGX runtime smoke:

```bash
.venv/bin/python -m pytest -m "dgx" -q
```

## 5. Completion Criteria

- Artifact inventory runs without deleting files.
- OCR claim drafts contain only verified source rows.
- Heavy runtime tests are opt-in by marker.
- Sensitive data is masked in generated reports and logs.
```

- [ ] **Step 2: Check document for scope drift**

Run:

```bash
rg -n "delete|rm -rf|automatic claim calculation complete|확정 지급|PLACEHOLDER_TOKEN" docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md
```

Expected: No destructive command appears. The only acceptable occurrence of “delete” is the explanatory sentence saying deletion requires separate approval.

- [ ] **Step 3: Commit Task 4**

```bash
git add docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md
git commit -m "docs(p2): define data ocr test boundaries"
```

---

## Task 5: P2 Integrated Verification And Self-Inspection

**Files:**
- Review: all files changed in Tasks 1-4

- [ ] **Step 1: Run focused P2 tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_audit_runtime_artifacts.py \
  tests/test_hospital_receipt_claim_promotion.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run marker verification**

Run:

```bash
.venv/bin/python -m pytest --markers | rg "ocr:|llm:|dgx:|slow:"
```

Expected: Marker descriptions are printed.

- [ ] **Step 3: Run default non-heavy suite**

Run:

```bash
.venv/bin/python -m pytest -m "not llm and not dgx and not slow" -q
```

Expected: PASS.

- [ ] **Step 4: Run full suite if current DGX resource use allows it**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. If current DGX team workloads make OCR/LLM-heavy tests inappropriate, record that only the non-heavy suite was executed.

- [ ] **Step 5: Search for P2 guardrail violations**

Run:

```bash
rg -n "claimed_amount|quantity|자동 계산|확정 지급|source_row_id|review_required|practitioner" src scripts tests docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md
```

Expected:

- `claimed_amount` is copied only from verified source rows.
- `quantity=1` remains an adapter convention for draft rows, not a coverage or payout rule.
- OCR failure paths create `review_required` human tasks.
- Practitioner approval is the path for OCR-derived ontology/rule candidates.

- [ ] **Step 6: Write the P2 self-inspection note**

Add this to the completion report or final response:

```markdown
### P2 Self-Inspection

- Deletion safety: artifact audit is read-only and produces JSON inventory only.
- OCR boundary: hospital receipt rows are review helpers unless verified by row-level checks.
- Insurance knowledge: OCR-derived knowledge is not promoted without practitioner approval.
- Test stability: default tests exclude LLM, DGX, and slow runtime dependencies.
- Remaining risk: this phase does not solve OCR accuracy; it prevents inaccurate OCR from becoming automatic calculation input.
```

- [ ] **Step 7: Commit Task 5 if a repository report was updated**

```bash
git add docs
git commit -m "docs(p2): record data ocr test verification"
```
