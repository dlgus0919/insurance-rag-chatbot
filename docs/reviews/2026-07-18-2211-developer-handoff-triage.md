# Developer Handoff Triage — Release A Runtime Artifact Schema Fixback

- Timestamp: 2026-07-18 22:11 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Scope/spec: Release A ontology approval-integrity runtime artifact boundaries
- Isolated DGX workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-approval-integrity-20260718`
- Base/protected expected: `fa8d734d643d18d6983447978de2210819717bc6`
- Review report: `docs/reviews/2026-07-18-220207-release-a-artifact-boundary-rereview.md`

## Reported

- Review Team returned `CHANGES_REQUESTED` after independently closing the previous three findings.
- It reports two remaining generic artifact-boundary defects: unvalidated manifest/provenance top-level schema and silent removal of partially malformed base-lock concept hashes.
- It reports focused `126 passed, 1 warning`, full pytest `1064 passed, 3 warnings`, Node `15 passed`, frontend build passing, and isolated Playwright `1 passed`.
- It reports no implementation edit, protected request, operational write, restart, stage, commit, push, or deploy.

## Observed

- The immutable Review Team report exists and contains exact source ranges, reproductions, verification evidence, and a bounded fixback prompt.
- Planner independently reproduced both findings against the live isolated workspace:
  - adding an unknown top-level field to base or active manifests leaves `manifest_content_hash` unchanged and returns `valid`; active provenance can be recomputed to keep Registry/audit valid;
  - provenance `schema_version=0`, missing schema version, or an unknown top-level field all return `valid`;
  - a base lock containing one valid concept hash and one empty hash is accepted after the malformed row is silently removed.
- The ontology manifest JSON schema already declares `additionalProperties: false`, so the rogue manifest payload is invalid under the repository's declared contract even though runtime loading accepts it.
- The current implementation docstring says only generated manifest `version` is excluded from the content hash, but the implementation whitelists only schema/description/concepts and therefore excludes every other top-level field.
- Isolated workspace remains exactly 39 status paths, unstaged/uncommitted; `git diff --check` passes and HEAD equals `origin/master` at `fa8d734d643d18d6983447978de2210819717bc6`.

## Not Verified

- Planner did not repeat the Review Team full suite, Node, build, or Playwright checks because the two blocking boundary defects were directly reproduced and already determine routing.
- No operational promotion or practitioner approval was attempted.

## Findings

### P1 — runtime manifest/provenance schema validation is incomplete

The declared manifest schema rejects unknown fields, while runtime registry/direct audit accepts them. The content hash also contradicts its contract by dropping unknown top-level content. Provenance version/shape is not validated, allowing unsupported or incomplete artifacts to be accepted after internally consistent hash recomputation. This is a genuine fail-open approval-integrity boundary and blocks promotion.

### P2 — partially malformed base-lock concept hashes are normalized into a different accepted lock

`BaseManifestLock.from_dict()` silently filters malformed rows before validation. An integrity artifact must be validated without deleting declared entries; any non-string, empty key, or empty hash must reject the whole lock.

## Decision

`DEVELOPER_FIXBACK`

Only the two reproduced generic artifact-boundary findings are in scope. Operational promotion and Review Team re-routing remain blocked until the fixback is complete and independently re-reviewed.

## Dispatch

- Target thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Prompt: the bounded runtime artifact-schema fixback recorded in the routed Developer message for this timestamp.
