# DGX SGLang Multi-model And Gemma4 Validation Report

Date: 2026-05-20

## Summary

Reviewed and improved the local LLM loading path so SGLang is the primary expansion path for large local models, while Ollama remains available only for models that are actually installed and supported by the Ollama runtime.

## Pipeline Review

Current loading path:

1. Streamlit calls `list_available_models()` from `src/llm/factory.py`.
2. UI separates `LLM Provider` and `LLM 모델`.
3. The selected value is stored as `provider:model`.
4. `_load_llm()` splits that selection and calls `build_llm()`.
5. `build_llm()` routes to:
   - `OpenAICompatibleClient` for SGLang
   - `OllamaClient` for Ollama
   - `OpenAIClient` only when `OFFLINE_MODE=false`

## Implemented Changes

- Added SGLang model discovery from `/srv/ai-ops/llm/models`.
- Added model-specific SGLang endpoint mapping through `SGLANG_MODEL_ENDPOINTS`.
- Added `SGLANG_STRICT_AVAILABLE_MODELS` so the UI can hide staged-but-not-running SGLang models.
- Updated SGLang labels to show model family, size, and validation status.
- Updated `OpenAICompatibleClient` so each model can use its own OpenAI-compatible base URL.
- Updated `scripts/prepare_offline_assets.py` so Gemma4 handoff assets are promoted before any network download attempt.
- Fixed `scripts/cli.py` so Ollama fallback uses `OLLAMA_MODEL` instead of the SGLang default model.
- Added tests for staged SGLang discovery and strict endpoint-based availability.

## Gemma4 Handoff Status

Found existing handoff assets at:

```text
/srv/shared/projects/insurance-rag-chatbot/handoff/llm_stage1_20260519/downloads/models/Gemma-4-26B-A4B-NVFP4
```

Promoted them to the DGX runtime path:

```text
/srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4
```

Verified non-invasive local checks:

- Runtime directory size: about `18G`.
- Required files present:
  - `config.json`
  - `tokenizer.json`
  - `model.safetensors.index.json`
  - `chat_template.jinja`
  - `hf_quant_config.json`
- Offline `AutoConfig` load: PASS.
- Offline `AutoTokenizer` load: PASS.
- Detected model type: `gemma4`.
- Detected architecture: `Gemma4ForConditionalGeneration`.
- Tokenizer chat template present: PASS.
- Vocab size: `262144`.

## Runtime Availability Behavior

`offline.env` now includes:

```env
SGLANG_CANDIDATE_MODELS=gpt-oss-20b,gemma-4-26b-a4b-nvfp4
SGLANG_MODEL_ENDPOINTS=gpt-oss-20b=http://127.0.0.1:30000/v1,gemma-4-26b-a4b-nvfp4=http://127.0.0.1:30001/v1
SGLANG_STRICT_AVAILABLE_MODELS=true
```

With strict mode enabled, the UI exposes only SGLang models that are actually reported by `/v1/models` on their mapped endpoint. Current observed UI availability:

```text
SGLang: gpt-oss-20b
Ollama: exaone3.5:7.8b
OpenAI: hidden in OFFLINE_MODE=true
```

Gemma4 is staged but hidden until its endpoint is running.

## Gemma4 Runtime Smoke Spec

The following check is intentionally not run automatically while `gpt-oss-20b` is serving, because loading both large SGLang models concurrently may create memory pressure. For controlled validation, run Gemma4 as a separate serving session, preferably after stopping competing large SGLang sessions.

```bash
/srv/ai-ops/bin/run-sglang-gemma4-local
```

Then verify:

```bash
SGLANG_BASE_URL=http://127.0.0.1:30001/v1 SGLANG_DEFAULT_MODEL=gemma-4-26b-a4b-nvfp4 /srv/ai-ops/bin/check-sglang-local
```

Minimum pass criteria:

- `/v1/models` reports `gemma-4-26b-a4b-nvfp4`.
- One non-streaming Korean answer completes.
- One streaming Korean answer completes without restart or OOM.
- First-token latency and total latency are recorded.
- No tokenizer/chat-template error occurs.

## Human Quality Validation Spec

After runtime smoke passes, compare `gpt-oss-20b` and Gemma4 on saved RAG answers for at least these cases:

1. General insurance question.
2. Quick code/procedure lookup.
3. Structured policy clause lookup.
4. Surgery grade numeric answer.
5. Disability rate numeric answer.
6. Cross-document answer requiring citations.

For each answer, record:

- factual correctness
- Korean fluency
- table/numeric accuracy
- citation format stability
- whether the answer follows the project system prompt
- hallucinated exclusions or invented policy language
- response latency

## Verification Performed

- `pytest -q`: `262 passed, 3 warnings`.
- Offline OCR retrieval eval: `retrieval recall@8 = 1.000`.
- `/srv/ai-ops/bin/check-sglang-local`: PASS for current `gpt-oss-20b` endpoint.
- `/srv/ai-ops/bin/check-insurance-rag`: reports Gemma4 assets as present.

## Operational Notes

- SGLang is the preferred provider for large Hugging Face/Safetensors/NVFP4 models.
- Ollama remains a fallback only for models installed in the Ollama runtime, currently `exaone3.5:7.8b`.
- The same model can be compared across SGLang and Ollama only if compatible artifacts exist for both providers.
