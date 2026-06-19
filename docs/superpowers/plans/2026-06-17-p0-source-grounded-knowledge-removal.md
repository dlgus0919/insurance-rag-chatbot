# P0 Source-Grounded Knowledge Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove production insurance knowledge hardcoding from claim calculation, deterministic RAG answers, and GraphRAG extraction by moving values into source-grounded approved rule/ontology data.

**Architecture:** Keep runtime code as a deterministic interpreter and evidence selector. Insurance-specific values enter production only through source rows, approved rule manifests, or practitioner-approved ontology candidates. GraphRAG knowledge expansion should prefer the existing practitioner approval workflow instead of direct code constants.

**Tech Stack:** Python 3.12, pytest, JSON Schema-style validation, existing FastAPI/RAG/GraphRAG modules, existing ontology review workflow.

---

## Guardrails

This plan must obey `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`.

- Do not add product-specific payout, exemption, deductible, or limit values to Python constants.
- Do not move answer values into a generic policy file just to hide hardcoding.
- Use source evidence, approved rule manifests, and practitioner approval records.
- LLMs may enrich descriptions or review questions, but must not invent calculation rules.
- Auto-approval must not approve payout, exemption, reduction, limit, or claim calculation rules.

## File Structure

Create:

- `data/rules/claim_deductible_rules.schema.json`  
  Schema for approved deductible rule rows. This is a contract, not production values.
- `data/rules/claim_deductible_rules.active.json`  
  Active source-grounded rule rows. Seed from current code values only with source references and `approval_status: "active"`.
- `src/claim_calculation/rule_registry.py`  
  Loads, validates, and indexes active claim rules.
- `tests/test_claim_rule_registry.py`  
  Unit tests for rule loading, source reference enforcement, and lookup behavior.
- `src/rag/source_grounded_answers.py`  
  Builds deterministic answers only from source rows and approved rule rows.
- `tests/test_source_grounded_answers.py`  
  Tests that answer builders cannot emit values not present in evidence.
- `data/ontology/policies/graph_extraction_markers.schema.json`  
  Schema for extractor marker candidates and approved marker manifests.
- `data/ontology/policies/graph_extraction_markers.active.json`  
  Approved marker manifest used by GraphRAG extraction.
- `tests/test_graph_extraction_marker_policy.py`  
  Tests marker loading and approval-status filtering.

Modify:

- `src/claim_calculation/deductible_rules.py`  
  Remove embedded rule values. Keep compatibility wrappers around `rule_registry`.
- `src/claim_calculation/pipeline.py`  
  Use `rule_registry` and remove LLM-created formula authority for rule values.
- `src/rag/pipeline.py`  
  Remove question-specific answer blocks and call `source_grounded_answers`.
- `src/graph/extractors.py`  
  Load approved marker manifest instead of embedded benefit/deductible constants.
- `src/ontology/registry.py` or nearest existing ontology loader  
  Expose approved graph extraction markers if this is the existing integration point.
- `scripts/ontology_review.py`  
  Extend review listing/apply flow for graph marker candidates only if existing schema cannot express them.

Do not modify:

- `src/ui/streamlit_app.py`
- Raw PDF/XLSX/OCR source data
- Runtime index directories unless a test fixture explicitly creates temp files

## Task 1: Add Claim Rule Manifest Contract

**Files:**
- Create: `data/rules/claim_deductible_rules.schema.json`
- Create: `data/rules/claim_deductible_rules.active.json`
- Test: `tests/test_claim_rule_registry.py`

- [ ] **Step 1: Write the failing schema and loader tests**

Create `tests/test_claim_rule_registry.py`:

```python
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.claim_calculation.rule_registry import ClaimRuleRegistry, ClaimRuleValidationError


def _write_rules(path, rows):
    path.write_text(json.dumps({"version": 1, "rules": rows}, ensure_ascii=False), encoding="utf-8")


def test_registry_loads_active_rule_with_source_reference(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [
            {
                "rule_id": "deductible.4th.outpatient.non_benefit",
                "generation": "4th",
                "category": "비급여",
                "visit_type": "outpatient",
                "facility_grade": "clinic",
                "copay_ratio": "0.3",
                "min_deductible": "30000",
                "per_visit_limit": "250000",
                "annual_limit": None,
                "annual_visit_limit": 180,
                "source_doc": "약관",
                "source_page": "p.12",
                "source_clause": "제5조",
                "source_chunk_id": "chunk-1",
                "approval_status": "active",
            }
        ],
    )

    registry = ClaimRuleRegistry.from_file(rules_path)
    rule = registry.lookup("4th", "비급여", "outpatient", "clinic")

    assert rule.rule_id == "deductible.4th.outpatient.non_benefit"
    assert rule.copay_ratio == Decimal("0.3")
    assert rule.min_deductible == Decimal("30000")
    assert rule.source_chunk_id == "chunk-1"


def test_registry_rejects_rule_without_source_reference(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [
            {
                "rule_id": "deductible.invalid",
                "generation": "4th",
                "category": "급여",
                "visit_type": "outpatient",
                "facility_grade": "clinic",
                "copay_ratio": "0.2",
                "min_deductible": "10000",
                "per_visit_limit": "250000",
                "annual_limit": None,
                "annual_visit_limit": 180,
                "source_doc": "",
                "source_page": "",
                "source_clause": "",
                "source_chunk_id": "",
                "approval_status": "active",
            }
        ],
    )

    with pytest.raises(ClaimRuleValidationError, match="source"):
        ClaimRuleRegistry.from_file(rules_path)


def test_registry_ignores_non_active_rules(tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [
            {
                "rule_id": "deductible.pending",
                "generation": "4th",
                "category": "급여",
                "visit_type": "outpatient",
                "facility_grade": "clinic",
                "copay_ratio": "0.2",
                "min_deductible": "10000",
                "per_visit_limit": "250000",
                "annual_limit": None,
                "annual_visit_limit": 180,
                "source_doc": "약관",
                "source_page": "p.10",
                "source_clause": "제5조",
                "source_chunk_id": "chunk-2",
                "approval_status": "pending",
            }
        ],
    )

    registry = ClaimRuleRegistry.from_file(rules_path)

    with pytest.raises(KeyError):
        registry.lookup("4th", "급여", "outpatient", "clinic")
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_registry.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.claim_calculation.rule_registry'
```

- [ ] **Step 3: Add the manifest schema**

Create `data/rules/claim_deductible_rules.schema.json`:

```json
{
  "version": 1,
  "required_rule_fields": [
    "rule_id",
    "generation",
    "category",
    "visit_type",
    "facility_grade",
    "copay_ratio",
    "min_deductible",
    "source_doc",
    "source_page",
    "source_clause",
    "source_chunk_id",
    "approval_status"
  ],
  "allowed_approval_status": ["active", "pending", "held", "rejected"],
  "description": "Schema contract for source-grounded claim deductible rule rows. Product values live in active manifests with source references, not in Python constants."
}
```

- [ ] **Step 4: Add the active manifest seeded from current behavior**

Create `data/rules/claim_deductible_rules.active.json` with rows for the current supported 4th/5th generation rules. Use source references from the current indexed 약관 chunks. Do not invent a source reference.

Use this exact shape for every row:

```json
{
  "version": 1,
  "rules": [
    {
      "rule_id": "deductible.4th.outpatient.non_benefit.clinic",
      "generation": "4th",
      "category": "비급여",
      "visit_type": "outpatient",
      "facility_grade": "clinic",
      "copay_ratio": "0.3",
      "min_deductible": "30000",
      "per_visit_limit": "250000",
      "annual_limit": null,
      "annual_visit_limit": 180,
      "source_doc": "약관",
      "source_page": "source page from indexed 약관 row",
      "source_clause": "source clause from indexed 약관 row",
      "source_chunk_id": "source chunk id from indexed 약관 row",
      "approval_status": "active"
    }
  ]
}
```

If a source reference cannot be located for a row, exclude that row from `active.json` and let downstream tests reveal the missing coverage.

- [ ] **Step 5: Implement the registry**

Create `src/claim_calculation/rule_registry.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from src import config


class ClaimRuleValidationError(ValueError):
    """Raised when a claim rule manifest is not safe for calculation."""


@dataclass(frozen=True)
class ClaimDeductibleRule:
    rule_id: str
    generation: str
    category: str
    visit_type: str
    facility_grade: str
    copay_ratio: Decimal
    min_deductible: Decimal
    per_visit_limit: Decimal | None
    annual_limit: Decimal | None
    annual_visit_limit: int | None
    source_doc: str
    source_page: str
    source_clause: str
    source_chunk_id: str
    approval_status: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClaimDeductibleRule":
        required = (
            "rule_id",
            "generation",
            "category",
            "visit_type",
            "facility_grade",
            "copay_ratio",
            "min_deductible",
            "source_doc",
            "source_page",
            "source_clause",
            "source_chunk_id",
            "approval_status",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ClaimRuleValidationError(f"missing required claim rule fields: {missing}")
        if payload["approval_status"] == "active":
            source_values = [payload.get("source_doc"), payload.get("source_page"), payload.get("source_chunk_id")]
            if not all(str(value or "").strip() for value in source_values):
                raise ClaimRuleValidationError(f"active rule {payload.get('rule_id')} is missing source reference")
        return cls(
            rule_id=str(payload["rule_id"]),
            generation=str(payload["generation"]),
            category=str(payload["category"]),
            visit_type=str(payload["visit_type"]),
            facility_grade=str(payload["facility_grade"]),
            copay_ratio=Decimal(str(payload["copay_ratio"])),
            min_deductible=Decimal(str(payload["min_deductible"])),
            per_visit_limit=_decimal_or_none(payload.get("per_visit_limit")),
            annual_limit=_decimal_or_none(payload.get("annual_limit")),
            annual_visit_limit=_int_or_none(payload.get("annual_visit_limit")),
            source_doc=str(payload["source_doc"]),
            source_page=str(payload["source_page"]),
            source_clause=str(payload["source_clause"]),
            source_chunk_id=str(payload["source_chunk_id"]),
            approval_status=str(payload["approval_status"]),
        )


class ClaimRuleRegistry:
    def __init__(self, rules: list[ClaimDeductibleRule]) -> None:
        self._rules = [rule for rule in rules if rule.approval_status == "active"]
        self._by_key = {
            (rule.generation, rule.category, rule.visit_type, rule.facility_grade): rule
            for rule in self._rules
        }

    @classmethod
    def from_file(cls, path: Path | str) -> "ClaimRuleRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("rules", [])
        if not isinstance(rows, list):
            raise ClaimRuleValidationError("claim rule manifest must contain a rules list")
        return cls([ClaimDeductibleRule.from_payload(row) for row in rows])

    def lookup(self, generation: str, category: str, visit_type: str, facility_grade: str) -> ClaimDeductibleRule:
        return self._by_key[(generation, category, visit_type, facility_grade)]


def load_default_claim_rule_registry() -> ClaimRuleRegistry:
    path = config.ROOT_DIR / "data" / "rules" / "claim_deductible_rules.active.json"
    return ClaimRuleRegistry.from_file(path)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
```

- [ ] **Step 6: Run the registry tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_registry.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Commit**

Run:

```bash
git add data/rules/claim_deductible_rules.schema.json \
  data/rules/claim_deductible_rules.active.json \
  src/claim_calculation/rule_registry.py \
  tests/test_claim_rule_registry.py
git commit -m "feat(claim): add source-grounded deductible rule registry"
```

## Task 2: Replace Deductible Rule Constants with Registry Lookup

**Files:**
- Modify: `src/claim_calculation/deductible_rules.py`
- Modify: `src/claim_calculation/pipeline.py`
- Test: `tests/test_claim_calculation_pipeline.py`
- Test: `tests/test_claim_rule_registry.py`

- [ ] **Step 1: Add a compatibility test for the current public lookup API**

Append to `tests/test_claim_rule_registry.py`:

```python
def test_legacy_lookup_rule_uses_active_registry(monkeypatch, tmp_path):
    rules_path = tmp_path / "rules.json"
    _write_rules(
        rules_path,
        [
            {
                "rule_id": "deductible.4th.outpatient.benefit.clinic",
                "generation": "4th",
                "category": "급여",
                "visit_type": "outpatient",
                "facility_grade": "clinic",
                "copay_ratio": "0.2",
                "min_deductible": "10000",
                "per_visit_limit": "250000",
                "annual_limit": None,
                "annual_visit_limit": 180,
                "source_doc": "약관",
                "source_page": "p.10",
                "source_clause": "제5조",
                "source_chunk_id": "chunk-3",
                "approval_status": "active",
            }
        ],
    )

    import src.claim_calculation.deductible_rules as deductible_rules

    monkeypatch.setattr(deductible_rules, "CLAIM_RULES_PATH", rules_path)
    deductible_rules._load_registry.cache_clear()

    rule = deductible_rules.lookup_rule("4th", "급여", "outpatient", "clinic")

    assert rule.copay_ratio == Decimal("0.2")
    assert rule.get_min_deductible("clinic") == Decimal("10000")
```

- [ ] **Step 2: Run the compatibility test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_registry.py::test_legacy_lookup_rule_uses_active_registry -q
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Replace embedded rules with registry-backed wrappers**

Replace `src/claim_calculation/deductible_rules.py` with a compatibility layer:

```python
"""Source-grounded claim deductible rule lookup.

Production rule values live in data/rules/claim_deductible_rules.active.json.
This module keeps the previous lookup API for callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from src import config
from src.claim_calculation.rule_registry import ClaimDeductibleRule, ClaimRuleRegistry


FACILITY_CLINIC = "clinic"
FACILITY_HOSPITAL = "hospital"
FACILITY_GENERAL = "general_hospital"
FACILITY_TERTIARY = "tertiary_hospital"
FACILITY_GRADES = (FACILITY_CLINIC, FACILITY_HOSPITAL, FACILITY_GENERAL, FACILITY_TERTIARY)
DEFAULT_FACILITY = FACILITY_CLINIC
CLAIM_RULES_PATH = config.ROOT_DIR / "data" / "rules" / "claim_deductible_rules.active.json"


@dataclass(frozen=True)
class DeductibleRule:
    generation: str
    category: str
    visit_type: str
    copay_ratio: Decimal
    min_deductible_by_facility: dict[str, Decimal]
    per_visit_limit: Decimal | None = None
    annual_limit: Decimal | None = None
    annual_visit_limit: int | None = None
    description: str = ""
    source_chunk_id: str = ""

    def get_min_deductible(self, facility_grade: str = "") -> Decimal:
        grade = facility_grade if facility_grade in self.min_deductible_by_facility else DEFAULT_FACILITY
        return self.min_deductible_by_facility.get(grade, Decimal("0"))


@dataclass(frozen=True)
class PrescriptionRule:
    generation: str
    deductible_amount: Decimal
    per_visit_limit: Decimal | None = None
    description: str = ""
    source_chunk_id: str = ""


@lru_cache(maxsize=1)
def _load_registry() -> ClaimRuleRegistry:
    return ClaimRuleRegistry.from_file(Path(CLAIM_RULES_PATH))


def lookup_rule(generation: str, category: str, visit_type: str, facility_grade: str = "") -> DeductibleRule:
    grade = facility_grade or DEFAULT_FACILITY
    active = _lookup_with_alias(generation, category, visit_type, grade)
    min_by_facility = _facility_minimums(active.generation, active.category, active.visit_type)
    return DeductibleRule(
        generation=active.generation,
        category=active.category,
        visit_type=active.visit_type,
        copay_ratio=active.copay_ratio,
        min_deductible_by_facility=min_by_facility,
        per_visit_limit=active.per_visit_limit,
        annual_limit=active.annual_limit,
        annual_visit_limit=active.annual_visit_limit,
        description=f"{active.rule_id} ({active.source_doc} {active.source_page})",
        source_chunk_id=active.source_chunk_id,
    )


def lookup_prescription_rule(generation: str) -> PrescriptionRule:
    active = _lookup_with_alias(generation, "처방약", "outpatient", DEFAULT_FACILITY)
    return PrescriptionRule(
        generation=active.generation,
        deductible_amount=active.min_deductible,
        per_visit_limit=active.per_visit_limit,
        description=f"{active.rule_id} ({active.source_doc} {active.source_page})",
        source_chunk_id=active.source_chunk_id,
    )


def _lookup_with_alias(generation: str, category: str, visit_type: str, facility_grade: str) -> ClaimDeductibleRule:
    gen = generation if generation in {"4th", "5th"} else "4th"
    vt = visit_type if visit_type in {"hospitalization", "outpatient"} else "outpatient"
    grade = facility_grade if facility_grade in FACILITY_GRADES else DEFAULT_FACILITY
    categories = [category]
    if gen == "4th" and category in {"3대비급여", "중증비급여", "비중증비급여"}:
        categories.append("비급여")
    categories.append("급여")
    registry = _load_registry()
    last_error: KeyError | None = None
    for candidate in categories:
        try:
            return registry.lookup(gen, candidate, vt, grade)
        except KeyError as exc:
            last_error = exc
    raise KeyError(f"no active deductible rule for {(gen, category, vt, grade)}") from last_error


def _facility_minimums(generation: str, category: str, visit_type: str) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    registry = _load_registry()
    for grade in FACILITY_GRADES:
        try:
            values[grade] = registry.lookup(generation, category, visit_type, grade).min_deductible
        except KeyError:
            values[grade] = Decimal("0")
    return values
```

- [ ] **Step 4: Run claim tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_registry.py tests/test_claim_calculation_pipeline.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Search for remaining production deductible constants**

Run:

```bash
rg -n 'Decimal\("0\.[235]"|30000|50000|250000|200000|50000000|8000' src/claim_calculation tests data/rules
```

Expected:

- Matches in `data/rules/claim_deductible_rules.active.json` are allowed.
- Matches in tests are allowed.
- Matches in `src/claim_calculation/deductible_rules.py` for production rule values are not allowed.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/claim_calculation/deductible_rules.py \
  src/claim_calculation/pipeline.py \
  tests/test_claim_rule_registry.py \
  tests/test_claim_calculation_pipeline.py
git commit -m "refactor(claim): load deductible rules from approved manifest"
```

## Task 3: Remove LLM Formula Authority from Claim Calculation

**Files:**
- Modify: `src/claim_calculation/pipeline.py`
- Modify: `src/claim_calculation/planner.py`
- Test: `tests/test_claim_calculation_pipeline.py`

- [ ] **Step 1: Add a test that LLM formula cannot determine final payout**

Append to `tests/test_claim_calculation_pipeline.py`:

```python
def test_llm_formula_is_never_final_authority_for_claim_amount(monkeypatch):
    from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
    from src.claim_calculation.pipeline import run_claim_calculation

    class BadPlanner:
        def plan(self, items, context, evidences):
            from src.claim_calculation.models import CalculationPlan

            return CalculationPlan(
                decision="calculable",
                formula_intent=(
                    "claimed_amount = Decimal('999999')\n"
                    "deductible = Decimal('0')\n"
                    "payable_amount = Decimal('999999')"
                ),
            )

    monkeypatch.setattr("src.claim_calculation.pipeline.LLMPlanner", lambda **kwargs: BadPlanner())

    item = ClaimItemInput(input_name="도수치료", claimed_amount="100000")
    context = ClaimCaseContext(policy_generation="5th", visit_type="outpatient", coverage_topic="실손")

    result = run_claim_calculation(
        rag_pipeline=None,
        items=[item],
        context=context,
        use_fake_planner=False,
        provider="local-test",
        model_id="local-test",
    )

    assert result.payable_amount != "999999"
    assert result.review_required is True
```

- [ ] **Step 2: Run the test**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py::test_llm_formula_is_never_final_authority_for_claim_amount -q
```

Expected:

```text
FAILED
```

If the test already passes, keep it as a regression test.

- [ ] **Step 3: Change pipeline behavior**

In `src/claim_calculation/pipeline.py`, replace the branch that executes LLM formula code with this behavior:

```python
if not use_deterministic_calculation and plan.decision == "calculable" and plan.formula_intent:
    review_required_from_llm_formula = True
    sandbox_code = "# LLM formula ignored: calculation rules must come from approved rule table"
    payable_val = baseline_payable_val
    deductible_val = baseline_deductible_val
    deterministic_line_results = baseline_line_results
    deterministic_review_reasons.extend(baseline_review_reasons)
    deterministic_review_reasons.append(
        "LLM 산식은 최종 계산 근거로 사용하지 않고 승인된 rule table 기반 결정론 계산값을 적용했습니다."
    )
```

Keep `execute_calculation()` and sandbox tests for legacy/test coverage, but do not let LLM-created code determine production payout.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py tests/test_claim_code_sandbox.py tests/test_claim_planner.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add src/claim_calculation/pipeline.py tests/test_claim_calculation_pipeline.py
git commit -m "fix(claim): prevent llm formulas from driving payouts"
```

## Task 4: Extract Source-Grounded Answer Builder

**Files:**
- Create: `src/rag/source_grounded_answers.py`
- Modify: `src/rag/pipeline.py`
- Test: `tests/test_source_grounded_answers.py`
- Test: existing clause-detail tests found by `rg -n "clause_detail|deterministic_guard" tests`

- [ ] **Step 1: Write tests for evidence-only answer construction**

Create `tests/test_source_grounded_answers.py`:

```python
from __future__ import annotations

from src.rag.source_grounded_answers import EvidenceAnswerRow, build_table_answer


def test_build_table_answer_uses_only_row_values():
    rows = [
        EvidenceAnswerRow(
            label="췌이식술-부분",
            values={"수가코드": "Q8061", "점수": "147,455.74"},
            source="심평원 p.638 chunk-hira-1",
        )
    ]

    answer = build_table_answer("췌이식술 수가코드", rows)

    assert "Q8061" in answer
    assert "147,455.74" in answer
    assert "Q8062" not in answer
    assert "심평원 p.638 chunk-hira-1" in answer


def test_build_table_answer_returns_none_without_rows():
    assert build_table_answer("근거 없는 질문", []) is None
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_source_grounded_answers.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.rag.source_grounded_answers'
```

- [ ] **Step 3: Add the answer builder**

Create `src/rag/source_grounded_answers.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceAnswerRow:
    label: str
    values: dict[str, str]
    source: str


def build_table_answer(question: str, rows: list[EvidenceAnswerRow]) -> str | None:
    if not rows:
        return None
    lines = ["제공된 구조화 근거에서 확인되는 범위로 답변드립니다.", ""]
    headers = ["항목"]
    for row in rows:
        for key in row.values:
            if key not in headers:
                headers.append(key)
    headers.append("출처")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [row.label]
        cells.extend(row.values.get(header, "") for header in headers[1:-1])
        cells.append(row.source)
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("위 표에 없는 값은 생성하지 않았습니다.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_source_grounded_answers.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Replace hardcoded RAG answer blocks**

In `src/rag/pipeline.py`:

- Keep the guard for clearly missing codes if it does not contain product values.
- Remove hardcoded rows for SOL 지급비율, 간장/췌장 이식수술, and 4세대/5세대 non-benefit comparison.
- Where those answers are needed, build `EvidenceAnswerRow` objects from GraphDB facts, HIRA chunks, clause_detail_rows, or approved rule rows and call `build_table_answer()`.

The replacement call should look like:

```python
from src.rag.source_grounded_answers import EvidenceAnswerRow, build_table_answer

rows = [
    EvidenceAnswerRow(
        label=row.label,
        values=row.values,
        source=row.source,
    )
    for row in source_rows
]
answer = build_table_answer(question, rows)
if answer:
    return answer
```

- [ ] **Step 6: Search for remaining question-specific answer values**

Run:

```bash
rg -n 'Q8061|Q8062|147,455|159,457|비중증 비급여 통원 50|최소 50,000|100% 후보|SOL 지급비율' src/rag src/api tests
```

Expected:

- Matches in tests are allowed.
- Matches in production answer strings are not allowed.

- [ ] **Step 7: Run RAG focused tests**

Run:

```bash
.venv/bin/python -m pytest tests -q -k 'clause_detail or deterministic_guard or source_grounded'
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

Run:

```bash
git add src/rag/source_grounded_answers.py src/rag/pipeline.py tests/test_source_grounded_answers.py
git commit -m "refactor(rag): build deterministic answers from source rows"
```

## Task 5: Move GraphRAG Extraction Markers Behind Practitioner Approval

**Files:**
- Create: `data/ontology/policies/graph_extraction_markers.schema.json`
- Create: `data/ontology/policies/graph_extraction_markers.active.json`
- Modify: `src/graph/extractors.py`
- Modify: `src/ontology/registry.py` if it is the nearest manifest loader
- Test: `tests/test_graph_extraction_marker_policy.py`

- [ ] **Step 1: Write marker policy tests**

Create `tests/test_graph_extraction_marker_policy.py`:

```python
from __future__ import annotations

import json

from src.graph.extractors import load_graph_extraction_markers


def test_load_graph_extraction_markers_filters_to_approved_rows(tmp_path):
    path = tmp_path / "markers.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "markers": [
                    {
                        "marker_id": "benefit_limit.manual_therapy",
                        "marker_type": "benefit_limit",
                        "terms": ["도수치료", "연간"],
                        "source_doc": "약관",
                        "source_chunk_id": "chunk-1",
                        "approval_status": "active",
                    },
                    {
                        "marker_id": "benefit_limit.unapproved",
                        "marker_type": "benefit_limit",
                        "terms": ["미승인"],
                        "source_doc": "약관",
                        "source_chunk_id": "chunk-2",
                        "approval_status": "pending",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    markers = load_graph_extraction_markers(path)

    assert [marker["marker_id"] for marker in markers] == ["benefit_limit.manual_therapy"]


def test_load_graph_extraction_markers_rejects_active_row_without_source(tmp_path):
    path = tmp_path / "markers.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "markers": [
                    {
                        "marker_id": "bad",
                        "marker_type": "benefit_limit",
                        "terms": ["도수치료"],
                        "source_doc": "",
                        "source_chunk_id": "",
                        "approval_status": "active",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    markers = load_graph_extraction_markers(path)

    assert markers == []
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_graph_extraction_marker_policy.py -q
```

Expected:

```text
ImportError
```

- [ ] **Step 3: Add marker schema**

Create `data/ontology/policies/graph_extraction_markers.schema.json`:

```json
{
  "version": 1,
  "required_marker_fields": [
    "marker_id",
    "marker_type",
    "terms",
    "source_doc",
    "source_chunk_id",
    "approval_status"
  ],
  "allowed_marker_type": [
    "benefit_limit",
    "deductible_marker",
    "required_document",
    "exclusion_marker",
    "claim_unit_marker"
  ],
  "allowed_approval_status": ["active", "pending", "held", "rejected"],
  "description": "Approved GraphRAG extraction markers. This file stores matching markers with source evidence, not product answer values."
}
```

- [ ] **Step 4: Add active marker manifest**

Create `data/ontology/policies/graph_extraction_markers.active.json`:

```json
{
  "version": 1,
  "markers": []
}
```

Start empty. Do not copy the old constants into active state without practitioner approval and source evidence.

- [ ] **Step 5: Implement marker loader**

Add this function to `src/graph/extractors.py` near the current marker constants:

```python
from pathlib import Path
import json


def load_graph_extraction_markers(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    markers = payload.get("markers", [])
    approved = []
    for marker in markers:
        if marker.get("approval_status") != "active":
            continue
        if not marker.get("source_doc") or not marker.get("source_chunk_id"):
            continue
        terms = marker.get("terms")
        if not isinstance(terms, list) or not all(isinstance(term, str) and term.strip() for term in terms):
            continue
        approved.append(marker)
    return approved
```

- [ ] **Step 6: Wire extractor to approved markers**

Replace direct iteration over `BENEFIT_LIMITS` and `DEDUCTIBLE_RULES` with approved markers loaded from:

```python
config.ROOT_DIR / "data" / "ontology" / "policies" / "graph_extraction_markers.active.json"
```

For the first pass, keep the previous constants only for tests by moving them under a test fixture. Production extraction should use the active marker manifest.

- [ ] **Step 7: Add candidate generation path instead of direct active insertion**

If the old constants are still useful, emit them as review candidates, not active markers.

Use the existing ontology review shape where possible. A marker candidate should include:

```json
{
  "candidate_id": "marker.benefit_limit.manual_therapy.<hash>",
  "candidate_type": "graph_extraction_marker",
  "representative_label": "도수치료 한도 marker",
  "approval_status": "pending",
  "source_doc": "약관",
  "source_chunk_id": "chunk id from evidence",
  "terms": ["도수치료", "연간"],
  "risk_flags": ["benefit_limit"],
  "requires_practitioner_approval": true
}
```

Do not auto-approve `graph_extraction_marker` candidates if `risk_flags` contains payout, exemption, reduction, limit, or claim calculation markers.

- [ ] **Step 8: Run marker tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_graph_extraction_marker_policy.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 9: Run graph tests**

Run:

```bash
.venv/bin/python -m pytest tests -q -k 'graph or ontology'
```

Expected:

```text
passed
```

- [ ] **Step 10: Commit**

Run:

```bash
git add data/ontology/policies/graph_extraction_markers.schema.json \
  data/ontology/policies/graph_extraction_markers.active.json \
  src/graph/extractors.py \
  src/ontology/registry.py \
  tests/test_graph_extraction_marker_policy.py
git commit -m "refactor(graph): require approved markers for extraction knowledge"
```

## Task 6: Full P0 Self-Inspection

**Files:**
- Modify: no production file unless inspection finds a real violation

- [ ] **Step 1: Search for hardcoded production values**

Run:

```bash
rg -n 'Decimal\("0\.[235]"|30000|50000|250000|200000|50000000|8000|100% 후보|Q8061|Q8062|159,457|147,455' src
```

Expected:

- No production hardcoded payout/deductible/limit answer values.
- If matches remain, each match must be a parser threshold, test-only guard, or non-insurance processing value. Otherwise remove it.

- [ ] **Step 2: Verify ontology approval boundary**

Run:

```bash
rg -n 'auto.*approve|auto_approve|risk_flags|graph_extraction_marker|benefit_limit|deductible' src/ontology scripts/ontology_review.py
```

Expected:

- Graph extraction marker candidates require practitioner approval.
- Auto approval does not approve payout, exemption, reduction, limit, or claim calculation rule candidates.

- [ ] **Step 3: Run focused test suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_claim_rule_registry.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_source_grounded_answers.py \
  tests/test_graph_extraction_marker_policy.py -q
```

Expected:

```text
passed
```

- [ ] **Step 4: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit self-inspection report**

If a short report is required by `AGENTS.md`, create `docs/247_P0_SOURCE_GROUNDED_KNOWLEDGE_REMOVAL_REPORT.md` with:

```markdown
# 247. P0 Source-Grounded Knowledge Removal Report

## 변경 파일

## 핵심 변경

## 000번 원칙 점검

## 검증 명령과 결과

## 남은 위험
```

Then run:

```bash
git add docs/247_P0_SOURCE_GROUNDED_KNOWLEDGE_REMOVAL_REPORT.md
git commit -m "docs: summarize p0 knowledge removal work"
```

## Self-Review

- Spec coverage: P0 calculation rule externalization, deterministic answer block removal, and GraphRAG extractor knowledge policy are covered.
- Placeholder scan: No task leaves unspecified production behavior; every new module has concrete tests and minimal code.
- Type consistency: `ClaimRuleRegistry`, `ClaimDeductibleRule`, `EvidenceAnswerRow`, and marker payload names are defined before later tasks use them.
