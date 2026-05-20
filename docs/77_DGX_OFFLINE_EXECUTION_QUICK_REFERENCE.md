# DGX Offline Execution Quick Reference

Date: 2026-05-20

## Purpose

This note records the shortest operational path for running the insurance RAG chatbot after the offline asset workflow has been prepared. It assumes all commands are run on DGX Spark as `ai-hang` and the main project directory is `/srv/shared/projects/insurance-rag-chatbot`.

## One-time Online Preparation

Run this only while DGX has internet access, or when refreshing model assets.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python scripts/prepare_offline_assets.py
```

The script prepares:

- `/srv/ai-ops/models/embedding/bge-m3`
- `/srv/ai-ops/models/reranker/bge-reranker-v2-m3`
- `/srv/ai-ops/llm/models/gpt-oss-20b`
- `/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja`
- `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`
- `/srv/ai-ops/manifests/insurance-rag-offline-assets.json`

## Normal Offline Startup

Start SGLang first, then Streamlit.

```bash
/srv/ai-ops/bin/run-sglang-local
```

In another shell:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

`run-insurance-rag` sources the private `env.sh` first and then `offline.env` when it exists, so the default DGX runtime is now offline-first.

## Local Access From Mac

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

Then open:

```text
http://localhost:8501
```

## Health Checks

```bash
/srv/ai-ops/bin/check-sglang-local
/srv/ai-ops/bin/check-insurance-rag
```

Expected core values:

- SGLang model: `gpt-oss-20b`
- Chroma count: `7825`
- chunks line count: `7825`
- Offline env: `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`

## Retrieval Regression Check

```bash
cd /srv/shared/projects/insurance-rag-chatbot
CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   OFFLINE_MODE=true RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9   EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3   RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3   .venv/bin/python scripts/eval.py --ocr
```

Expected result:

```text
retrieval recall@8: 1.000
```

## Provider Selection Rule

The Streamlit UI separates provider and model selection.

- Use `SGLang` for large Hugging Face/Safetensors models staged under `/srv/ai-ops/llm/models`.
- Use `Ollama` for models already present in the Ollama runtime, typically GGUF-backed models such as `exaone3.5:7.8b`.
- Use `OpenAI` only when `OFFLINE_MODE=false` and cloud access is intentionally enabled.

A model is not automatically portable across providers. The same model family can be compared across providers only when compatible artifacts exist for both sides, for example SGLang safetensors and Ollama GGUF/Modelfile variants.

## Fallback

If SGLang is unavailable, choose the Ollama provider in the UI or set:

```bash
LOCAL_LLM_PROVIDER=ollama
OLLAMA_MODEL=exaone3.5:7.8b
```

Ollama remains local and offline-capable as long as the model has already been pulled into the DGX Ollama store.

## Notes For Future Model A/B Tests

For each new model, record:

- provider compatibility: SGLang, Ollama, or both
- local path or Ollama model name
- required chat template or tokenizer override
- first-token latency and tokens/sec
- Korean insurance QA smoke results
- table/reference citation accuracy
- memory pressure and restart/OOM behavior

Gemma-family NVFP4 models should be treated as SGLang-first candidates until an Ollama-compatible GGUF or Modelfile path is separately validated.
