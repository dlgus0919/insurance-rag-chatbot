# Safe-baseline immutable Graph runtime fix report

- Date: 2026-07-20
- Scope: safe-baseline runtime Graph query connection only
- Status: review candidate, not deployed

## Cause

The safe-baseline validator opened the published Graph snapshot with SQLite
`readonly=True, immutable=True`, while `GraphRetriever.retrieve()` opened the
same configured runtime Graph with `readonly=True` only. A non-immutable
read-only SQLite connection may create WAL/SHM sidecars, which subsequently
causes the existing fail-closed safe-baseline validation to reject the runtime
root on an API restart.

## Minimal change

- `GraphRetriever` now identifies the Graph path resolved from the configured
  safe-baseline runtime root.
- Only that exact Graph path is opened with `GraphStore(..., readonly=True,
  immutable=True)`.
- All other local or mutable Graph paths retain the existing
  `readonly=True, immutable=False` connection behavior.
- No sidecar deletion, validation relaxation, Graph rebuild, ontology change,
  calculation-rule change, or domain-specific exception was added.

## Regression evidence

A new SQLite regression begins with a WAL-capable copied test Graph without
sidecars and queries it twice through the configured safe-baseline path.

- RED before the implementation: the captured connection options were
  `[(True, False), (True, False)]`, while the required options were
  `[(True, True), (True, True)]`.
- GREEN after the implementation: the two safe-baseline queries use immutable
  read-only connections, no `-wal` or `-shm` file is created, and a local Graph
  query still captures `[(True, False)]`.

## Verification

```text
pytest tests/test_graph_retriever.py -q -p no:cacheprovider
7 passed in 0.11s

pytest tests/test_graph_retriever.py tests/test_safe_baseline.py -q -p no:cacheprovider
33 passed in 0.51s

pytest tests/test_graph_query_planner.py tests/test_api_chat_stream.py \
  tests/test_graph_retriever.py tests/test_api_rag_service_payload.py \
  tests/test_api_claim_calculation.py tests/test_claim_calculation_pipeline.py \
  tests/test_deductible_rules.py tests/test_graph_store.py -q -p no:cacheprovider
190 passed, 1 warning in 1.81s

git diff --check
passed
```

The focused and upper regressions were run in the isolated workspace. Before
and after each run, the operational Graph DB SHA-256 remained
`2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb` and
the following frozen calculation boundary hashes were unchanged:

- `claim_deductible_rules.active.json`:
  `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`:
  `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `processing_policy.py`:
  `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`

## Operational boundary and follow-up

The protected main checkout, active safe-baseline runtime root, API, LLM,
GraphDB data, ontology data, calculation rules, and user data were not changed.
No API restart, runtime replacement, push, tag, or release was performed.

The currently published runtime root retains its pre-existing sidecars and is
intentionally untouched. After review approval, deployment must byte-copy the
verified files into a new versioned runtime root with no sidecars, validate it,
then atomically switch the runtime-root configuration and restart the API only.
