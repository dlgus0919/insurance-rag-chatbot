# Streamlit Large Model Test Guide

Date: 2026-05-20

## Scope

This guide is for testing the Streamlit app from the administrator `ai-hang` workspace on DGX Spark.

Primary project path:

```bash
/srv/shared/projects/insurance-rag-chatbot
```

The app now uses a single SGLang serving slot for large local models. The large model is selected on the login screen, then Streamlit asks the DGX wrapper to load that model into SGLang.

## Current Model Policy

Large model slot, SGLang:

- `gpt-oss-20b`: current validated default.
- `gemma-4-26b-a4b-nvfp4`: staged validation candidate.

Small/local fallback, Ollama:

- `exaone3.5:7.8b`

Important current Gemma4 note:

- Gemma4 assets are present and SGLang can load the model after a local SGLang runtime patch.
- However, first generation smoke currently returns repeated `<pad>` tokens, so Gemma4 should be treated as a runtime validation candidate, not as the production default.
- Use `gpt-oss-20b` for normal functional testing.

## 1. SSH Into The Admin Workspace

From the Mac:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot; bash -l"
```

Check that the repo is the admin/main project directory:

```bash
pwd
git status --short
git rev-parse --short HEAD
```

Expected current commit at the time of this guide:

```text
9d974eb
```

## 2. Verify SGLang Status

Check the active SGLang model:

```bash
/srv/ai-ops/bin/check-sglang-local
```

Expected for normal testing:

```text
/v1/models includes gpt-oss-20b
```

If needed, switch back to the validated default:

```bash
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
```

Model switching can take several minutes because the previous SGLang session is stopped and the selected model is loaded from local disk.

## 3. Start Streamlit From The Admin Repo

In the DGX admin shell:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

This wrapper loads:

1. `/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh`
2. `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`

The second file makes the runtime offline-first by default.

## 4. Open The App From The Mac

In a separate Mac terminal:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

Open:

```text
http://localhost:8501
```

If port `8501` is already used by another workspace process, identify it on DGX:

```bash
pgrep -af "streamlit run src/ui/streamlit_app.py"
```

Use the admin/main repo process for final validation.

## 5. Login-time Large Model Selection

On the login screen:

1. Select `gpt-oss-20b` for normal testing.
2. Enter the app credentials.
3. Click login.

After login, the app verifies whether the selected SGLang model is active. If not, it calls:

```bash
/srv/ai-ops/bin/switch-sglang-model <selected-model>
```

Only allowlisted model names are accepted by the wrapper.

## 6. Sidebar Model Selection After Login

After login:

- The large SGLang model is already determined by the login screen.
- The sidebar can still be used to select available provider/model combinations.
- Ollama `exaone3.5:7.8b` remains available for small local fallback testing.

Expected normal options:

- `SGLang / gpt-oss-20b` when `gpt-oss-20b` is active.
- `Ollama / exaone3.5:7.8b` if Ollama is running.
- OpenAI is hidden while `OFFLINE_MODE=true`.

## 7. Recommended Smoke Tests

Run these with `gpt-oss-20b` first.

### General Question

```text
실손보험에서 통원 치료비 청구 시 일반적으로 확인해야 할 항목을 설명해줘.
```

Check:

- Korean answer is readable.
- Answer cites retrieved sources.
- No cloud/OpenAI warning appears.

### Quick Code / Procedure Search

Use `퀵 코드 검색` and ask a short procedure/code-oriented query.

Check:

- Results return quickly enough for interactive use.
- Source chunks are visible.

### Structured Policy Search

Use `약관 정형 검색`.

Check:

- Required fields work.
- Answer format remains consistent.
- Sources are attached.

### Ollama Fallback

Switch provider/model to Ollama if available:

```text
Ollama / exaone3.5:7.8b
```

Ask a short question and verify local fallback still responds.

## 8. Gemma4 Validation Test

Gemma4 can be selected from the login screen for controlled testing.

Expected current behavior:

- Model load may take several minutes.
- SGLang may report the model under `/v1/models`.
- Generated output may repeat `<pad>` tokens.

If Gemma4 returns `<pad>` output, record it as a model/runtime validation failure rather than an app failure.

Manual Gemma4 switch command:

```bash
/srv/ai-ops/bin/switch-sglang-model gemma-4-26b-a4b-nvfp4
```

Return to default after the test:

```bash
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
```

## 9. Logs To Check

Streamlit logs:

```bash
ls -lt logs/streamlit_*.log | head
```

SGLang logs:

```bash
tail -200 /srv/ai-ops/logs/sglang/sglang-local.log
```

Runtime checks:

```bash
/srv/ai-ops/bin/check-insurance-rag
/srv/ai-ops/bin/check-sglang-local
```

## 10. Pass Criteria

For `gpt-oss-20b`:

- Login succeeds.
- Streamlit reaches the chat UI.
- `SGLang / gpt-oss-20b` can answer at least one general Korean question.
- Source display works.
- Ollama fallback remains selectable and responds.
- No external OpenAI model is exposed in offline mode.

For Gemma4:

- Login selection and model switch path can be exercised.
- If output is `<pad>` repetition, mark Gemma4 as not ready for production answers.
- Do not use Gemma4 as the default until generation quality is fixed.
