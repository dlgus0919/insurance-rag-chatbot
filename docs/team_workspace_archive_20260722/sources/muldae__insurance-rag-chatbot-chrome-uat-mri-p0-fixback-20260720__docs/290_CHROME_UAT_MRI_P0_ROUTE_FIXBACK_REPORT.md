# Chrome UAT MRI P0 Route Fixback Report

## Scope

- Candidate-only fixback. No protected checkout, runtime, GraphDB, ontology,
  active claim rule, source document, account, chat, or audit data was changed.
- The change is a generic routing rule for pure policy-attribute lookups. It
  contains no medical procedure, generation, amount, document, or chunk-ID
  exception.

## Root Cause

The browser request reached the general chat endpoint with the UI-selected
generation and `v2_only` index mode. The recorded request classification was a
new general question with `policy_attribute_lookup`, but the route resolver
sent every clause lookup to the formal path before the direct policy-attribute
retrieval lane ran. The formal path returned no source, so the final response
used the generic unavailable-evidence fallback.

The investigation also confirmed that this was not caused by stale frontend
assets, session history, a missing generation field, or a different API image:

- The browser request payload included the selected generation and index mode.
- The running API used the protected checkout and served the current chat
  modules with no-cache headers.
- The selected-generation value was passed into the retrieval call.
- The canonical source lookup contains a selected-generation direct clause
  candidate for the affected attribute shape.

## Minimal Fix

`resolve_query_route()` now routes only the already-classified
`policy_attribute_lookup` intent through the existing general retrieval path.
That path invokes the direct policy-attribute lane before rank-based retrieval.
Quick-code routing remains first, while coverage, claim, calculation, and
other decision questions retain their existing non-attribute intent handling.

## Regression Coverage

- A stream API regression uses the same general-mode, selected-generation,
  `v2_only` payload shape sent by the UI. It exercises each selected generation
  twice. Before the route fix it reached a guarded formal context and failed;
  after the fix it reaches direct retrieval, keeps the selected generation,
  emits a source, and persists the resolved general route and policy-attribute
  intent.
- Router regressions keep pure attribute lookup on the direct retrieval path
  and preserve coverage-question classification.
- Existing pipeline, intent, graph-planner, API payload, and frontend tests
  cover selected 4th/5th direct limits, comparison-only dual-generation use,
  coverage-question clarification, bounded source preview, source PDF click,
  and non-exposure of internal review metadata.

## Verification

| Command scope | Result |
| --- | --- |
| API RED: same UI payload with guarded formal context | Failed before the fix as expected |
| API GREEN: same payload after the route fix | 1 passed |
| Router, intent, graph planner, pipeline, chat stream, API payload | 198 passed, 1 warning |
| Full Python suite with temporary DB/lock and active manifest | 1177 passed, 3 warnings |
| Node tests | 50 passed |
| Chat syntax check and frontend production build | Passed |
| `git diff --check` | Passed |

An isolated actual-v2-index smoke used a byte-copy whose SQLite inode differed
from the protected index. Its first full retrieval run reached the source
filter but failed the smoke assertion that every returned hit must carry a
generation value. A lightweight canonical-source check verified the direct
lane itself returns exactly one selected-generation direct clause candidate
with the expected selected-generation amount. The full smoke was not repeated
to avoid repeated index copying while the candidate fix and deterministic
regressions were completed. This leaves final browser UAT as a Review Team and
practitioner validation item.

## Boundaries And Remaining Risk

- The protected runtime was not integrated or restarted, and no push was made.
- The copied-index smoke created no protected SQLite sidecars; the temporary
  copy and worktree symlink were removed.
- The candidate must be reviewed with a real browser session after integration,
  because final LLM rendering and the protected request lifecycle are not
  exercised by this candidate-only work.
