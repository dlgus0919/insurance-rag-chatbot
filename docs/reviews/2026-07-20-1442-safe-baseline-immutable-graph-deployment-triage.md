# Safe-baseline immutable Graph fix — protected deployment triage

## Approval evidence

- Candidate commit: `44beca55a9ba4416babe016f801789969db79ac1`
- Candidate workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-safe-baseline-immutable-graph-20260720`
- Review verdict: `PASS`
- Review marker: `REVIEW_TEAM_SAFE_BASELINE_IMMUTABLE_GRAPH_FIX_COMPLETE`
- Review handoff: `docs/reviews/2026-07-20-1430-safe-baseline-immutable-graph-review-team-handoff.md`

## Protected integration gate

1. Confirm protected checkout `/srv/shared/projects/insurance-rag-chatbot` is `master`, exactly `e32f56ee29fdf974976ecbec3b70d8f533bfa01d`, and clean using the writable `ai-hang` route.
2. Confirm candidate commit and its parent exactly match the approved target.
3. Cherry-pick only `44beca55a9ba4416babe016f801789969db79ac1`.
4. Confirm the resulting commit contains only:
   - `src/graph/retriever.py`
   - `tests/test_graph_retriever.py`
   - `docs/283_SAFE_BASELINE_IMMUTABLE_GRAPH_FIX_REPORT.md`
5. Run `git diff --check`, focused `7`, safe-baseline combined `33`, and Graph/API/calculation upper regression `190` suites against the integrated commit.
6. Stop and roll back the source integration if the preflight, scope, or regression contract fails.

## Runtime publication gate

Current running API safe root:

`/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0`

Create a new sibling runtime root:

`/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2`

Rules:

- Never edit the existing v1.2.0 runtime root in place.
- Never delete or modify its existing `insurance_graph.sqlite-wal` or `insurance_graph.sqlite-shm` files.
- Byte-copy the verified regular artifacts into the new root while excluding both SQLite sidecars.
- The new Graph DB must have a different inode from v1.2.0 and SHA-256:
  `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`.
- The new root must contain zero `-wal`/`-shm` files before activation.
- Verify SQLite `integrity_check=ok`, `foreign_key_check` empty, Graph manifest consistency, ontology artifacts, pending-corrections/reports, and frozen calculation boundary hashes.
- Do not rebuild GraphDB, ontology, or calculation rules. This is a byte-copy publication only.

## API-only switch

1. Record the existing API PID, health, model/provider, safe-root environment, and rollback command.
2. Do not stop, switch, or reload SGLang/LLM.
3. Start the app with the existing provider/model and `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT` explicitly set to the new r2 root, using the existing `ops/bin/insurance-rag-up` lifecycle contract.
4. Only the FastAPI/SPA listener on `127.0.0.1:18080` may be replaced.
5. Verify health, active model/provider, safe-root environment, protected HEAD, Graph hash, and sidecar count after repeated Graph queries.
6. The r2 root must still have zero sidecars after repeated API/Graph queries and after one API-only restart.
7. On any failure, restore the previous v1.2.0 safe-root environment and API process. Preserve both runtime roots for inspection.

## Boundaries

- No push, tag, release, Graph/ontology rebuild, active calculation-rule change, user-data change, or UAT workbook edit in this task.
- Do not start full-stack preparation or change LLM state.
- Report the protected integration commit, exact regression results, old/new runtime identities and hashes, API PID transition, health checks, sidecar counts, rollback readiness, and residual risks.

Completion marker: `DEVELOPER_SAFE_BASELINE_IMMUTABLE_GRAPH_DEPLOYMENT_COMPLETE_NO_PUSH`
