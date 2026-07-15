# Hospital Receipt Claim Batch Evaluation Implementation Plan

> Status: Historical implementation plan for the recorded `v1.0.22` batch run. Revalidate the workflow before using it with a newer release.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible DGX-side evaluation package for all 155 manually extracted hospital receipt detail items using the current `v1.0.22` claim calculation logic.

**Architecture:** Add one small batch runner script that reads the existing manual extraction JSON, runs one case-level claim calculation, and writes JSON/CSV/XLSX outputs for practitioner grading. Keep OCR, production rules, and frontend behavior unchanged.

**Tech Stack:** Python 3.12, existing `src.claim_calculation` modules, `openpyxl`, stdlib `csv/json/pathlib`, DGX SGLang default model/app launcher commands.

---

## File Structure

- Create: `scripts/eval_hospital_receipt_claim_batch.py`
  - Reads the manual extraction file.
  - Normalizes it into existing `ClaimItemInput` and `ClaimCaseContext`.
  - Runs the existing calculation pipeline once.
  - Writes result artifacts.
- Create: `tests/test_eval_hospital_receipt_claim_batch.py`
  - Tests input normalization and line-result export with small sample data.
- Create at runtime only: `reports/claim_batch/manual_20260609/<timestamp>_v1.0.22/`
  - Contains result files. Do not commit runtime result files unless the user explicitly asks.
- Read only: `data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json`
- Read only: `src/claim_calculation/models.py`
- Read only: `src/claim_calculation/pipeline.py`
- Read only: `src/api/schemas/claim.py`

## Task 1: Runtime Preflight

**Files:**
- Read: `ops/bin/insurance-rag-up`
- Read: `ops/bin/switch-sglang-model`
- Read: `src/config.py`

- [ ] **Step 1: Verify DGX repository version**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
git status --short --branch
git log --oneline -1 --decorate
git tag --points-at HEAD
```

Expected:

```text
## master...origin/master
a03238f ... v1.0.22 ...
v1.0.22
```

Untracked `insurance_chat.db-shm` or `insurance_chat.db-wal` may exist and should not be committed.

- [ ] **Step 2: Verify sample input count**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path("data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json")
data = json.loads(p.read_text())
print(len(data["claim_items"]))
print(data["validation_summary"]["ready_for_auto_calculation_count"])
print(data["validation_summary"]["review_required_count"])
PY
```

Expected:

```text
155
153
2
```

- [ ] **Step 3: Start or verify default LLM/app runtime**

Run:

```bash
/srv/ai-ops/bin/insurance-rag-up --provider sglang --model qwen3-next-80b-a3b-instruct-fp8 --skip-prepare
```

Expected:

```text
http://127.0.0.1:18080
```

If the app is already running with the same default model, record that and do not restart it.

- [ ] **Step 4: Smoke-check endpoints**

Run:

```bash
curl -fsS http://127.0.0.1:18080/api/health
curl -fsS http://127.0.0.1:30000/v1/models
```

Expected:

```text
Both commands return JSON.
```

If either command fails, stop and report the runtime issue before running the batch test.

## Task 2: Add Batch Runner Tests

**Files:**
- Create: `tests/test_eval_hospital_receipt_claim_batch.py`
- Target later: `scripts/eval_hospital_receipt_claim_batch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_hospital_receipt_claim_batch.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.eval_hospital_receipt_claim_batch import (
    build_claim_context,
    build_claim_items,
    flatten_line_results,
)


def test_build_claim_items_preserves_source_metadata():
    payload = {
        "claim_items": [
            {
                "line_id": "detail_p001_r001",
                "input_name": "체질침술료",
                "input_code": "AA254",
                "claimed_amount": 13370,
                "insured_copay_amount": 2674,
                "nonpay_amount": 0,
                "quantity": 1,
                "user_category_hint": "source_amount_split:insured_copay",
                "ready_for_auto_calculation": True,
                "extra_info": {
                    "source_file": "CamScanner 2026. 6. 9. 15.00_1.jpg",
                    "page_label": "1 / 9",
                    "source_row_id": "detail_p001_r001",
                    "item_group": "진찰료",
                    "service_date": "20260324-20260324",
                },
            }
        ]
    }

    items, metadata = build_claim_items(payload)

    assert len(items) == 1
    assert items[0].line_id == "detail_p001_r001"
    assert items[0].claimed_amount == "13370"
    assert items[0].insured_copay_amount == "2674"
    assert items[0].quantity == "1"
    assert metadata["detail_p001_r001"]["page_label"] == "1 / 9"
    assert metadata["detail_p001_r001"]["ready_for_auto_calculation"] is True


def test_build_claim_context_defaults_to_latest_supported_generation():
    payload = {
        "claim_case_context": {
            "treatment_date": "2026-03-25",
            "visit_type": "hospitalization",
            "diagnosis_code": ["S8352", "S8329"],
            "diagnosis_name": ["전십자인대의 파열, 우측", "내측 반달연골의 파열, 우측"],
            "policy_generation": None,
            "situation_note": "입원기간 2026-03-24~2026-03-27",
        }
    }

    context = build_claim_context(payload)

    assert context.policy_generation == "5th"
    assert context.visit_type == "hospitalization"
    assert context.diagnosis_code == "S8352, S8329"
    assert "전십자인대" in context.diagnosis_name


def test_flatten_line_results_adds_practitioner_columns():
    line_results = [
        {
            "line_id": "detail_p001_r001",
            "input_name": "체질침술료",
            "category": "급여",
            "claimed_amount": "13370",
            "deductible": "2674",
            "payable_amount": "10696",
            "calculation_status": "auto_calculated",
            "requires_review": False,
            "review_reasons": [],
            "rule_summary": "급여 본인부담 20%",
        }
    ]
    metadata = {
        "detail_p001_r001": {
            "source_file": "CamScanner 2026. 6. 9. 15.00_1.jpg",
            "page_label": "1 / 9",
            "source_row_id": "detail_p001_r001",
            "item_group": "진찰료",
            "service_date": "20260324-20260324",
            "ready_for_auto_calculation": True,
        }
    }

    rows = flatten_line_results(line_results, metadata)

    assert rows[0]["page_label"] == "1 / 9"
    assert rows[0]["input_name"] == "체질침술료"
    assert rows[0]["payable_amount"] == "10696"
    assert rows[0]["practitioner_grade"] == ""
    assert rows[0]["practitioner_comment"] == ""
    assert rows[0]["corrected_payable_amount"] == ""
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python -m pytest tests/test_eval_hospital_receipt_claim_batch.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'scripts.eval_hospital_receipt_claim_batch'
```

## Task 3: Implement Batch Runner

**Files:**
- Create: `scripts/eval_hospital_receipt_claim_batch.py`
- Test: `tests/test_eval_hospital_receipt_claim_batch.py`

- [ ] **Step 1: Create the script**

Create `scripts/eval_hospital_receipt_claim_batch.py`:

```python
#!/usr/bin/env python3
"""Evaluate manual hospital receipt detail rows with the claim calculator."""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from src import config
from src.api.schemas.claim import ClaimCalculationResponse
from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation
from src.api.rag_service import get_rag_pipeline


DEFAULT_INPUT = Path("data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json")
DEFAULT_OUTPUT_ROOT = Path("reports/claim_batch/manual_20260609")
DEFAULT_APP_VERSION = "v1.0.22"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None)
    return str(value)


def build_claim_context(payload: dict[str, Any]) -> ClaimCaseContext:
    raw = payload.get("claim_case_context") or {}
    return ClaimCaseContext(
        treatment_date=_text(raw.get("treatment_date")),
        visit_type=_text(raw.get("visit_type")),
        coverage_topic=_text(raw.get("coverage_topic") or "실손"),
        diagnosis_code=_text(raw.get("diagnosis_code")),
        diagnosis_name=_text(raw.get("diagnosis_name")),
        accident_type=_text(raw.get("accident_type")),
        situation_note=_text(raw.get("situation_note")),
        policy_generation=_text(raw.get("policy_generation") or "5th"),
        facility_type=_text(raw.get("facility_type")),
        facility_grade=_text(raw.get("facility_grade")),
    )


def build_claim_items(payload: dict[str, Any]) -> tuple[list[ClaimItemInput], dict[str, dict[str, Any]]]:
    items: list[ClaimItemInput] = []
    metadata: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(payload.get("claim_items") or [], start=1):
        line_id = _text(raw.get("line_id") or f"line-{idx}")
        extra = raw.get("extra_info") or {}
        items.append(
            ClaimItemInput(
                line_id=line_id,
                input_name=_text(raw.get("input_name")),
                input_code=_text(raw.get("input_code")),
                claimed_amount=_text(raw.get("claimed_amount")),
                insured_copay_amount=_text(raw.get("insured_copay_amount")),
                nonpay_amount=_text(raw.get("nonpay_amount")),
                quantity=_text(raw.get("quantity") or "1"),
                user_category_hint=_text(raw.get("user_category_hint")),
                extra_info=json.dumps(extra, ensure_ascii=False),
            )
        )
        metadata[line_id] = {
            "source_file": _text(extra.get("source_file")),
            "page_label": _text(extra.get("page_label")),
            "source_row_id": _text(extra.get("source_row_id") or line_id),
            "item_group": _text(extra.get("item_group")),
            "service_date": _text(extra.get("service_date")),
            "ready_for_auto_calculation": bool(raw.get("ready_for_auto_calculation")),
        }
    return items, metadata


def flatten_line_results(line_results: list[dict[str, Any]], metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in line_results:
        line_id = _text(line.get("line_id"))
        meta = metadata.get(line_id, {})
        review_reasons = line.get("review_reasons") or []
        rows.append(
            {
                "source_file": meta.get("source_file", ""),
                "page_label": meta.get("page_label", ""),
                "source_row_id": meta.get("source_row_id", line_id),
                "item_group": meta.get("item_group", ""),
                "service_date": meta.get("service_date", ""),
                "ready_for_auto_calculation": meta.get("ready_for_auto_calculation", False),
                "line_id": line_id,
                "input_code": _text(line.get("input_code")),
                "input_name": _text(line.get("input_name")),
                "claimed_amount": _text(line.get("claimed_amount")),
                "insured_copay_amount": _text(line.get("insured_copay_amount")),
                "nonpay_amount": _text(line.get("nonpay_amount")),
                "category": _text(line.get("category")),
                "deductible": _text(line.get("deductible")),
                "payable_amount": _text(line.get("payable_amount")),
                "calculation_status": _text(line.get("calculation_status")),
                "requires_review": bool(line.get("requires_review")),
                "review_reasons": "; ".join(_text(reason) for reason in review_reasons),
                "rule_summary": _text(line.get("rule_summary")),
                "practitioner_grade": "",
                "practitioner_comment": "",
                "corrected_category": "",
                "corrected_payable_amount": "",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "practitioner_scoring"
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append([row[key] for key in rows[0].keys()])
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    review_fill = PatternFill("solid", fgColor="FFF2CC")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    requires_review_col = None
    for idx, cell in enumerate(ws[1], start=1):
        if cell.value == "requires_review":
            requires_review_col = idx
            break
    if requires_review_col:
        for row_idx in range(2, ws.max_row + 1):
            if ws.cell(row_idx, requires_review_col).value is True:
                for col_idx in range(1, ws.max_column + 1):
                    ws.cell(row_idx, col_idx).fill = review_fill
    ws.freeze_panes = "A2"
    wb.save(path)


def run_batch(input_path: Path, output_root: Path, app_version: str, no_rag: bool) -> Path:
    payload = json.loads(input_path.read_text())
    items, metadata = build_claim_items(payload)
    context = build_claim_context(payload)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / f"{timestamp}_{app_version}"
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    rag_pipeline = None
    if not no_rag:
        try:
            rag_pipeline = get_rag_pipeline(f"sglang:{config.SGLANG_DEFAULT_MODEL}", config.CLAIM_RAG_TOP_K, "v2_only")
        except Exception as exc:
            warnings.append(f"RAG pipeline unavailable: {exc}")

    started = time.perf_counter()
    result = run_claim_calculation(
        rag_pipeline=rag_pipeline,
        items=items,
        context=context,
        basis_mode="auto",
        use_fake_planner=True,
        model_id=config.SGLANG_DEFAULT_MODEL,
        provider="sglang",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response = ClaimCalculationResponse.from_result(result, warnings)
    rows = flatten_line_results(response.line_results, metadata)

    normalized_input = {
        "app_version": app_version,
        "model": f"sglang:{config.SGLANG_DEFAULT_MODEL}",
        "context": context.__dict__,
        "items": [item.__dict__ for item in items],
    }
    summary = {
        "app_version": app_version,
        "model": f"sglang:{config.SGLANG_DEFAULT_MODEL}",
        "input_file": str(input_path),
        "input_item_count": len(items),
        "line_result_count": len(rows),
        "claimed_amount": response.claimed_amount,
        "deductible": response.deductible,
        "payable_amount": response.payable_amount,
        "requires_review": response.requires_review,
        "review_line_count": sum(1 for row in rows if row["requires_review"]),
        "elapsed_ms": elapsed_ms,
        "warnings": warnings,
    }

    (output_dir / "input_payload.json").write_text(json.dumps(normalized_input, ensure_ascii=False, indent=2))
    (output_dir / "claim_response.json").write_text(response.model_dump_json(indent=2))
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    write_csv(output_dir / "line_results.csv", rows)
    write_xlsx(output_dir / "practitioner_scoring.xlsx", rows)
    (output_dir / "README.md").write_text(
        "\n".join(
            [
                "# Hospital Receipt Claim Batch Evaluation",
                "",
                f"- App version: `{app_version}`",
                f"- Model: `sglang:{config.SGLANG_DEFAULT_MODEL}`",
                f"- Input items: `{len(items)}`",
                f"- Review lines: `{summary['review_line_count']}`",
                "",
                "Practitioner grading is done in `practitioner_scoring.xlsx`.",
                "Fill `practitioner_grade`, `practitioner_comment`, `corrected_category`, and `corrected_payable_amount`.",
            ]
        )
    )
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hospital receipt claim batch evaluation.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--app-version", default=DEFAULT_APP_VERSION)
    parser.add_argument("--no-rag", action="store_true")
    args = parser.parse_args()
    output_dir = run_batch(args.input, args.output_root, args.app_version, args.no_rag)
    print(output_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the unit tests**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python -m pytest tests/test_eval_hospital_receipt_claim_batch.py -q
```

Expected:

```text
3 passed
```

## Task 4: Run the Batch Evaluation

**Files:**
- Read: `data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json`
- Create runtime outputs under: `reports/claim_batch/manual_20260609/`

- [ ] **Step 1: Run the evaluator**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python scripts/eval_hospital_receipt_claim_batch.py \
  --input data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json \
  --output-root reports/claim_batch/manual_20260609 \
  --app-version v1.0.22
```

Expected:

```text
reports/claim_batch/manual_20260609/<timestamp>_v1.0.22
```

- [ ] **Step 2: Verify output files exist**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
RUN_DIR="$(ls -td reports/claim_batch/manual_20260609/*_v1.0.22 | head -1)"
test -f "$RUN_DIR/input_payload.json"
test -f "$RUN_DIR/claim_response.json"
test -f "$RUN_DIR/line_results.csv"
test -f "$RUN_DIR/practitioner_scoring.xlsx"
test -f "$RUN_DIR/summary.json"
test -f "$RUN_DIR/README.md"
echo "$RUN_DIR"
```

Expected:

```text
reports/claim_batch/manual_20260609/<timestamp>_v1.0.22
```

- [ ] **Step 3: Verify item counts**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
RUN_DIR="$(ls -td reports/claim_batch/manual_20260609/*_v1.0.22 | head -1)"
.venv/bin/python - <<PY
import csv, json
from pathlib import Path
run = Path("$RUN_DIR")
summary = json.loads((run / "summary.json").read_text())
rows = list(csv.DictReader((run / "line_results.csv").open(encoding="utf-8-sig")))
print(summary["input_item_count"])
print(summary["line_result_count"])
print(len(rows))
print(summary["model"])
PY
```

Expected:

```text
155
155
155
sglang:qwen3-next-80b-a3b-instruct-fp8
```

## Task 5: Prepare Practitioner Grading Package

**Files:**
- Read: latest `reports/claim_batch/manual_20260609/*_v1.0.22/`
- Create: `reports/claim_batch/manual_20260609/<timestamp>_v1.0.22/practitioner_review_guide.md`

- [ ] **Step 1: Write the review guide**

Create `practitioner_review_guide.md` in the run directory:

```markdown
# 실무자 채점 가이드

## 채점 대상

`practitioner_scoring.xlsx`의 각 행은 병원 진료비 세부산정내역서의 한 항목입니다.

## 확인할 열

- `input_name`: 원문 항목명
- `input_code`: 원문 코드
- `claimed_amount`: 계산에 넣은 총액
- `insured_copay_amount`: 급여 본인부담 입력금액
- `nonpay_amount`: 비급여 입력금액
- `category`: 계산기가 분류한 항목 유형
- `deductible`: 예상 공제금액
- `payable_amount`: 예상 지급금액
- `requires_review`: 추가 확인 필요 여부
- `review_reasons`: 추가 확인 사유

## 실무자 입력 열

- `practitioner_grade`: `pass`, `fail`, `review` 중 하나를 입력합니다.
- `practitioner_comment`: 틀렸거나 애매한 이유를 적습니다.
- `corrected_category`: 분류가 틀린 경우 올바른 분류를 적습니다.
- `corrected_payable_amount`: 지급예상액이 틀린 경우 올바른 금액을 적습니다.

## 주의

이 결과는 확정 보험금 지급 결과가 아니라 현재 앱 계산 로직의 평가 자료입니다.
계약 담보, 사고 유형, 특약 가입 여부, 기존 지급 이력은 별도 확인 대상입니다.
```

- [ ] **Step 2: Verify the workbook can be opened by Python**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
RUN_DIR="$(ls -td reports/claim_batch/manual_20260609/*_v1.0.22 | head -1)"
.venv/bin/python - <<PY
from openpyxl import load_workbook
from pathlib import Path
run = Path("$RUN_DIR")
wb = load_workbook(run / "practitioner_scoring.xlsx")
ws = wb.active
print(ws.max_row - 1)
print(ws["A1"].value)
PY
```

Expected:

```text
155
source_file
```

## Task 6: Write Test Result Report

**Files:**
- Create: `docs/265_HOSPITAL_RECEIPT_CLAIM_BATCH_EVALUATION_REPORT.md`

- [ ] **Step 1: Generate the report from the latest run**

Create `docs/265_HOSPITAL_RECEIPT_CLAIM_BATCH_EVALUATION_REPORT.md` with this structure:

```markdown
# 265. 병원 영수증 세부내역 보험금 계산 배치 테스트 보고서

기준 버전: `v1.0.22`
기준 입력: `data/hospital_receipts/manual_20260609/manual_extraction/claim_calculation_input.json`
결과 경로: `reports/claim_batch/manual_20260609/<timestamp>_v1.0.22`

## 1. 목적

수기 판독된 병원 세부내역 155개 항목 전체를 현재 보험금 계산 로직에 넣고, 실무자 채점 가능한 결과물을 생성했다.

## 2. 실행 환경

- DGX 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- 앱 버전: `v1.0.22`
- 기본 모델: `sglang:qwen3-next-80b-a3b-instruct-fp8`
- 인덱스 모드: `v2_only`
- 계산 방식: 기존 deterministic claim calculation pipeline

## 3. 입력 요약

- 전체 항목 수: `155`
- 수기 판독 기준 자동 계산 가능 후보: `153`
- 수기 판독 기준 검토 필요 후보: `2`
- 청구 맥락: 입원, 2026-03-24~2026-03-27, 5세대 기본값

## 4. 산출물

- `input_payload.json`
- `claim_response.json`
- `line_results.csv`
- `practitioner_scoring.xlsx`
- `summary.json`
- `README.md`
- `practitioner_review_guide.md`

## 5. 결과 요약

- 총 청구금액: `<summary.claimed_amount>`
- 총 공제금액: `<summary.deductible>`
- 예상 지급금액: `<summary.payable_amount>`
- 추가 확인 필요 항목 수: `<summary.review_line_count>`

## 6. 실무자 채점 방법

실무자는 `practitioner_scoring.xlsx`를 열고 `practitioner_grade`, `practitioner_comment`, `corrected_category`, `corrected_payable_amount`를 입력한다.

## 7. 한계

이 테스트는 OCR 자동화 평가가 아니라 수기 판독 입력 기반 계산 로직 평가다.
계약 담보, 사고 유형, 특약 가입 여부, 기존 지급 이력은 병원 서류만으로 확정되지 않는다.
```

Replace angle-bracket placeholders with values from `summary.json` before saving the report.

- [ ] **Step 2: Verify the report has no placeholders**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
rg -n "<summary|<timestamp>|TBD|TODO" docs/265_HOSPITAL_RECEIPT_CLAIM_BATCH_EVALUATION_REPORT.md
```

Expected:

```text
No output.
```

## Task 7: Final Validation

**Files:**
- Test: `tests/test_eval_hospital_receipt_claim_batch.py`
- Runtime output: latest `reports/claim_batch/manual_20260609/*_v1.0.22/`

- [ ] **Step 1: Run focused tests**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
.venv/bin/python -m pytest tests/test_eval_hospital_receipt_claim_batch.py tests/test_claim_calculation_pipeline.py tests/test_api_claim_calculation.py -q
```

Expected:

```text
All tests pass.
```

- [ ] **Step 2: Check uncommitted generated runtime outputs**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
git status --short
```

Expected:

```text
scripts/eval_hospital_receipt_claim_batch.py
tests/test_eval_hospital_receipt_claim_batch.py
docs/265_HOSPITAL_RECEIPT_CLAIM_BATCH_EVALUATION_REPORT.md
```

Runtime files under `reports/claim_batch/manual_20260609/` should remain untracked unless the user explicitly asks to commit result artifacts.

- [ ] **Step 3: Report practitioner package path**

Report:

```text
실무자 채점 파일: /srv/shared/projects/insurance-rag-chatbot/reports/claim_batch/manual_20260609/<timestamp>_v1.0.22/practitioner_scoring.xlsx
```

## Plan Self-Review

- Spec coverage: covers default LLM/app preflight, all 155 sample items, result recording, and practitioner grading.
- Placeholder scan: the only angle-bracket strings appear inside the report template task and are explicitly replaced before saving.
- Type consistency: functions used in tests match functions defined in the script task.
- Scope check: this plan adds one runner and one report path; it does not alter OCR, rules, or app behavior.
