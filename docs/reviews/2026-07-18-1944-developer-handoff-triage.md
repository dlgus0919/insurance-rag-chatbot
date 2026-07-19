# Developer Handoff Triage — Release A Global Manifest Lock Fixback

- Timestamp: 2026-07-18 19:44 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Isolated DGX workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- Base/HEAD: `fa8d734d643d18d6983447978de2210819717bc6`
- Authoritative plan: `docs/superpowers/plans/2026-07-18-ontology-approval-integrity-containment.md`
- Developer report: `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md`

## Reported

- Developer completed Release A in the isolated workspace and left all changes unstaged and uncommitted.
- The implementation reports canonical manifest/base locking, field-level approval patches, trusted projection, runtime registry quarantine, Graph integrity metadata, dry-run audit, and a pending-only correction candidate.
- Reported verification includes `1033 passed`, focused suites, Node/admin tests, build, isolated E2E, protected GET-only smoke, and `git diff --check`.
- No active manifest apply, candidate approval, GraphDB rebuild, reindex, service restart, commit, or push was reported.

## Observed

- The isolated workspace is detached at `fa8d734`, matching its reported base.
- Workspace status contains exactly 39 implementation paths: 32 tracked modifications and 7 untracked files. There is no staged diff.
- Tracked diff size is 32 files, 2,200 insertions, and 410 deletions; `git diff --check` passes.
- Base lock, ontology schema, review policy, and pending correction artifact are valid JSON.
- The correction artifact remains `pending` and `test_candidate=false`.
- Current raw ontology projection retains 49 locked concepts and quarantines the same 6 unverified concepts reported by Developer.
- Automatic Codex development approval still requires pending status, source evidence, `test_candidate=true`, the development risk flag, and the explicit development-only review payload.
- Independent focused rerun passed: `23 passed in 0.09s` for `test_ontology_approval_integrity.py`, `test_ontology_manifest_merge.py`, and `test_ontology_registry.py`.

## Finding

### P1 — whole-manifest lock is not enforced by trusted projection/runtime audit

`manifest_content_hash()` intentionally includes `schema_version`, `description`, and `concepts`, excluding only generated `version`. The lock therefore claims to protect those top-level semantic fields as well as each concept.

However, `build_trusted_base_projection()` validates only per-concept hashes. It copies the current unreviewed top-level fields into the projection, sets state to `valid` whenever no concept issue exists, and records the lock hash without comparing the recomputed projection hash to it. `OntologyRegistry._load_base()` trusts that report directly. `audit_active_manifest()` also compares provenance to the stored lock hash rather than first proving that the current trusted projection actually has that hash.

Independent in-memory reproduction changed only `description` while keeping every concept byte-identical. The result was:

```text
state=valid
issues=[]
projection_hash_matches_lock=false
loaded_concepts=1
```

An active-manifest audit with internally consistent provenance over the drifted payload also returned:

```text
state=valid
issues=[]
active_hash != locked_hash
```

This violates the plan's canonical whole-manifest hash contract and means an unreviewed top-level semantic change can be treated as valid by runtime/audit even though merge happens to reject it later.

## Decision

`DEVELOPER_FIXBACK`

Do not route to Review Team yet. The implementation needs one bounded, domain-neutral fail-closed correction in the existing isolated workspace.

## Required fixback

1. Add failing regressions for both `description` and `schema_version` drift while all concept hashes remain unchanged.
2. Make trusted projection report a dedicated global/base manifest hash mismatch and a `stale` state when the complete locked concept set is present and valid but the recomputed trusted projection hash differs from the lock.
3. Ensure base `OntologyRegistry` exposes zero concepts for that global stale state.
4. Ensure `audit_active_manifest()` cannot return `valid` for the same top-level drift, even when active/provenance hashes are otherwise internally consistent.
5. Preserve the intended concept-level behavior for the current incident: six extra untrusted concepts remain quarantined, 49 trusted concepts remain usable, and the trusted projection hash still equals the lock. Do not turn this case into a global outage.
6. Keep the implementation domain-neutral. Do not add topic, disease, question-text, or concept-ID branches.
7. Update `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md` with the finding, correction, exact regression results, and unchanged operational boundary.

If the existing lock representation cannot distinguish top-level drift from a concept-level mismatch without weakening the current partial quarantine contract, stop and report the representational limitation instead of guessing or silently broadening the lock format.

## Verification gates

- New top-level drift tests fail before the fix and pass after it.
- Existing six-concept quarantine dry-run remains `quarantined`, retains 49 trusted concepts, and performs no apply.
- Existing approval-integrity focused suite and full `pytest -q` pass.
- Procedure grade, HIRA, MX122/claim calculation, session continuity, source-grounded answers, and admin Graph regressions remain passing.
- `git diff --check` passes.
- No active apply, candidate approval, GraphDB rebuild, reindex, API/LLM restart, protected-main edit, staging, commit, push, or Release B work occurs.
- The isolated workspace remains unstaged/uncommitted for Review Team inspection.

## Completion contract

On success, report exact changed paths and test counts, and finish with:

```text
DEVELOPER_RELEASE_A_FIXBACK_READY_FOR_REVIEW
```
