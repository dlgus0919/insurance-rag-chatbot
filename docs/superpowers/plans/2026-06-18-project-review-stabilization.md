# Project Review Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the post-P0~P2 review artifacts and make runtime artifact auditing usable without changing insurance knowledge logic.

**Architecture:** Keep this as a documentation and tooling patch. Do not touch active LLM processes, Streamlit legacy code, raw data, indexes, or ontology manifests. The only code behavior change is a CLI output mode for an existing read-only audit script.

**Tech Stack:** Python 3.12, argparse, pytest, Markdown documentation.

---

## Task 1: Record Post-P0~P2 Findings

**Files:**
- Modify: `docs/246_PROJECT_FULL_LOGIC_REVIEW_NEXT_PHASE_REPORT.md`
- Create: `docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md`
- Include: `docs/superpowers/plans/2026-06-17-p0-source-grounded-knowledge-removal.md`
- Include: `docs/superpowers/plans/2026-06-17-p1-runtime-operations-alignment.md`
- Include: `docs/superpowers/plans/2026-06-17-p2-data-ocr-test-operations.md`

- [x] **Step 1: Mark 246 as a baseline record**

Add this note immediately under the title:

```markdown
> 상태: P0~P2 수행 전 기준의 선행 검토 기록이다. P0~P2 수행 후 최신 원점 재검토와 남은 작업은 `docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md`를 우선한다.
```

- [x] **Step 2: Add the current findings report**

Create `docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md` with sections:

```markdown
# 250. P0~P2 이후 프로젝트 로직 원점 재검토 결과

## 1. 검토 기준
## 2. 확인 결과
## 3. 이번 작업 범위
## 4. 보류한 항목
## 5. 결론
```

The report must state that tracked raw PDF/XLSX, secrets, venv, and generated indexes were not found, and that `scripts/audit_runtime_artifacts.py` needs a concise output mode.

- [x] **Step 3: Verify documentation files are staged intentionally**

Run:

```bash
git status --short docs/246_PROJECT_FULL_LOGIC_REVIEW_NEXT_PHASE_REPORT.md docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md docs/superpowers
```

Expected: only these documentation files are shown.

## Task 2: Add Concise Runtime Artifact Audit Output

**Files:**
- Modify: `scripts/audit_runtime_artifacts.py`
- Modify: `tests/test_audit_runtime_artifacts.py`

- [x] **Step 1: Write the failing test**

Add:

```python
def test_cli_summary_only_omits_artifact_list(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "note.md").write_text("review note", encoding="utf-8")

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "audit_runtime_artifacts.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--root", str(tmp_path), "--summary-only"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["summary"]["review"] == len("review note")
    assert "artifacts" not in payload
```

- [x] **Step 2: Run RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_audit_runtime_artifacts.py::test_cli_summary_only_omits_artifact_list -q
```

Expected: fail with `unrecognized arguments: --summary-only`.

- [x] **Step 3: Implement minimal CLI option**

In `scripts/audit_runtime_artifacts.py`, add:

```python
parser.add_argument(
    "--summary-only",
    action="store_true",
    help="Omit per-file artifacts from the JSON payload",
)
```

Then only attach `payload["artifacts"]` when `not args.summary_only`.

- [x] **Step 4: Run GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_audit_runtime_artifacts.py -q
```

Expected: all audit artifact tests pass.

## Task 3: Verify and Publish

**Files:**
- All files changed by Tasks 1 and 2.

- [x] **Step 1: Run focused verification**

```bash
.venv/bin/python scripts/audit_runtime_artifacts.py --summary-only > /tmp/runtime_artifacts_summary.json
.venv/bin/python -m pytest tests/test_audit_runtime_artifacts.py -q
```

- [x] **Step 2: Run project verification**

```bash
.venv/bin/python -m pytest -q
```

- [x] **Step 3: Commit and push intentionally**

```bash
git add docs/246_PROJECT_FULL_LOGIC_REVIEW_NEXT_PHASE_REPORT.md docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md docs/superpowers/plans/2026-06-17-p0-source-grounded-knowledge-removal.md docs/superpowers/plans/2026-06-17-p1-runtime-operations-alignment.md docs/superpowers/plans/2026-06-17-p2-data-ocr-test-operations.md docs/superpowers/plans/2026-06-18-project-review-stabilization.md scripts/audit_runtime_artifacts.py tests/test_audit_runtime_artifacts.py
git commit -m "chore(project): stabilize post p0 p2 review artifacts"
git push origin master
```
