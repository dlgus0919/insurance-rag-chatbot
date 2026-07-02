# Muldae Cold Workspace Knowledge Extension Test Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DGX 메인 저장소의 `v1.0.16` 확장 로직을 `muldae` 독립 워크스페이스에서 cold 상태로 검증한다. 검증 범위는 관리자 문서 추가, 스캔 PDF 차단, 디지털 PDF 후보 생성, 후보 목록 노출, 승인 대기 상태, 적용 전 안전성 확인까지다.

**Architecture:** `/srv/shared/projects/insurance-rag-chatbot`는 source-of-truth master로 유지하고, `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test`를 격리된 실행 대상로 사용한다. 런타임 산출물은 muldae 워크스페이스의 `data/`와 `reports/` 아래에만 생성하며, DGX 메인 DB와 active ontology/rule manifest를 직접 변경하지 않는다.

**Tech Stack:** FastAPI 정적 SPA, 관리자 knowledge API, pytest, Node test runner, PyMuPDF 기반 테스트 PDF 생성, curl cookie 인증, git, DGX SSH.

---

## File Structure

### Read Existing Files
- `/srv/shared/projects/insurance-rag-chatbot/docs/261_MULDAE_COLD_WORKSPACE_TEST_SETUP.md`
- `/srv/shared/projects/insurance-rag-chatbot/docs/262_MULDAE_COLD_WORKSPACE_KNOWLEDGE_EXTENSION_TEST_SPEC.md`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/src/ingest/document_intake.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/src/ingest/intake_runner.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/src/api/routes/knowledge.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/frontend/js/admin.js`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_file_intake_planner.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_intake_runner.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_source_promotion.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_knowledge_apply.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_api_admin_knowledge.py`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/tests/test_admin_knowledge_frontend.mjs`

### Runtime Files To Create In Muldae Workspace Only
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/data/intake_test_samples/digital_text_layer.pdf`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/data/intake_test_samples/no_text_layer.pdf`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/data/muldae_cold_test/users.json`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/data/muldae_cold_test/insurance_chat.db`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/reports/muldae_cold_workspace/<RUN_ID>/run_summary.md`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/reports/muldae_cold_workspace/<RUN_ID>/uvicorn.log`
- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/reports/muldae_cold_workspace/<RUN_ID>/validation.json`

---

## Task 1: Verify Repository Alignment And Cold Starting State

- [ ] Step 1: Confirm DGX source-of-truth master is clean and still points at `v1.0.16`.

  ```bash
  ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && git fetch origin master --tags && git status --short --branch && git rev-parse --short HEAD && git tag --points-at HEAD'
  ```

  Expected output:

  ```text
  ## master...origin/master
  f6390b9
  v1.0.16
  ```

- [ ] Step 2: Fast-forward the `muldae` cold workspace to the same commit.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && git fetch origin master --tags && git pull --ff-only origin master && git status --short --branch && git rev-parse --short HEAD && rg -n "VERSION:" frontend/js/config.js'
  ```

  Expected output:

  ```text
  ## master...origin/master
  f6390b9
  72:  VERSION: '1.0.16',
  ```

- [ ] Step 3: Confirm the cold-test runtime artifacts are absent or intentionally isolated before testing.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && for p in data/intake/jobs data/ontology/review/candidates.jsonl data/rules/review/candidates.jsonl data/ontology/concepts.active.json data/rules/active_rule_manifest.json data/muldae_cold_test/insurance_chat.db; do if [ -e "$p" ]; then echo "PRESENT $p"; else echo "MISSING $p"; fi; done'
  ```

  Expected output for a fully cold workspace:

  ```text
  MISSING data/intake/jobs
  MISSING data/ontology/review/candidates.jsonl
  MISSING data/rules/review/candidates.jsonl
  MISSING data/ontology/concepts.active.json
  MISSING data/rules/active_rule_manifest.json
  MISSING data/muldae_cold_test/insurance_chat.db
  ```

  If any path is `PRESENT`, do not delete it immediately. Record the path in the run report and continue only if it is clearly a prior cold-test artifact, not DGX main data.

---

## Task 2: Run Static And Unit-Level Regression Tests

- [ ] Step 1: Run the knowledge extension Python test subset in the `muldae` workspace.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest tests/test_file_intake_planner.py tests/test_intake_runner.py tests/test_source_promotion.py tests/test_knowledge_apply.py tests/test_api_admin_knowledge.py -q'
  ```

  Expected result:

  ```text
  27 passed
  ```

  A warning count is acceptable if all selected tests pass.

- [ ] Step 2: Run the administrator knowledge frontend behavior test.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && node --test tests/test_admin_knowledge_frontend.mjs'
  ```

  Expected result:

  ```text
  tests 10
  pass 10
  fail 0
  ```

  Node `MODULE_TYPELESS_PACKAGE_JSON` warnings are acceptable because they do not change the test result.

- [ ] Step 3: Compile the changed Python modules to catch syntax/import boundary errors.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m py_compile src/ingest/document_intake.py src/ingest/intake_runner.py src/ingest/knowledge_apply.py src/api/routes/knowledge.py src/api/schemas/knowledge.py'
  ```

  Expected result: command exits with code `0` and prints no syntax error.

---

## Task 3: Generate Isolated Test Input Files

- [ ] Step 1: Create one digital PDF with a text layer and one no-text PDF that simulates a scanned document.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && mkdir -p data/intake_test_samples && /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python - <<'"'"'PY'"'"'
  from pathlib import Path
  import fitz

  out = Path("data/intake_test_samples")
  out.mkdir(parents=True, exist_ok=True)

  digital = fitz.open()
  page = digital.new_page()
  page.insert_text(
      (72, 72),
      "신한EZ 테스트 약관\n제1조 보험금 지급\n디지털 PDF 텍스트 레이어 검증용 문서입니다.\n"
      "본 문서는 관리자 문서 추가 테스트를 위한 비운영 샘플입니다.",
      fontsize=12,
  )
  digital.save(out / "digital_text_layer.pdf")
  digital.close()

  scanned = fitz.open()
  page = scanned.new_page()
  page.draw_rect(fitz.Rect(72, 72, 420, 180), color=(0, 0, 0), width=1)
  page.draw_line(fitz.Point(72, 120), fitz.Point(420, 120), color=(0, 0, 0), width=1)
  page.draw_line(fitz.Point(180, 72), fitz.Point(180, 180), color=(0, 0, 0), width=1)
  scanned.save(out / "no_text_layer.pdf")
  scanned.close()

  print(out / "digital_text_layer.pdf")
  print(out / "no_text_layer.pdf")
  PY'
  ```

  Expected output:

  ```text
  data/intake_test_samples/digital_text_layer.pdf
  data/intake_test_samples/no_text_layer.pdf
  ```

- [ ] Step 2: Verify the generated text-layer properties before using the files.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python - <<'"'"'PY'"'"'
  import fitz
  for path in ("data/intake_test_samples/digital_text_layer.pdf", "data/intake_test_samples/no_text_layer.pdf"):
      doc = fitz.open(path)
      text = "\n".join(page.get_text().strip() for page in doc)
      print(f"{path}: text_chars={len(text.strip())}")
  PY'
  ```

  Expected output:

  ```text
  data/intake_test_samples/digital_text_layer.pdf: text_chars=<positive integer>
  data/intake_test_samples/no_text_layer.pdf: text_chars=0
  ```

---

## Task 4: Start An Isolated Admin Runtime

- [ ] Step 1: Create an isolated test administrator account file. This is a test-only credential inside `data/muldae_cold_test/users.json`.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && mkdir -p data/muldae_cold_test && USERS_JSON_PATH="$PWD/data/muldae_cold_test/users.json" /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python - <<'"'"'PY'"'"'
  from pathlib import Path
  from src.auth import users

  path = Path("data/muldae_cold_test/users.json")
  if path.exists():
      path.unlink()
  users.add_user("admin", "admin1234", role=users.ROLE_ADMIN, display_name="Cold Test Admin")
  print(path)
  PY'
  ```

  Expected output:

  ```text
  data/muldae_cold_test/users.json
  ```

- [ ] Step 2: Start the FastAPI app on an isolated port without changing any running LLM server.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_ID=$(date +%Y%m%d-%H%M%S) && RUN_DIR="reports/muldae_cold_workspace/$RUN_ID" && mkdir -p "$RUN_DIR" && echo "$RUN_DIR" > /tmp/insurance-rag-muldae-cold-run-dir.txt && USERS_JSON_PATH="$PWD/data/muldae_cold_test/users.json" DATABASE_URL="sqlite+aiosqlite:///./data/muldae_cold_test/insurance_chat.db" /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 18081 > "$RUN_DIR/uvicorn.log" 2>&1 & echo $! > "$RUN_DIR/uvicorn.pid"'
  ```

  Expected result: command returns immediately and writes a PID file under the printed run directory.

- [ ] Step 3: Verify the app health endpoint.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && for i in 1 2 3 4 5 6 7 8 9 10; do if curl -fsS http://127.0.0.1:18081/api/health > "$RUN_DIR/health.json"; then cat "$RUN_DIR/health.json"; exit 0; fi; sleep 3; done; tail -80 "$RUN_DIR/uvicorn.log"; exit 1'
  ```

  Expected output:

  ```json
  {"status":"ok"}
  ```

---

## Task 5: Reproduce The Two-Step Admin Extension Flow Through API Calls

- [ ] Step 1: Log in as the isolated test administrator and keep cookies in the run directory.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && COOKIE="$RUN_DIR/cookies.txt" && curl -fsS -c "$COOKIE" -H "Content-Type: application/json" -X POST http://127.0.0.1:18081/api/auth/login -d "{\"username\":\"admin\",\"password\":\"admin1234\"}" | tee "$RUN_DIR/login.json"'
  ```

  Expected output includes:

  ```json
  "role":"admin"
  ```

- [ ] Step 2: Upload the no-text PDF and run its intake job. It must be blocked before candidate extraction.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && COOKIE="$RUN_DIR/cookies.txt" && curl -fsS -b "$COOKIE" -c "$COOKIE" -F "file=@data/intake_test_samples/no_text_layer.pdf;type=application/pdf" http://127.0.0.1:18081/api/admin/knowledge/intake/jobs | tee "$RUN_DIR/no_text_upload.json" && NO_TEXT_JOB=$(/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -c "import json; print(json.load(open(\"$RUN_DIR/no_text_upload.json\"))[\"job_id\"])") && curl -fsS -b "$COOKIE" -c "$COOKIE" -X POST http://127.0.0.1:18081/api/admin/knowledge/intake/jobs/$NO_TEXT_JOB/run | tee "$RUN_DIR/no_text_run.json"'
  ```

  Expected result in `no_text_run.json`:

  ```json
  "status":"blocked_scanned_pdf"
  "block_reason":"scanned_pdf_text_layer_missing"
  ```

- [ ] Step 3: Upload the digital PDF and run its intake job. It must reach review-waiting state or record a candidate extraction failure with enough detail to diagnose.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && COOKIE="$RUN_DIR/cookies.txt" && curl -fsS -b "$COOKIE" -c "$COOKIE" -F "file=@data/intake_test_samples/digital_text_layer.pdf;type=application/pdf" http://127.0.0.1:18081/api/admin/knowledge/intake/jobs | tee "$RUN_DIR/digital_upload.json" && DIGITAL_JOB=$(/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -c "import json; print(json.load(open(\"$RUN_DIR/digital_upload.json\"))[\"job_id\"])") && curl -fsS -b "$COOKIE" -c "$COOKIE" -X POST http://127.0.0.1:18081/api/admin/knowledge/intake/jobs/$DIGITAL_JOB/run | tee "$RUN_DIR/digital_run.json"'
  ```

  Expected success result:

  ```json
  "status":"waiting_review"
  ```

  Acceptable diagnostic result:

  ```json
  "status":"failed"
  "block_reason":"candidate_extraction_failed"
  ```

  The diagnostic result is acceptable only if `details.error_type`, `details.error_message`, and the staging files exist for analysis.

- [ ] Step 4: Verify the administrator candidate lists are callable after intake.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && COOKIE="$RUN_DIR/cookies.txt" && curl -fsS -b "$COOKIE" http://127.0.0.1:18081/api/admin/knowledge/ontology-candidates | tee "$RUN_DIR/ontology_candidates.json" && curl -fsS -b "$COOKIE" http://127.0.0.1:18081/api/admin/knowledge/rule-candidates | tee "$RUN_DIR/rule_candidates.json"'
  ```

  Expected result: both responses are JSON objects with `total` and `items`. `total=0` is acceptable for a tiny synthetic PDF only if the digital job still reached `waiting_review` and the run report explains that no candidate-worthy expression was extracted.

- [ ] Step 5: Verify that active manifests were not changed by upload and run alone.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && git status --short data/ontology/concepts.active.json data/rules/active_rule_manifest.json data/index data/intake data/ontology/review data/rules/review | tee "$RUN_DIR/git_runtime_status.txt"'
  ```

  Expected result: runtime files may appear under `data/intake`, `data/ontology/review`, and `data/rules/review`; active manifests and indexes must not appear as modified unless the apply endpoint was explicitly called.

---

## Task 6: Validate The Administrator UI Flow

- [ ] Step 1: Create an SSH local port tunnel from the Mac to the `muldae` test runtime.

  ```bash
  ssh -N -L 18081:127.0.0.1:18081 dgx-spark-muldae
  ```

  Expected result: the command stays running. Do not start a second tunnel on the same port.

- [ ] Step 2: Open the UI in the Mac browser.

  ```text
  http://127.0.0.1:18081/login
  ```

  Expected result: login page loads. Use the isolated test administrator account created in Task 4.

- [ ] Step 3: In the admin page, verify the two-step flow is understandable to a practitioner.

  Required checks:

  - The document-add section is in the administrator page, not the general chat page.
  - The no-text PDF job shows that OCR is not performed and explains the next action.
  - The digital PDF job reaches candidate review or shows a clear failure reason.
  - Ontology and active-rule candidate review panels are reachable from the admin page.
  - The user can see the current step, why the job is blocked or waiting, and what to do next.

- [ ] Step 4: Confirm the old launcher-only review flow is no longer the only available review path.

  Expected result: a practitioner can perform review from the admin UI without relying on the DGX desktop launcher review window.

---

## Task 7: Write The Test Result Report

- [ ] Step 1: Generate a concise Markdown report in the current run directory.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python - <<'"'"'PY'"'"'
  from pathlib import Path
  import json

  run_dir = Path(Path("/tmp/insurance-rag-muldae-cold-run-dir.txt").read_text().strip())

  def load_json(name):
      path = run_dir / name
      if not path.exists():
          return {"missing": name}
      return json.loads(path.read_text(encoding="utf-8"))

  no_text = load_json("no_text_run.json")
  digital = load_json("digital_run.json")
  ontology = load_json("ontology_candidates.json")
  rules = load_json("rule_candidates.json")

  lines = [
      "# Muldae Cold Workspace Knowledge Extension Test Result",
      "",
      "## Summary",
      f"- no_text_status: {no_text.get('status')}",
      f"- no_text_block_reason: {no_text.get('block_reason')}",
      f"- digital_status: {digital.get('status')}",
      f"- digital_block_reason: {digital.get('block_reason')}",
      f"- ontology_candidate_total: {ontology.get('total')}",
      f"- rule_candidate_total: {rules.get('total')}",
      "",
      "## Acceptance",
      f"- scanned_pdf_blocked: {no_text.get('status') == 'blocked_scanned_pdf'}",
      f"- digital_pdf_processed_or_diagnosed: {digital.get('status') in {'waiting_review', 'failed'}}",
      "- active_manifest_apply_not_called: true",
      "",
      "## Evidence Files",
      "- uvicorn.log",
      "- no_text_upload.json",
      "- no_text_run.json",
      "- digital_upload.json",
      "- digital_run.json",
      "- ontology_candidates.json",
      "- rule_candidates.json",
      "- git_runtime_status.txt",
  ]
  (run_dir / "run_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
  print(run_dir / "run_summary.md")
  PY'
  ```

  Expected output:

  ```text
  reports/muldae_cold_workspace/<RUN_ID>/run_summary.md
  ```

- [ ] Step 2: Stop the isolated runtime after all checks are recorded.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt) && if [ -f "$RUN_DIR/uvicorn.pid" ]; then kill "$(cat "$RUN_DIR/uvicorn.pid")" 2>/dev/null || true; fi'
  ```

  Expected result: port `18081` no longer responds unless another intentional test runtime is running.

- [ ] Step 3: Leave the workspace clean with respect to tracked files.

  ```bash
  ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && git status --short'
  ```

  Expected result: no tracked source-code changes. Runtime outputs under ignored `data/` or `reports/` may exist and should be listed in the run report.

---

## Task 8: Final Evaluation Criteria

- [ ] Static tests pass in the `muldae` workspace.
- [ ] No-text PDF is blocked with `scanned_pdf_text_layer_missing`.
- [ ] Digital text-layer PDF reaches `waiting_review` or produces a diagnosable candidate extraction failure.
- [ ] Candidate review lists are callable from the admin API.
- [ ] Administrator UI exposes document-add and candidate-review flows without using the general chat screen.
- [ ] Upload/run alone does not rebuild GraphDB, rewrite active ontology, or rewrite active rule manifests.
- [ ] The run report explains what a practitioner should do next for blocked jobs.
- [ ] DGX main `/srv/shared/projects/insurance-rag-chatbot` remains clean and untouched except for any later user-approved commits.

---

## Rollback And Cleanup

If the test runtime or artifacts need to be removed after reporting, use these commands only in the `muldae` cold workspace:

```bash
ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && RUN_DIR=$(cat /tmp/insurance-rag-muldae-cold-run-dir.txt 2>/dev/null || true) && if [ -n "$RUN_DIR" ] && [ -f "$RUN_DIR/uvicorn.pid" ]; then kill "$(cat "$RUN_DIR/uvicorn.pid")" 2>/dev/null || true; fi'
ssh dgx-spark-muldae 'cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test && rm -rf data/intake_test_samples data/muldae_cold_test'
```

Do not delete `reports/muldae_cold_workspace/<RUN_ID>` until the result summary has been reviewed.
