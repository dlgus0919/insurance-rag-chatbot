# DGX Login-time Large Model Switch Report

Date: 2026-05-20

## Summary

Implemented a single-slot SGLang model loading flow for the Streamlit app. Instead of keeping multiple large SGLang models resident at the same time, the login screen now lets the user choose one large local model. After login, the app switches the single SGLang slot to the selected model through an allowlisted operational wrapper.

## Why This Change Was Needed

Running `gpt-oss-20b` and `gemma-4-26b-a4b-nvfp4` concurrently caused memory pressure and startup failures. The expected usage is at most a few users, so loading one large model per session target is safer than splitting GPU/unified memory between multiple large SGLang servers.

## Implemented Behavior

- Login screen includes a `대형 로컬 모델` selector.
- Supported large SGLang candidates are discovered from config and `/srv/ai-ops/llm/models`.
- After login, Streamlit calls `/srv/ai-ops/bin/switch-sglang-model <model>` only with an allowlisted model name.
- The switcher kills the previous SGLang session and starts the requested model on `127.0.0.1:30000`.
- The sidebar still keeps small/local fallback model selection through Ollama.
- `OFFLINE_MODE=true` still hides OpenAI Cloud.

## Operational Wrapper

Created:

```text
/srv/ai-ops/bin/switch-sglang-model
```

Allowed models:

- `gpt-oss-20b`
- `gemma-4-26b-a4b-nvfp4`

The wrapper performs fixed path/template selection and does not accept arbitrary shell commands.

## Gemma4 Runtime Findings

Gemma4 handoff assets are present at:

```text
/srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4
```

Observed results:

- Weight loading succeeds.
- SGLang server reaches `/v1/models`.
- Initial generation failed because SGLang 0.5.12 ModelOpt NVFP4 activation mapping did not include `gelu`.
- Applied local venv patch to add `gelu -> ActivationType.Gelu` in SGLang ModelOpt/FlashInfer mapping.
- After patch, `/v1/chat/completions` returns HTTP 200.
- However, first text smoke generated repeated `<pad>` tokens, so Gemma4 remains a validation candidate, not a production default.

Patched runtime files, outside Git:

```text
/srv/shared/projects/insurance-rag-chatbot/.venv-sglang/lib/python3.12/site-packages/sglang/srt/layers/quantization/modelopt_quant.py
/srv/shared/projects/insurance-rag-chatbot/.venv-sglang/lib/python3.12/site-packages/sglang/srt/layers/moe/moe_runner/flashinfer_trtllm.py
```

Backups were saved next to each file with `.bak-gemma4-gelu` suffix.

## Current Recommendation

- Use `gpt-oss-20b` as the default large local SGLang model.
- Use Gemma4 only for controlled validation until the `<pad>` generation issue is resolved by a newer SGLang/FlashInfer/ModelOpt build or a model-specific runtime setting.
- Keep Ollama `exaone3.5:7.8b` available as the small local fallback.

## Verification

- `gpt-oss-20b` switcher path: PASS.
- Gemma4 load path: starts after local `gelu` runtime patch.
- Gemma4 response quality smoke: FAIL, repeated `<pad>` tokens.
- UI code compiles and login selector is implemented.
