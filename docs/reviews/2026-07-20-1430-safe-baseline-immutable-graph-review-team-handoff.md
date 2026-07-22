# Safe-baseline immutable Graph fix — Review Team handoff

## Review target

- DGX isolated workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-safe-baseline-immutable-graph-20260720`
- Branch: `codex/safe-baseline-immutable-graph-fix-20260720`
- Base/protected-main commit: `e32f56ee29fdf974976ecbec3b70d8f533bfa01d`
- Candidate commit: `44beca55a9ba4416babe016f801789969db79ac1`
- Candidate worktree: clean
- Protected main: `master`, `e32f56ee29fdf974976ecbec3b70d8f533bfa01d`, clean
- Source triage: `docs/reviews/2026-07-20-1336-safe-baseline-immutable-graph-fix-triage.md`

## Exact candidate scope

1. `src/graph/retriever.py`
2. `tests/test_graph_retriever.py`
3. `docs/283_SAFE_BASELINE_IMMUTABLE_GRAPH_FIX_REPORT.md`

No protected-main integration, runtime-root replacement, API restart, push, tag, or release has been performed.

## Developer evidence to verify independently

- RED: safe-baseline Graph queries captured `(readonly=True, immutable=False)` twice.
- GREEN: safe-baseline Graph queries capture `(True, True)` twice and create no `-wal`/`-shm` sidecars.
- Mutable/local Graph query remains `(True, False)`.
- Focused: `7 passed`; safe-baseline combined: `33 passed`.
- Graph/API/calculation upper regression: `190 passed, 1 warning`.
- `git diff --check`: pass.
- Operational Graph SHA-256 unchanged:
  `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`.
- Frozen calculation boundaries unchanged:
  - `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
  - `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
  - `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`

## Mandatory review questions

1. Is the fix a general safe-baseline runtime rule, with no MRI, hair-loss, disease, or test-sentence product hardcoding?
2. Does it enable immutable mode only for the exact Graph file resolved from the configured safe-baseline runtime root?
3. Are symlink, relative-path, missing-path, permission, and `Path.resolve()` failure behaviors safe and compatible with fail-closed operation?
4. Does mutable/local Graph behavior remain unchanged?
5. Do repeated real SQLite queries remain sidecar-free without deleting production sidecars or weakening validation?
6. Are GraphDB data, ontology, the six MRI query-patch files, active calculation rules, user data, and UAT artifacts untouched?
7. Are the new tests non-domain-specific enough to enforce the connection contract rather than merely one sample answer?
8. Does the exact commit contain only the three declared files, pass `git diff --check`, and leave the isolated worktree clean?

## Review boundary

Review is strictly read-only. Do not edit files, commit, cherry-pick, integrate into protected main, change runtime data/config, restart services, push, tag, or release.

Return one verdict: `PASS`, `CHANGES_REQUIRED`, or `BLOCKED`, with exact commands, results, findings, and residual risks.

Completion marker: `REVIEW_TEAM_SAFE_BASELINE_IMMUTABLE_GRAPH_FIX_COMPLETE`
