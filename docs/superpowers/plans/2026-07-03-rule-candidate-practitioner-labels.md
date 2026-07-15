# Rule Candidate Practitioner Labels Implementation Plan

> Status: Historical implementation plan. The work was completed before this plan was published to the repository.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 페이지 지식 확장 탭의 계산 룰 후보명을 실무자가 이해할 수 있는 한국어 표현으로 표시한다.

**Architecture:** 내부 enum과 rule id는 그대로 유지하고, 관리자 UI 표시 직전에만 실무자용 라벨로 변환한다. 계산 지식 값은 새로 만들지 않고 기존 후보의 `proposed_rule` 필드와 원문 근거만 표시한다.

**Tech Stack:** Static JS admin UI, Node test runner, existing claim rule candidate review label conventions.

---

## Scope

- 변경 대상은 계산 룰 후보 표시 UI와 해당 프론트엔드 테스트로 제한한다.
- `generation`, `category`, `visit_type`, `facility_grade`, `rule_id` 등 내부 저장 값은 변경하지 않는다.
- 보상률/공제율/한도 같은 지식 값을 코드에 새로 하드코딩하지 않는다.

## Files

- Modify: `frontend/js/pages/admin.js`
- Modify: `tests/test_admin_knowledge_frontend.mjs`
- Reference only: `scripts/claim_rule_candidate_review.py`
- Optional verification only: `scripts/extract_claim_rule_candidates.py`

## Task 1: Add Display Formatter In Admin UI

- [ ] **Step 1: Add a failing frontend test**

Add a test case to `tests/test_admin_knowledge_frontend.mjs` that renders a rule candidate with:

```js
proposed_rule: {
  generation: '1th',
  category: 'unknown',
  visit_type: 'hospitalization',
  facility_grade: 'all',
  copay_ratio: '0.2',
  description: '1th unknown hospitalization: 본인부담금 20%',
}
```

Expected assertions:

```js
assert.ok(html.includes('1세대'));
assert.ok(html.includes('입원'));
assert.ok(html.includes('급여/비급여 미확정'));
assert.ok(html.includes('전체 의료기관'));
assert.ok(!html.includes('1th unknown hospitalization'));
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: the new test fails because `renderCandidateList()` currently uses `proposed_rule.description` as-is.

- [ ] **Step 3: Add minimal label helpers**

In `frontend/js/pages/admin.js`, add small local maps near `renderRuleCandidateContext()`:

```js
const RULE_GENERATION_LABELS = { '1th': '1세대', '2th': '2세대', '3th': '3세대', '4th': '4세대', '5th': '5세대' };
const RULE_CATEGORY_LABELS = { benefit: '급여', nonpay: '비급여', unknown: '급여/비급여 미확정' };
const RULE_VISIT_LABELS = { hospitalization: '입원', outpatient: '통원', unknown: '입원/통원 미확정' };
const RULE_FACILITY_LABELS = { all: '전체 의료기관', clinic: '의원', hospital: '병원', general_hospital: '종합병원', tertiary_hospital: '상급종합병원' };
```

Add `ruleLabel(value, labels)` and `ruleCandidateTitle(item)` helpers. The title should prefer structured fields over `description`:

```js
function ruleCandidateTitle(item) {
  const rule = item.proposed_rule || {};
  const parts = [
    ruleLabel(rule.generation, RULE_GENERATION_LABELS),
    ruleLabel(rule.category, RULE_CATEGORY_LABELS),
    ruleLabel(rule.visit_type, RULE_VISIT_LABELS),
    ruleLabel(rule.facility_grade, RULE_FACILITY_LABELS),
  ].filter(Boolean);
  const ratio = formatRulePercent(rule.copay_ratio || rule.payout_ratio);
  if (ratio) parts.push(`본인부담금 ${ratio}`);
  return parts.join(' · ') || rule.description || rule.rule_id || item.candidate_id || '-';
}
```

- [ ] **Step 4: Use formatter only for rule candidates**

Change `renderCandidateList()` title selection:

```js
const title = kind === 'rule'
  ? ruleCandidateTitle(item)
  : item.canonical_name || item.candidate_id || '-';
```

Keep ontology display unchanged.

- [ ] **Step 5: Run frontend test**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: all tests pass.

## Task 2: Improve Rule Candidate Detail Text

- [ ] **Step 1: Add test for detail context**

Add assertions that rule candidate HTML includes:

```js
assert.ok(html.includes('확인할 계산 조건'));
assert.ok(html.includes('원문 근거'));
assert.ok(html.includes('입원'));
assert.ok(html.includes('급여/비급여 미확정'));
```

- [ ] **Step 2: Replace raw-only context**

Update `renderRuleCandidateContext(item)` so it shows:

- `확인할 계산 조건`: 세대, 급여/비급여, 입원/통원, 의료기관 구분
- `제안 값`: 본인부담금 비율, 최소 공제금
- `원문 근거`: existing `evidence_text` or `source_clause`

Use existing CSS classes: `candidate-section`, `candidate-section-label`, `candidate-text`, `candidate-guide`.

- [ ] **Step 3: Keep raw evidence bounded**

Keep the existing 900-character cap for evidence text:

```js
String(evidence || '-').slice(0, 900)
```

- [ ] **Step 4: Run frontend test again**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: all tests pass.

## Task 3: Narrow Integration Check On DGX

- [ ] **Step 1: Patch DGX main repository**

Apply the same minimal changes to `/srv/shared/projects/insurance-rag-chatbot`.

- [ ] **Step 2: Run the same frontend test on DGX**

Run:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: pass.

- [ ] **Step 3: Optional live UI smoke**

If the app is already running, open the 관리자 페이지 지식 확장 탭 and confirm:

- 계산 룰 후보 card title no longer exposes `1th`, `outpatient`, `hospitalization`, `unknown`.
- Unknown fields are shown as `미확정`.
- Original evidence remains visible.

Do not restart LLM servers for this check.

## Self-Review Checklist

- [ ] Internal rule ids and enum values were not changed.
- [ ] No new dependency was added.
- [ ] No payout/copay knowledge value was introduced in code.
- [ ] Ontology candidate UI was not changed unintentionally.
- [ ] Rule candidate evidence remains visible for practitioner review.
- [ ] Frontend test covers the reported `1th unknown hospitalization` display bug.
