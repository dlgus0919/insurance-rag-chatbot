# Knowledge Intake Extension Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make administrator document intake, candidate review, and approved-knowledge application actually connect without silently dropping generated candidates.

**Architecture:** Keep the current two-step extension model: uploaded source files produce pending candidates, and only practitioner-approved candidates can affect active ontology/rule assets. Job-local artifacts remain audit/debug evidence, while the global review stores remain the single source of truth for approval UI and apply operations.

**Tech Stack:** FastAPI, JSONL review stores, existing ontology/rule candidate extractors, static SPA admin frontend, pytest, Node test runner.

---

## Scope

This plan fixes extension-flow correctness. It does not implement scanned-PDF OCR automation, Excel staging, or full vector/BM25 reindexing.

The work is split into three phases:

- **P0:** Fix broken admin audit endpoint and publish digital-PDF-generated candidates into the existing global review stores.
- **P1:** Add apply preflight so approved knowledge does not partially mutate active assets before a predictable validation failure.
- **P2:** Design and implement active source/index promotion for newly uploaded document text.

P0 is the immediate patch. P1 and P2 are intentionally separate because P2 touches source manifests and search indexes.

## Files

- Modify: `frontend/js/config.js`
  - Add the missing admin intake audit base endpoint.
- Modify: `tests/test_admin_knowledge_frontend.mjs`
  - Assert the audit helper builds a valid URL instead of using `undefined`.
- Modify: `src/ingest/intake_runner.py`
  - Load active ontology if present.
  - Write job-local candidates as before.
  - Publish pending candidates into the global ontology/rule review stores with intake provenance metadata.
  - Record publish counts and skipped duplicate counts in job details/audit.
- Modify: `tests/test_intake_runner.py`
  - Assert digital PDF jobs publish candidates into injected global review stores.
  - Assert duplicate candidates are skipped rather than duplicated.
- Modify: `src/api/routes/knowledge.py`
  - Keep global candidate list endpoints unchanged, because they are the intended review UI source.
  - Do not add a new P0 route; existing job responses already include publish counts in `details`.
- Modify: `src/ingest/file_intake_planner.py`
  - Align Excel plan with current runtime: Excel is accepted for upload classification but not candidate generation until staging is implemented.
- Modify: `frontend/html/admin.html` and/or `frontend/js/pages/admin.js`
  - Make administrator copy honest: digital PDF candidate generation is supported; Excel staging is not yet connected.
- Modify: `tests/test_file_intake_planner.py`
  - Align expected Excel plan with current blocked behavior.
- Modify: `src/ingest/knowledge_apply.py`
  - P1 only: add dry-run preflight before mutation.
- Modify: `tests/test_knowledge_apply.py`
  - P1 only: assert preflight failure stops before mutation.

## P0 Detailed Tasks

### Task 1: Fix Admin Intake Audit Endpoint

**Files:**
- Modify: `frontend/js/config.js`
- Modify: `tests/test_admin_knowledge_frontend.mjs`

- [ ] **Step 1: Write the failing frontend endpoint test**

Add this test to `tests/test_admin_knowledge_frontend.mjs`:

```js
test('admin config defines knowledge intake audit endpoint base', async () => {
  const { API_CONFIG } = await import('../frontend/js/config.js');

  assert.equal(
    API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE,
    '/admin/knowledge/intake/jobs'
  );
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: FAIL because `ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE` is undefined.

- [ ] **Step 3: Add the missing endpoint constant**

In `frontend/js/config.js`, extend `API_CONFIG.ENDPOINTS`:

```js
    ADMIN_KNOWLEDGE_INTAKE_JOBS: '/admin/knowledge/intake/jobs',
    ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE: '/admin/knowledge/intake/jobs',
    ADMIN_KNOWLEDGE_APPLY_APPROVED: '/admin/knowledge/apply-approved',
```

- [ ] **Step 4: Run the frontend test**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: PASS.

### Task 2: Publish Intake Candidates Into Global Review Stores

**Files:**
- Modify: `src/ingest/intake_runner.py`
- Modify: `tests/test_intake_runner.py`

- [ ] **Step 1: Write a failing intake publication test**

Add a test that injects temporary global review paths and asserts candidates generated from a digital PDF become visible in those paths.

Use this shape in `tests/test_intake_runner.py`:

```python
def test_runner_publishes_generated_candidates_to_global_review_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntakeJobStore(tmp_path / "jobs")
    job = store.create_job(original_filename="digital.pdf", uploaded_by="admin", document_kind="pdf")
    source = store.job_dir(job.job_id) / "source" / "digital.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    store.update_job(job.job_id, status=IntakeJobStatus.UPLOADED, message="uploaded", source_path=str(source))

    ontology_global = tmp_path / "ontology" / "candidates.jsonl"
    rule_global = tmp_path / "rules" / "candidates.jsonl"
    monkeypatch.setattr("src.ingest.intake_runner.GLOBAL_ONTOLOGY_CANDIDATES_PATH", ontology_global)
    monkeypatch.setattr("src.ingest.intake_runner.GLOBAL_RULE_CANDIDATES_PATH", rule_global)
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
    monkeypatch.setattr(
        "src.ingest.intake_runner._write_candidate_outputs",
        lambda job_dir, _chunks_path, job_id: _write_fake_job_candidates(job_dir, job_id),
    )

    result = run_intake_job_once(store, job.job_id)

    assert result.status == IntakeJobStatus.WAITING_REVIEW
    ontology_rows = [json.loads(line) for line in ontology_global.read_text(encoding="utf-8").splitlines()]
    rule_rows = [json.loads(line) for line in rule_global.read_text(encoding="utf-8").splitlines()]
    assert ontology_rows[0]["properties"]["intake_job_id"] == job.job_id
    assert rule_rows[0]["intake_job_id"] == job.job_id
    assert result.details["published_ontology_candidate_count"] == 1
    assert result.details["published_rule_candidate_count"] == 1
```

Add a local helper in the test file:

```python
def _write_fake_job_candidates(job_dir: Path, job_id: str) -> dict[str, object]:
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    ontology_path = review_dir / "ontology_candidates.jsonl"
    rule_path = review_dir / "rule_candidates.jsonl"
    ontology_path.write_text(
        json.dumps(
            {
                "candidate_id": f"dev.cov.demo.{job_id[-8:]}",
                "concept_id": "cov.demo",
                "canonical_name": "테스트 보장",
                "status": "pending",
                "properties": {},
                "source_evidence": [{"chunk_id": "chunk:demo"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rule_path.write_text(
        json.dumps(
            {
                "candidate_id": f"rulecand.demo.{job_id[-8:]}",
                "status": "pending",
                "rule_type": "deductible",
                "proposed_rule": {"rule_id": f"rule.demo.{job_id[-8:]}"},
                "proposed_links": {"rule_id": f"rule.demo.{job_id[-8:]}"},
                "source_refs": [{"chunk_id": "chunk:demo"}],
                "evidence_text": "4세대 급여 통원 80% 보상",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "ontology_candidates_path": str(ontology_path),
        "rule_candidates_path": str(rule_path),
        "ontology_candidate_count": 1,
        "rule_candidate_count": 1,
        "ontology_warnings": [],
    }
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py::test_runner_publishes_generated_candidates_to_global_review_stores -q
```

Expected: FAIL because `GLOBAL_ONTOLOGY_CANDIDATES_PATH` and publication logic do not exist.

- [ ] **Step 3: Add global review-store path constants**

In `src/ingest/intake_runner.py`, add imports and constants:

```python
from src import config
from src.claim_calculation.rule_candidates import load_jsonl
from src.ontology.registry import ACTIVE_ONTOLOGY_MANIFEST, BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import OntologyCandidate, OntologyReviewStore

GLOBAL_ONTOLOGY_CANDIDATES_PATH = config.ROOT_DIR / "data" / "ontology" / "review" / "candidates.jsonl"
GLOBAL_RULE_CANDIDATES_PATH = config.ROOT_DIR / "data" / "rules" / "review" / "candidates.jsonl"
```

Replace the existing `BASE_ONTOLOGY_MANIFEST` import line accordingly.

- [ ] **Step 4: Add active-manifest resolution**

In `src/ingest/intake_runner.py`, add:

```python
def _candidate_extraction_manifest() -> Path:
    if ACTIVE_ONTOLOGY_MANIFEST.exists():
        return ACTIVE_ONTOLOGY_MANIFEST
    return BASE_ONTOLOGY_MANIFEST
```

Change:

```python
concepts = load_manifest_concepts(str(BASE_ONTOLOGY_MANIFEST))
```

to:

```python
concepts = load_manifest_concepts(str(_candidate_extraction_manifest()))
```

- [ ] **Step 5: Add publication helpers**

In `src/ingest/intake_runner.py`, add:

```python
def _publish_candidate_outputs(job: IntakeJob, candidate_details: dict[str, Any]) -> dict[str, Any]:
    ontology_result = _publish_ontology_candidates(job, Path(str(candidate_details["ontology_candidates_path"])))
    rule_result = _publish_rule_candidates(job, Path(str(candidate_details["rule_candidates_path"])))
    return {
        "published_ontology_candidate_count": ontology_result["published"],
        "skipped_ontology_candidate_count": ontology_result["skipped"],
        "published_rule_candidate_count": rule_result["published"],
        "skipped_rule_candidate_count": rule_result["skipped"],
        "global_ontology_candidates_path": str(GLOBAL_ONTOLOGY_CANDIDATES_PATH),
        "global_rule_candidates_path": str(GLOBAL_RULE_CANDIDATES_PATH),
    }


def _publish_ontology_candidates(job: IntakeJob, path: Path) -> dict[str, int]:
    store = OntologyReviewStore(candidates_path=GLOBAL_ONTOLOGY_CANDIDATES_PATH)
    existing_ids = {candidate.candidate_id for candidate in store.load_candidates()}
    published = 0
    skipped = 0
    for row in _read_jsonl_dicts(path):
        candidate = OntologyCandidate.from_dict(row)
        if candidate.candidate_id in existing_ids:
            skipped += 1
            continue
        candidate.properties = dict(candidate.properties)
        candidate.properties.setdefault("intake_job_id", job.job_id)
        candidate.properties.setdefault("source_filename", job.original_filename)
        if job.staging_chunks_path:
            candidate.properties.setdefault("staging_chunks_path", job.staging_chunks_path)
        store.add_candidate(candidate)
        existing_ids.add(candidate.candidate_id)
        published += 1
    return {"published": published, "skipped": skipped}


def _publish_rule_candidates(job: IntakeJob, path: Path) -> dict[str, int]:
    existing = load_jsonl(GLOBAL_RULE_CANDIDATES_PATH)
    existing_ids = {str(row.get("candidate_id")) for row in existing if row.get("candidate_id")}
    new_rows = []
    skipped = 0
    for row in _read_jsonl_dicts(path):
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id in existing_ids:
            skipped += 1
            continue
        row = dict(row)
        row.setdefault("intake_job_id", job.job_id)
        row.setdefault("source_filename", job.original_filename)
        if job.staging_chunks_path:
            row.setdefault("staging_chunks_path", job.staging_chunks_path)
        new_rows.append(row)
        existing_ids.add(candidate_id)
    if new_rows:
        write_jsonl(GLOBAL_RULE_CANDIDATES_PATH, [*existing, *new_rows])
    return {"published": len(new_rows), "skipped": skipped}


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows
```

- [ ] **Step 6: Call publication from the PDF runner**

In `_run_pdf_job`, after candidate generation succeeds:

```python
        candidate_details = _write_candidate_outputs(store.job_dir(job.job_id), chunks_path, job.job_id)
        job = store.load_job(job.job_id)
        job.staging_chunks_path = str(chunks_path)
        publish_details = _publish_candidate_outputs(job, candidate_details)
        candidate_details.update(publish_details)
```

Then return the existing `WAITING_REVIEW` update with the expanded details.

If direct mutation of `job.staging_chunks_path` feels too brittle, pass `staging_chunks_path` explicitly to the helper instead.

- [ ] **Step 7: Run intake tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_intake_runner.py -q
```

Expected: PASS.

### Task 3: Make Excel Intake Status Honest

**Files:**
- Modify: `src/ingest/file_intake_planner.py`
- Modify: `tests/test_file_intake_planner.py`
- Modify: `frontend/html/admin.html`

- [ ] **Step 1: Update Excel planner expectation**

In `tests/test_file_intake_planner.py`, update the Excel test to expect no candidate steps:

```python
def test_plan_file_intake_excel_is_blocked_until_staging_ready() -> None:
    plan = plan_file_intake("rules.xlsx")

    assert plan.file_type == "excel"
    assert plan.steps == ["excel_staging_not_ready"]
    assert plan.mutates_indexes is False
    assert plan.requires_practitioner_approval is False
```

- [ ] **Step 2: Update planner**

In `src/ingest/file_intake_planner.py`, change the Excel branch to:

```python
    if suffix in EXCEL_SUFFIXES:
        return IntakePlan(
            path=str(source_path),
            file_type="excel",
            steps=["excel_staging_not_ready"],
            mutates_indexes=False,
            requires_practitioner_approval=False,
        )
```

- [ ] **Step 3: Update admin copy**

In `frontend/html/admin.html`, replace user-facing copy that says Excel candidate extraction proceeds with:

```html
디지털 PDF는 후보 추출을 진행합니다. Excel 문서는 업로드 기록만 가능하며, 구조화 staging 연결 전에는 후보 추출을 진행하지 않습니다.
```

- [ ] **Step 4: Run related tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_file_intake_planner.py tests/test_intake_runner.py -q
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: PASS.

## P1 Detailed Tasks

### Task 4: Add Apply Preflight Before Mutation

**Files:**
- Modify: `src/ingest/knowledge_apply.py`
- Modify: `tests/test_knowledge_apply.py`

- [ ] **Step 1: Write preflight ordering test**

Add:

```python
def test_apply_approved_knowledge_runs_preflight_before_mutation(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda dry_run=False: calls.append(f"ontology:{dry_run}") or {"merged_candidate_count": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda dry_run=False: calls.append(f"rules:{dry_run}") or {"applied_candidate_ids": ["rulecand.demo"]},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "completed"
    assert calls == ["ontology:True", "rules:True", "ontology:False", "rules:False", "graph"]
```

- [ ] **Step 2: Write preflight-failure test**

Add:

```python
def test_apply_approved_knowledge_stops_when_rule_preflight_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda dry_run=False: calls.append(f"ontology:{dry_run}") or {"merged_candidate_count": 1},
    )

    def fail_rules(dry_run=False):
        calls.append(f"rules:{dry_run}")
        raise ValueError("duplicate rule_id: demo")

    monkeypatch.setattr("src.ingest.knowledge_apply.apply_rule_candidates", fail_rules)
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "failed_preflight"
    assert "duplicate rule_id" in result.rules["error"]
    assert calls == ["ontology:True", "rules:True"]
```

- [ ] **Step 3: Change helper signatures**

In `src/ingest/knowledge_apply.py`, change:

```python
def apply_ontology_reviews() -> dict[str, Any]:
```

to:

```python
def apply_ontology_reviews(*, dry_run: bool = False) -> dict[str, Any]:
```

Pass `dry_run=dry_run` into `apply_reviews`.

Change:

```python
def apply_rule_candidates() -> dict[str, Any]:
```

to:

```python
def apply_rule_candidates(*, dry_run: bool = False) -> dict[str, Any]:
```

Pass `dry_run=dry_run` into `apply_candidates`.

- [ ] **Step 4: Implement preflight in `apply_approved_knowledge`**

Use:

```python
def apply_approved_knowledge() -> KnowledgeApplyResult:
    try:
        ontology_preflight = apply_ontology_reviews(dry_run=True)
        rules_preflight = apply_rule_candidates(dry_run=True)
    except Exception as exc:
        return KnowledgeApplyResult(
            status="failed_preflight",
            ontology=locals().get("ontology_preflight", {}),
            rules={"error": str(exc), "error_type": type(exc).__name__},
            graph_rebuilt=False,
        )

    ontology = apply_ontology_reviews(dry_run=False)
    rules = apply_rule_candidates(dry_run=False)
    rebuild_graph()
    return KnowledgeApplyResult(
        status="completed",
        ontology=ontology,
        rules=rules,
        graph_rebuilt=True,
    )
```

If ontology preflight returns a skipped result because no approved ontology candidates exist, keep that as non-fatal so rule-only apply remains possible.

- [ ] **Step 5: Run apply tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_apply.py -q
```

Expected: PASS.

## P2 Detailed Tasks

### Task 5: Source Promotion Design Gate

**Files:**
- Create: `docs/superpowers/plans/2026-07-02-intake-source-index-promotion.md`

- [ ] **Step 1: Confirm current source/index contracts**

Read:

```bash
sed -n '1,140p' scripts/build_index_from_canonical_manifest.py
sed -n '1,120p' scripts/build_cloud_index.py
sed -n '130,180p' src/config.py
rg -n "canonical|manifest|chunks.jsonl|processed" scripts src docs | head -n 80
```

- [ ] **Step 2: Define active-source promotion target**

The design must name the actual durable target for uploaded document chunks. It must not silently append to `data/processed/chunks.jsonl` unless that is confirmed as the canonical source for the current runtime.

- [ ] **Step 3: Define reindex command**

The design must specify the exact command used after promotion. Candidate commands to evaluate:

```bash
.venv/bin/python scripts/build_index_from_canonical_manifest.py --index-mode v2_only
.venv/bin/python scripts/build_graph_index.py --rebuild
```

If neither candidate command matches the current repo CLI, stop and revise the P2 plan before implementation.

- [ ] **Step 4: Add source-presence preflight**

Before applying candidates created from an intake job, verify that each candidate's `staging_chunks_path` or source evidence has been promoted to active source storage. If not, return a failed preflight with a human-readable next action.

## Verification Matrix

Run on DGX before reporting ready:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_knowledge_apply.py tests/test_document_intake_detector.py tests/test_file_intake_planner.py -q && node --test tests/test_admin_knowledge_frontend.mjs'
```

Expected:

- Python tests pass.
- Node tests pass.
- No LLM server start/stop.
- No active DB/index rebuild during P0 unit tests.

## Self-Review Checklist

- P0 does not promote unapproved knowledge into active ontology/rules.
- P0 makes generated candidates visible to the same review endpoints the admin UI already uses.
- P0 does not claim uploaded document text is active searchable data.
- Excel behavior is honest and blocked until staging is implemented.
- P1 preflight reduces partial mutation risk without introducing a large transaction framework.
- P2 remains a separate source/index promotion design because it touches broader retrieval assets.
