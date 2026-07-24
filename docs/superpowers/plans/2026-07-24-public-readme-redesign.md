# Public Portfolio README Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale operator-oriented README with a source-grounded public portfolio README that accurately describes the current `v1.2.b` baseline and post-release `master` state.

**Architecture:** Keep the change documentation-only. Build the README from facts verified in the remote source tree, current runtime wrappers, release reports and project guardrails; separate public project explanation from full DGX operational prerequisites and internal data.

**Tech Stack:** Markdown, Mermaid, Git, FastAPI, static SPA, BM25, Chroma, RRF, reranker, SQLite GraphDB, SGLang

## Global Constraints

- Primary audience: external public and portfolio visitors.
- Stable release tag: `v1.2.b`.
- Frontend display version: `1.2.0.b`.
- Current production UI: FastAPI plus static SPA.
- Default local model path: SGLang plus `qwen3-next-80b-a3b-instruct-fp8`.
- Optional local model: `gpt-oss-20b`.
- Do not expose credentials, user data, chat history, audit logs or internal absolute paths.
- Do not imply that raw documents, runtime indexes, models or `.env` are included in Git.
- Do not present Streamlit as the current production UI.
- Do not present OCR as the current intake path for new scanned documents.
- Do not add a license badge or redistribution claim because the repository has no license file.
- Preserve the existing dirty local workspace by implementing from a clean remote clone.

---

### Task 1: Rewrite the public README

**Files:**

- Modify: `README.md`
- Reference: `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`
- Reference: `docs/154_PROJECT_ARCHITECTURE_CURRENT_STATUS_REPORT.md`
- Reference: `docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md`
- Reference: `docs/268_ADMIN_GRAPHDB_3D_VISUALIZATION_REPORT.md`
- Reference: `docs/282_V1_2_0_B_QWEN_ALWAYS_HOTFIX_REPORT.md`
- Reference: `docs/283_V1_2_0_B_GRAPH_READ_HOTFIX_REPORT.md`

**Interfaces:**

- Consumes: repository-visible release, architecture, feature and safety facts
- Produces: one public Markdown entrypoint with valid relative links and balanced Mermaid fences

- [ ] **Step 1: Record the clean baseline**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
```

Expected: clean feature branch and matching `89bc12e5f5f2ab029d003ac7ff37e9960de74172` hashes.

- [ ] **Step 2: Validate the existing README structure**

Run a local-link check over every Markdown link, count code fences and run:

```bash
git diff --check
```

Expected: no missing existing local links, balanced fences and no whitespace errors.

- [ ] **Step 3: Replace the README**

Write these exact top-level sections in order:

1. project hero and status
2. project problem
3. core capabilities
4. user workflows
5. architecture
6. answer generation versus deterministic calculation
7. approval-based knowledge lifecycle and guardrails
8. technology stack
9. reproducibility boundary
10. developer quick start and verification
11. repository structure
12. release state and known limitations
13. selected documentation
14. security, usage and license notice

Use `assets/logo.svg`, two Mermaid diagrams, public relative links and the exact version terminology from the global constraints.

- [ ] **Step 4: Run README validation**

Run:

```bash
git diff --check
rg -n '현재 후보 릴리스: v1\.2\.0|Streamlit 앱 실행 성공|OpenAI API.*필수' README.md
```

Expected: `git diff --check` exits 0 and the stale-pattern search returns no matches.

Check every relative Markdown link and every image source against the worktree. Expected: zero missing targets.

- [ ] **Step 5: Review the content against the design**

Confirm all 14 required sections exist, `v1.2.b` and `1.2.0.b` are distinct, the full-runtime asset boundary is explicit, and no secret or internal path is present.

### Task 2: Verify and publish the documentation change

**Files:**

- Modify: `README.md`
- Create: `docs/superpowers/specs/2026-07-24-public-readme-redesign.md`
- Create: `docs/superpowers/plans/2026-07-24-public-readme-redesign.md`

**Interfaces:**

- Consumes: the reviewed README from Task 1
- Produces: a single source-grounded commit uploaded to remote `master`

- [ ] **Step 1: Inspect the exact diff**

Run:

```bash
git status --short
git diff -- README.md docs/superpowers/specs/2026-07-24-public-readme-redesign.md docs/superpowers/plans/2026-07-24-public-readme-redesign.md
```

Expected: only the README, design spec and implementation plan are changed.

- [ ] **Step 2: Recheck the remote head**

Run:

```bash
git ls-remote origin refs/heads/master
git rev-parse origin/master
```

Expected: both identify `89bc12e5f5f2ab029d003ac7ff37e9960de74172`. If the remote differs, fetch and re-review instead of pushing.

- [ ] **Step 3: Commit the intended files**

Run:

```bash
git add README.md \
  docs/superpowers/specs/2026-07-24-public-readme-redesign.md \
  docs/superpowers/plans/2026-07-24-public-readme-redesign.md
git commit -m "docs(readme): refresh public project overview"
```

Expected: one documentation commit with exactly three files.

- [ ] **Step 4: Verify the committed tree**

Run the README link, fence, stale-pattern and `git diff --check HEAD^ HEAD` checks again. Inspect:

```bash
git show --stat --oneline HEAD
git status --short --branch
```

Expected: validation succeeds and the worktree is clean.

- [ ] **Step 5: Upload to remote master**

Run:

```bash
git push origin HEAD:master
```

Expected: remote `master` advances from `89bc12e` to the documentation commit.

- [ ] **Step 6: Verify the remote result**

Run:

```bash
git ls-remote origin refs/heads/master
```

Expected: the returned hash equals the local committed `HEAD`.
