# Chrome UAT MRI P0 fixback — protected-main promotion triage

## Authority and gate

Review Team verdict is `PASS` in:

`/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-20-225511-chrome-uat-mri-p0-fixback-rereview.md`

This is a new, separate promotion gate. It authorizes only the exact candidate below to be applied to the protected DGX checkout, validated, and activated by an API-only restart. It does not authorize push, release tagging, GraphDB/ontology rebuild, rule promotion, raw-data changes, or user/chat/audit data manipulation.

## Exact inputs

- Protected checkout: `/srv/shared/projects/insurance-rag-chatbot`
- Expected protected HEAD: `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5`
- Candidate worktree: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-chrome-uat-mri-p0-fixback-20260720`
- Candidate commit to cherry-pick: `dc83002fe4c3b3da6f475a7ac4cd68c2885dac98`
- Expected API PID before activation: `4015169`
- Expected SGLang PID to preserve: `344387`
- Expected active model: `sglang:qwen3-next-80b-a3b-instruct-fp8`

Expected candidate paths are exactly:

- `src/rag/query_router.py`
- `tests/test_api_chat_stream.py`
- `tests/test_query_router.py`
- `tests/test_search_intent.py`
- `docs/290_CHROME_UAT_MRI_P0_ROUTE_FIXBACK_REPORT.md`

## Preflight stop conditions

Before any write, record and compare:

1. Protected HEAD and `git status --short`.
2. Candidate parent equals the expected protected HEAD and candidate diff contains only the five paths above.
3. API PID, SGLang PID, `/api/health`, and active model.
4. Active safe-baseline/runtime root and ontology status.
5. SHA-256 of frozen calculation/policy files, at minimum:
   - `src/calculation/processing_policy.py` expected `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
   - active deductible rules expected `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
   - active rule links expected `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
6. Graph/ontology manifest hash and operational `insurance_chat.db` body identity (hash/inode/size/mtime) without reading or printing user content.
7. Existing `insurance_chat.db-wal`/`insurance_chat.db-shm` may be present because the service is live. Record their presence only; do not remove, checkpoint, truncate, copy, or otherwise manipulate them.

Stop without cherry-picking if the protected HEAD is unexpected, protected source changes are present, the candidate chain/path set differs, the model/PID baseline is inconsistent, or frozen hashes differ without an explained pre-existing cause.

## Promotion procedure

1. Cherry-pick exactly `dc83002fe4c3b3da6f475a7ac4cd68c2885dac98` into protected `master`.
2. Do not stage or include any other file.
3. Before activation, run candidate-equivalent verification from protected main using temporary DB/lock/cache paths and the canonical active-manifest environment. Do not point tests at the operational chat DB.
4. Required minimum verification:
   - focused UI-like chat stream and route/intent regressions, including 4th/5th repeated payloads;
   - related RAG/API/public-payload/source-preview/PDF contract tests;
   - full Python suite;
   - full Node suite;
   - chat syntax, production frontend build, and `git diff --check`;
   - frozen hashes and protected diff path audit.
5. Treat the known r2-root manifest precedence test conflict only as an environment-only comparison if it reappears. Use the canonical active-manifest temporary DB/lock configuration that produced `1177 passed`; do not retry the raw quarantined-base configuration.
6. If and only if all gates pass, restart the API using the documented standard API-only replacement command with `--replace --skip-prepare --no-llm-switch` or the exact currently documented equivalent.
7. Do not restart, signal, reload, or switch SGLang/LLM.

## Postflight

After API activation, record:

- new protected HEAD and clean status;
- new API PID and successful health response;
- unchanged SGLang PID `344387` and active model;
- unchanged safe-baseline/runtime root, ontology status, Graph/ontology hash, frozen calculation/rule hashes, and operational DB body identity;
- no manually created or removed DB sidecars;
- exact test counts and any warnings;
- confirmation that no push occurred.

Do not perform the browser UAT in the Developer task. Planner will run Chrome after successful promotion.

## Required result

On success, report the resulting protected-main commit and marker:

`DEVELOPER_CHROME_UAT_MRI_P0_PROMOTION_COMPLETE_NO_PUSH`

On any mismatch or test failure, stop before API activation and report the exact blocker. Do not repair by broadening the patch or changing data, Graph, ontology, or active rules.
