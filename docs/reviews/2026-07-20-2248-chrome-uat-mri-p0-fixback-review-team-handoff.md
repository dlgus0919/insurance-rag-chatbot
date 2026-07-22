# Chrome UAT MRI P0 fixback — Review Team handoff

## Review subject

- Protected checkout: `/srv/shared/projects/insurance-rag-chatbot`
- Protected base/deployed HEAD: `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5`
- Candidate worktree: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-chrome-uat-mri-p0-fixback-20260720`
- Candidate commit: `dc83002fe4c3b3da6f475a7ac4cd68c2885dac98`
- Candidate branch: `codex/chrome-uat-mri-p0-fixback-20260720`
- Candidate report: `docs/290_CHROME_UAT_MRI_P0_ROUTE_FIXBACK_REPORT.md`

Review the exact diff `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5..dc83002fe4c3b3da6f475a7ac4cd68c2885dac98`. Do not integrate, restart, push, rebuild data, or modify protected state during review.

## Operational failure that triggered this review

Chrome UAT used the deployed web UI, a new chat, general mode, selected 4th generation, and the exact question:

> 4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?

The final visible bubble was `제공된 문서에서 확인되지 않습니다.` even though the previously reviewed direct `/api/v2/query` smoke returned the 4th-generation limit. The browser path was therefore stopped as P0.

Read-only audit evidence established:

1. The browser posted `/api/chat/stream` with `mode=general`, `policy_generation=4th`, `index_mode=v2_only`, and a new session.
2. The running API and served ES modules matched protected HEAD; no stale frontend bundle or alternate API image was involved.
3. The server classified the question as `policy_attribute_lookup`, but `requires_clause_lookup` changed the route to `formal` before direct policy-attribute retrieval ran.
4. The formal path produced zero sources and the public fallback sentence.
5. Generation loss and history contamination were excluded.

## Candidate intent and scope

The candidate keeps an already classified pure `policy_attribute_lookup` on the existing `general` direct-retrieval lane. It must not contain an MRI-specific, procedure-specific, generation-specific, amount-specific, document-specific, or chunk-specific exception.

Changed paths:

- `src/rag/query_router.py`
- `tests/test_api_chat_stream.py`
- `tests/test_query_router.py`
- `tests/test_search_intent.py`
- `docs/290_CHROME_UAT_MRI_P0_ROUTE_FIXBACK_REPORT.md`

## Mandatory review assertions

### Route and payload contract

- The actual UI payload shape for `/api/chat/stream` is covered.
- Pure policy-attribute lookup reaches direct retrieval without entering formal context first.
- Selected generation is preserved through retrieval, source selection, and the recorded resolved route/intent.
- The same UI payload is processed twice for 4th generation and twice for 5th generation without cross-generation contamination.

### Expected policy-attribute outcomes

- 4th-generation MRI/MRA annual limit: `300만원`.
- 5th-generation MRI/MRA annual limit: `200만원`, repeatable on two runs.
- Direct comparison: 4th `300만원`, 5th `200만원`.

### 000-principle and intent boundaries

- No exact-query or medical-term hardcoding.
- Natural-language attribute questions remain generic policy-attribute lookups.
- Coverage, claim-condition, payment-judgment, and calculation questions retain their existing intent/clarification boundaries.
- In particular, `5세대 MRI 연간 보장되나요?` and `5세대 MRI 보상한도 지급 여부는?` must not be silently converted into a pure numeric-attribute answer when additional judgment is required.

### Public answer and source contract

- Internal route/review/metadata markers are not exposed in the final bubble.
- Public source preview remains bounded to 180 characters.
- Source hover still reveals the relevant chunk.
- Source click still opens the original PDF in a new tab/window and targets the cited page.

### Data and runtime boundaries

- No GraphDB, ontology, active calculation rule/manifest, raw source, account, chat, audit, or protected DB mutation.
- No protected checkout integration, runtime restart, or push during review.
- Candidate worktree must remain clean.

## Developer evidence to independently reproduce

- UI-like API RED before fix: failed as expected because guarded formal context was reached.
- UI-like API GREEN after fix: `1 passed`.
- Focused router/intent/graph planner/pipeline/chat stream/API payload: `198 passed, 1 warning`.
- Full Python suite with temporary DB/lock and active manifest: `1177 passed, 3 warnings`.
- Node tests: `50 passed`.
- Chat syntax, frontend production build, and `git diff --check`: passed.
- Frontend production bundle was unchanged.

The isolated actual-v2-index smoke used a byte copy with a different inode. It reached filtering but exposed existing mixed or empty `policy_generation` metadata among raw hits, so an assertion that every hit had a generation failed. A lighter canonical-source check returned exactly one selected-generation direct candidate with the expected amount. Treat this as a remaining diagnostic boundary: verify whether the candidate's final selected source and response are correct without broadening the product patch to normalize every raw hit.

## Required disposition

Return exactly one of:

- `PASS`: candidate is suitable for a separate protected-main promotion gate and subsequent Chrome UAT.
- `CHANGES_REQUESTED`: list only reproducible defects, with file/line or command evidence and a minimal correction scope.
- `BLOCKED`: state the unavailable evidence and why safe review cannot proceed.

Completion marker:

`REVIEW_TEAM_CHROME_UAT_MRI_P0_FIXBACK_PASS_OR_CHANGES_REQUESTED`
