# DGX Offline Asset Preparation Implementation Report

Date: 2026-05-20

## Summary

Implemented a DGX-native offline asset preparation workflow so the insurance RAG chatbot can run in a fully offline or segmented network environment after one online preparation step.

## Repository Changes

- Added `scripts/prepare_offline_assets.py`.
- Updated `.env.example` so DGX defaults point to local offline model paths and SGLang as the local provider.
- Updated `docs/DGX_SPARK_RUNBOOK.md` with the complete offline preparation and verification workflow.

## DGX Operational Changes

These files are runtime assets under `/srv/ai-ops` and are intentionally not committed to Git:

- `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`
- `/srv/ai-ops/manifests/insurance-rag-offline-assets.json`
- `/srv/ai-ops/bin/run-insurance-rag` now sources `offline.env` after the private `env.sh` when it exists.
- `/srv/ai-ops/bin/check-insurance-rag` now reports offline asset presence.
- `/srv/ai-ops/bin/check-sglang-local` now validates SGLang through the project client, including GPT-OSS final response extraction.

## Prepared Assets

| Asset | Source | Target | Status | Required file check |
|---|---|---|---|---|
| embedding | `BAAI/bge-m3` | `/srv/ai-ops/models/embedding/bge-m3` | downloaded | config.json=OK, modules.json=OK |
| reranker | `BAAI/bge-reranker-v2-m3` | `/srv/ai-ops/models/reranker/bge-reranker-v2-m3` | downloaded | config.json=OK |
| llm | `openai/gpt-oss-20b` | `/srv/ai-ops/llm/models/gpt-oss-20b` | skipped_existing | config.json=OK, tokenizer.json=OK |
| gpt_oss_chat_template | `openai/gpt-oss-20b:chat_template.jinja` | `/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja` | skipped_existing | gpt_oss_harmony.jinja=OK |

## Offline Runtime Defaults

The generated `offline.env` sets:

```env
OFFLINE_MODE=true
HF_MODEL_DOWNLOAD=false
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3
RERANKER_ENABLED=true
LOCAL_LLM_PROVIDER=sglang
SGLANG_BASE_URL=http://127.0.0.1:30000/v1
SGLANG_DEFAULT_MODEL=gpt-oss-20b
SGLANG_REASONING_EFFORT=low
ALLOW_OLLAMA=true
OLLAMA_MODEL=exaone3.5:7.8b
```

No secrets are written into `offline.env`.

## Verification Results

- `scripts/prepare_offline_assets.py`: completed successfully.
- Embedding offline load: PASS.
- Reranker offline load: PASS.
- `/srv/ai-ops/bin/check-sglang-local`: PASS, returned final Korean response through project client.
- `pytest -q`: `260 passed, 3 warnings`.
- Offline OCR retrieval eval: `retrieval recall@8 = 1.000` with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `OFFLINE_MODE=true`.
- Chroma count remains `7,825`.
- `data/processed/chunks.jsonl` remains `7,825` lines.

## How To Re-run

When adding a new DGX or refreshing local model assets:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python scripts/prepare_offline_assets.py
```

Use `--force` only when an asset must be re-downloaded. Use `--skip-llm` if `gpt-oss-20b` is already staged and only embedding/reranker assets should be prepared.

## Residual Notes

- Full offline operation assumes the existing local indexes under `data/index/` and `data/processed/chunks.jsonl` remain present.
- SGLang must be running separately through `/srv/ai-ops/bin/run-sglang-local` for the SGLang provider to answer.
- Ollama `exaone3.5:7.8b` remains available as a local fallback provider.
