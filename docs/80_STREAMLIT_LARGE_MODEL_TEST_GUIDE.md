# Streamlit GraphRAG / Large Model Test Guide

Date: 2026-05-26

> 최신 팀원용 pull/run 절차는 `docs/121_TEAM_PULL_AND_STREAMLIT_RUN_GUIDE_DGX_SPARK.md`를 우선한다. 이 문서는 공용 관리자 repo에서 Streamlit과 대형 모델을 확인하는 운영용 요약 가이드다.

## Scope

This guide is for testing the Streamlit app from the administrator `ai-hang` workspace on DGX Spark.

Primary project path:

```bash
/srv/shared/projects/insurance-rag-chatbot
```

The app uses local offline assets, a Streamlit frontend, GraphDB-assisted RAG, and local large model backends. For normal team testing, start Streamlit from the project runtime preparation script so the OCR indexes, GraphDB file, embedding paths, and CPU/GPU policy are validated before the server opens.

## Current Model Policy

Validated large model slots:

- vLLM `nemotron-3-nano-30b-a3b-nvfp4`: current 신규 테스트 기본값.
- SGLang `qwen3-30b-a3b-instruct-2507-fp8`: current 신규 비교 테스트 모델.
- SGLang `gpt-oss-20b`: 기존 비교 기준 모델.
- vLLM `gemma-4-26b-a4b-nvfp4`: 기존 비교 기준 모델.

Small/local fallback, Ollama:

- `exaone3.5:7.8b`

Important current model notes:

- Nemotron must be served via vLLM. Its SGLang path loads weights but is unstable at first chat completion.
- Qwen must be served via SGLang.
- Gemma4 should use vLLM, not SGLang, because the SGLang path previously produced repeated `<pad>` output.
- Run only one large model at a time on DGX Spark unless explicitly coordinating GPU memory use.

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
Use `git rev-parse --short HEAD` after pulling `origin/master`.
```

## 2. Verify Model Endpoint Status

Check active model endpoints:

```bash
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30001/v1/models || true
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30000/v1/models || true
```

Recommended switches:

```bash
/srv/ai-ops/bin/switch-vllm-model nemotron-3-nano-30b-a3b-nvfp4
/srv/ai-ops/bin/switch-sglang-model qwen3-30b-a3b-instruct-2507-fp8
```

Model switching can take several minutes because the previous model session is stopped and the selected model is loaded from local disk.

Do not start vLLM and SGLang large models simultaneously unless there is a specific test reason and GPU memory has been checked.

## 3. Verify Runtime Assets

In the DGX admin shell:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --skip-offline-assets --skip-v2-handoff-import
```

The check should confirm at least:

- default BM25/Chroma index
- v2 manual BM25/Chroma index
- v1/v2 combined chunks and index
- pair mapping files
- relational standard code DB
- GraphDB SQLite index at `data/index/graph/insurance_graph.sqlite`

If GraphDB is missing, rebuild it after required OCR/index files are ready:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_graph_index.py --rebuild
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
```

`check_graph_index.py` must end with `Detailed Integrity Check: PASS`.

## 4. Start Streamlit From The Admin Repo

Preferred command:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
```

For quick restart when assets are already prepared:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/run_offline_streamlit_test.sh --skip-asset-prep --port 8501 --replace
```

Expected runtime policy:

- `GRAPH_ENABLED=true`
- `GRAPH_INDEX_PATH=/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite`
- Streamlit/RAG query embedding: CPU 기본
- SGLang/vLLM large model backend: GPU
- offline HuggingFace mode enabled

Check the current Streamlit process:

```bash
pgrep -af "streamlit run src/ui/streamlit_app.py"
```

Check GraphDB-related environment variables for the active process:

```bash
pid=$(pgrep -f "streamlit run src/ui/streamlit_app.py" | head -n 1)
tr '\0' '\n' < /proc/$pid/environ | grep -E '^(GRAPH_ENABLED|GRAPH_INDEX_PATH|GRAPH_CONTEXT_MAX_CHARS|OFFLINE_MODE|CUDA_VISIBLE_DEVICES)='
```

## 5. Open The App From The Mac

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

## 6. Login-time Large Model Selection

On the login screen:

1. Select `vllm:nemotron-3-nano-30b-a3b-nvfp4` for current 신규 모델 testing.
2. Select `sglang:qwen3-30b-a3b-instruct-2507-fp8` for Qwen comparison testing.
2. Enter the app credentials.
3. Click login.

After login, the app verifies whether the selected SGLang model is active. If not, it calls:

The app can call the configured switch wrapper:

- `/srv/ai-ops/bin/switch-vllm-model <selected-vllm-model>`
- `/srv/ai-ops/bin/switch-sglang-model <selected-sglang-model>`

Only allowlisted model names are accepted by the wrapper.

## 7. Sidebar Model Selection After Login

After login:

- The large SGLang model is already determined by the login screen.
- The sidebar can still be used to select available provider/model combinations.
- Ollama `exaone3.5:7.8b` remains available for small local fallback testing.

Expected normal options:

- `SGLang / gpt-oss-20b` when `gpt-oss-20b` is active.
- `Ollama / exaone3.5:7.8b` if Ollama is running.
- OpenAI is hidden while `OFFLINE_MODE=true`.

## 8. Recommended Smoke Tests

Run these with `gpt-oss-20b` first.

### GraphRAG Complex Question

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.
```

Check:

- The answer uses structured GraphDB facts, not only vector chunks.
- It identifies the surgery grade and gives same-grade peer surgeries.
- Candidate SOL appendix mappings are labeled as candidate/review-needed when not confirmed.
- Admin users can see GraphDB query plan/facts in the diagnostic panel.

### GraphRAG Category / Payment Ratio Question

```text
신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.
```

Check:

- Digestive grade-5 procedures are listed.
- Missing medical fee code links are explicitly marked as missing rather than invented.
- SOL payment ratio facts are not over-stated when they are candidate graph edges.

### Conflict-Aware Source Split

```text
로봇 수술의 수가코드와 분류 지침을 문서별로 비교해서 알려주세요.
```

Check:

- If retrieved documents disagree or expose different code/value rows, the answer separates document-specific cases.
- The answer does not merge conflicting source values into one final code.

### Claim Payout Calculation

Use `보험금 계산`.

Recommended first smoke:

- 청구 항목명: `도수치료`
- 청구금액: `150,000`
- 수량/횟수: `1`
- 방문 형태: `통원`
- 플래너 유형: first `Fake Planner`, then `LLM Planner` when a local large model is ready

Check:

- Fake Planner returns 지급예상액 `105000`, 공제금액 `45000`.
- LLM Planner returns valid JSON-backed calculation code and does not treat GraphDB candidate facts as confirmed payout rules.
- Candidate-only graph facts set review-required behavior.

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

## 9. Gemma4 / vLLM Validation Test

Gemma4 is served by vLLM in the current local runtime path.

Expected current behavior:

- Model load may take several minutes.
- vLLM should require the configured API key and return `/v1/models` only with the Authorization header.
- Use Gemma4 for controlled quality testing after `gpt-oss-20b` smoke passes.

If Gemma4 model startup fails, record it as a vLLM/model runtime issue rather than a GraphRAG app issue, unless Streamlit itself crashes.

Manual vLLM switch command:

```bash
/srv/ai-ops/bin/switch-vllm-model gemma-4-26b-a4b-nvfp4
```

Return to SGLang default for normal testing if needed:

```bash
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
```

## 10. Logs To Check

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
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

## 11. Pass Criteria

For `gpt-oss-20b`:

- Login succeeds.
- Streamlit reaches the chat UI.
- `SGLang / gpt-oss-20b` can answer at least one general Korean question.
- Source display works.
- GraphRAG complex question uses GraphDB facts and source chunks together.
- Missing/candidate graph facts are not hallucinated as confirmed facts.
- Conflict-aware questions split document-specific values instead of unifying them.
- 보험금 계산 mode remains usable and runs at least Fake Planner smoke successfully.
- Ollama fallback remains selectable and responds.
- No external OpenAI model is exposed in offline mode.

For Gemma4:

- vLLM model switch path can be exercised.
- Korean answer generation succeeds after cold start.
- Do not treat cold-start/model-serving failure as a GraphDB failure unless the app itself fails.
