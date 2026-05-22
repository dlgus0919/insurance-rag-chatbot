# Streamlit Large Model Test Guide

Date: 2026-05-22

## Scope

This guide is for testing large local LLMs through the Streamlit app on DGX Spark.

Primary project path:

```bash
/srv/shared/projects/insurance-rag-chatbot
```

Before using this guide, read and follow:

```text
docs/103_STREAMLIT_RUNTIME_PREP_GUIDE.md
```

That document is the source of truth for pull-after setup, non-Git runtime files, OCR indexes, local model assets, and Streamlit launch commands.

## Current Provider Policy

The current app separates provider and model selection.

Recommended runtime policy:

```text
Streamlit app: CPU
RAG query embedding: CPU by default
Reranker: CPU by default
SGLang/vLLM large LLM: GPU 0
Batch index/embedding generation: GPU 0
```

Large local providers:

- `vLLM / gemma-4-26b-a4b-nvfp4`
- `SGLang / gpt-oss-20b`

Small/local fallback:

- `Ollama / exaone3.5:7.8b`

Cloud/OpenAI providers should be hidden while `OFFLINE_MODE=true`.

## Current Model Notes

### Gemma4 via vLLM

`gemma-4-26b-a4b-nvfp4` is now the main Gemma4 test target and is served through vLLM.

Important fixes already applied:

- vLLM readiness checks use `Authorization: Bearer EMPTY`.
- vLLM is launched with `--api-key EMPTY`.
- OpenAI-compatible streaming now handles non-Harmony streams, so Gemma4 `delta.content` tokens are displayed immediately.

### GPT-OSS via SGLang

`gpt-oss-20b` remains available through SGLang.

It uses GPT-OSS/Harmony-style final-channel parsing, so the OpenAI-compatible client keeps Harmony marker handling for this model family.

## Start Streamlit

From DGX:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
```

From the Mac in one command:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace"
```

Use a different port for a personal workspace:

```bash
cd /srv/shared/workspaces/<user>/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace --port 8502
```

## Open The App From The Mac

For the shared `8501` port:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

Open:

```text
http://localhost:8501
```

For a personal `8502` port:

```bash
ssh -L 8502:localhost:8502 <user>@100.88.5.57
```

Open:

```text
http://localhost:8502
```

## Runtime Checks

Streamlit:

```bash
ss -tlnp | grep ':8501'
```

vLLM Gemma4:

```bash
curl -s -H "Authorization: Bearer EMPTY" \
  http://127.0.0.1:30001/v1/models
```

SGLang GPT-OSS:

```bash
curl -s -H "Authorization: Bearer EMPTY" \
  http://127.0.0.1:30000/v1/models
```

GPU usage:

```bash
nvidia-smi
```

## Recommended Smoke Tests

### General Question

```text
로봇 수술의 코드를 알려주세요.
```

Expected:

- Answer body is generated.
- Retrieved source citations are shown below the answer.
- Exported chat has text after `[A1] [vllm:gemma-4-26b-a4b-nvfp4]`.

### Quick Code Search

Use `퀵 코드 검색` and ask a short procedure/code query.

Expected:

- Procedure/code-oriented result appears.
- Sources are visible.

### Structured Policy Search

Use `약관 정형 검색`.

Expected:

- Required fields work.
- Answer format remains consistent.
- Sources are attached.

### Claim Payout Calculation

Use `보험금 계산`.

Expected:

- Standard code DB lookup works.
- Ambiguous code matches are held for user selection.
- The result is labeled as `지급예상액`, not guaranteed payout.

### Ollama Fallback

Select:

```text
Ollama / exaone3.5:7.8b
```

Expected:

- The app can still answer without vLLM/SGLang.

## Stop Runtime

Stop Streamlit only:

```bash
pkill -f '[s]treamlit run src/ui/streamlit_app.py' || true
pkill -f '[r]un_offline_streamlit_test.sh' || true
```

Stop Gemma4/vLLM:

```bash
tmux kill-session -t vllm-gemma4 2>/dev/null || true
```

Stop SGLang:

```bash
tmux kill-session -t sglang-local 2>/dev/null || true
```

## Pass Criteria

- Login succeeds.
- Streamlit reaches the chat UI.
- Provider/model dropdown exposes the expected local providers.
- Gemma4/vLLM answers a Korean question with a non-empty body.
- GPT-OSS/SGLang remains usable if the SGLang server is active.
- Ollama fallback remains selectable when Ollama is running.
- No external OpenAI model is exposed in offline mode.
- General/quick-code/structured-policy/claim-calculation modes are usable.
