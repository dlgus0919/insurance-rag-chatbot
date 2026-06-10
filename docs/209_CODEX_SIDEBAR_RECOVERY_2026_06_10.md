# Codex Sidebar Recovery Report - 2026-06-10

## Summary

Codex Desktop sidebar visibility was investigated for this project. Public reports in `openai/codex` indicate that hidden or stale sidebar histories can occur while local thread data remains intact. The closest matching symptom is that search can still find threads and pinning makes them visible, but unpinning hides them again.

## Local Findings

- `~/.codex/state_5.sqlite` contained project thread rows for this repository.
- The project had many active thread metadata fields with very large `title`, `first_user_message`, and `preview` values.
- The local DB project `cwd` and the Codex global active workspace root pointed to the same path but used different Unicode normalization forms, so exact string matching failed before repair.
- `thread-workspace-root-hints` in `.codex-global-state.json` had too few entries and was overwritten by the running app after manual repair, matching public reports that global UI state can be restored from app memory.

## Actions Taken

- Created local backups before mutation:
  - `/private/tmp/codex_state_5_before_sidebar_repair.sqlite`
  - `/private/tmp/codex_global_state_before_sidebar_repair.json`
  - `/private/tmp/codex_global_state_bak_before_sidebar_repair.json`
- Pinned key recovery/current project threads through the official Codex thread API.
- Compacted oversized sidebar metadata for active project threads only:
  - `title`
  - `first_user_message`
  - `preview`
- Preserved transcript history; rollout/session files were not deleted.
- Normalized the affected project `cwd` values in `state_5.sqlite` to match the active workspace root string used by Codex Desktop.

## Verification

- `PRAGMA integrity_check` returned `ok`.
- Active project thread metadata now has no oversized `title`, `first_user_message`, or `preview` fields under the applied thresholds.
- Active project thread `cwd` now exactly matches Codex Desktop's active workspace root.
- Manual `thread-workspace-root-hints` repair did not persist while the app was running; Codex rewrote that state.

## Remaining Risk

- Codex Desktop may need a full quit and relaunch before the sidebar refreshes from the repaired DB.
- If the app continues to overwrite global UI state, a future fix may need to be done while Codex Desktop is fully closed.
- Some long historical thread titles were replaced with generated `Recovered Codex thread ...` titles; the underlying conversation history remains available in local session history.

## Follow-up Repair

After the initial repair, pinned user threads still disappeared from the project folder after unpinning. A second inspection found that active user threads for this project had drifted back to a Unicode-decomposed `cwd`, while Codex Desktop's active workspace root used a Unicode-composed path. This made exact path matching fail even though the displayed paths looked identical.

Additional actions:

- Archived project threads not used for at least one week, using `updated_at < 2026-06-03 00:00:00` as the cutoff.
- Used the official thread archive API where possible, and DB `archived` flags for not-loaded historical threads where the API had no app server manager.
- Normalized all remaining active user project thread `cwd` values to exactly match the active workspace root.
- Marked active project threads with blank `thread_source` as `user`.

Follow-up verification:

- Active project-equivalent threads: `39`.
- Active project threads older than the cutoff: `0`.
- Active project threads with non-exact `cwd`: `0`.
- Active project threads with blank `thread_source`: `0`.
- `PRAGMA integrity_check` returned `ok`.

## Restart Diagnosis

After deleting some archived chats from Codex settings and fully restarting Codex Desktop, the project folder still showed `No chats`.

The root cause is a Unicode normalization mismatch:

- The actual macOS directory entry returned by `os.getcwd()` is Unicode-decomposed (`NFD`) and has length `64`.
- Codex Desktop's saved and active project root in `.codex-global-state.json` is Unicode-composed (`NFC`) and has length `54`.
- Active user threads in `state_5.sqlite` are attached to the decomposed `cwd`.
- The visible project folder is keyed by the composed saved root.

Observed state after restart:

- Active project-equivalent threads: `34`.
- Active threads with exact saved-root `cwd`: `28`, but all were `subagent` threads.
- Active user threads with exact saved-root `cwd`: `0`.
- Active user threads still existed, but under the decomposed `cwd`.

This explains the UI symptom: search can find the thread because search is not constrained by the exact project-root key, but the project folder list returns empty because no active `user` thread has a `cwd` string exactly equal to the saved project root.

Deleting archived chats or restarting the app does not fix this because the mismatch is not caused by archived rows. It is caused by Codex Desktop storing project roots and thread working directories in different Unicode normalization forms for a Korean path.

## ASCII Root Migration

The project was migrated to an ASCII-only canonical root to avoid future Unicode normalization mismatches:

`/Users/june_kim/Projects/insurance-rag-chatbot`

Actions:

- Copied the full repository directory, including the dirty working tree and `.git`, from the Korean path to the ASCII path.
- Created backups before Codex state mutation:
  - `/private/tmp/codex_state_5_before_ascii_root_migration.sqlite`
  - `/private/tmp/codex_global_state_before_ascii_root_migration.json`
  - `/private/tmp/codex_global_state_bak_before_ascii_root_migration.json`
- Updated `~/.codex/state_5.sqlite` so all threads whose `cwd` was Unicode-equivalent to the old Korean project root now use the ASCII root.
- Updated `.codex-global-state.json` and `.codex-global-state.json.bak`:
  - `active-workspace-roots`
  - `electron-saved-workspace-roots`
  - `project-order`
  - `pinned-project-ids`
  - `electron-workspace-root-labels`
  - `thread-workspace-root-hints`

Migration verification:

- Migrated thread rows: `86`.
- New ASCII root exact thread rows: `86`.
- New ASCII root active thread rows: `35`.
- New ASCII root active user thread rows: `5`.
- Old Korean root-equivalent thread rows remaining: `0`.
- `PRAGMA integrity_check` returned `ok`.
- `.codex-global-state.json` parsed successfully as JSON.

## Final Cleanup

The remaining recurrence risks were removed after the ASCII root migration.

Actions:

- Replaced the remaining old Korean root strings in Codex global state main and backup JSON files.
- Backed up the JSON files before that cleanup:
  - `/private/tmp/.codex-global-state.json.before_old_root_string_cleanup_20260610_110147`
  - `/private/tmp/.codex-global-state.json.bak.before_old_root_string_cleanup_20260610_110147`
- Deleted the original Korean/NFD project directory:
  - `/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇`

Final verification:

- Original Korean project directory: missing.
- `.codex-global-state.json` old-root string hits: `0`.
- `.codex-global-state.json.bak` old-root string hits: `0`.
- Codex active workspace root: `/Users/june_kim/Projects/insurance-rag-chatbot`.
- `thread-workspace-root-hints` entries pointing at the ASCII root: `88`.
- `state_5.sqlite` integrity check: `ok`.
- SQLite rows with old Korean `cwd`: `0`.
- SQLite rows with new ASCII `cwd`: `89`.
- Active SQLite rows with new ASCII `cwd`: `38`.
- Active user SQLite rows with new ASCII `cwd`: `8`.
- New ASCII root size: `361M`.

External verification prompt, if the running Codex app rewrites global state after restart:

```text
You are verifying a completed Codex Desktop project-root migration.

Canonical project root:
/Users/june_kim/Projects/insurance-rag-chatbot

Old root that must not reappear:
/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇

Tasks:
1. Confirm the old root directory does not exist.
2. Parse ~/.codex/.codex-global-state.json and ~/.codex/.codex-global-state.json.bak as JSON.
3. Recursively search both JSON files for both NFC and NFD forms of the old root. Expected result: 0 hits.
4. Confirm active-workspace-roots contains only the canonical ASCII root for this project.
5. Confirm electron-saved-workspace-roots, project-order, pinned-project-ids, electron-workspace-root-labels, and thread-workspace-root-hints do not point to the old root.
6. Run PRAGMA integrity_check against ~/.codex/state_5.sqlite. Expected result: ok.
7. Confirm threads.cwd has 0 rows for both NFC and NFD forms of the old root.
8. Confirm the project still has active user threads under the canonical ASCII root.
9. Do not modify project source files. If Codex Desktop is open and rewrites global state, ask the user to fully quit Codex Desktop and rerun the cleanup while the app is closed.
```
