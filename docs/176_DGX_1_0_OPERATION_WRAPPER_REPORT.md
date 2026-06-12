# 176. DGX 1.0 Operation Wrapper Report

## 목적

DGX Spark 부팅 후 회사 임직원이 앱을 쉽게 사용할 수 있도록, 운영자가 2개 이하의 명령으로 FastAPI + SPA 서비스를 기동하고 상태를 확인하는 wrapper를 추가했다.

기준 앱은 기존 Streamlit이 아니라 현재 메인 경로인 `uvicorn src.api.main:app` 기반 FastAPI + SPA다.

## 추가 파일

```text
ops/bin/insurance-rag-common
ops/bin/insurance-rag-prepare
ops/bin/insurance-rag-up
ops/bin/insurance-rag-status
ops/bin/insurance-rag-desktop-launcher
ops/desktop/insurance-rag-chatbot.desktop
ops/install_ai_ops_wrappers.sh
```

## 설치

DGX 메인 프로젝트 폴더에서 1회 실행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash ops/install_ai_ops_wrappers.sh
```

설치 대상:

```text
/srv/ai-ops/bin/insurance-rag-common
/srv/ai-ops/bin/insurance-rag-prepare
/srv/ai-ops/bin/insurance-rag-up
/srv/ai-ops/bin/insurance-rag-status
/srv/ai-ops/bin/insurance-rag-desktop-launcher
~/Desktop/신한EZ손해보험 보상지원 AI 챗봇.desktop
```

## 1.0 운영 사용 흐름

DGX에서 앱 기동:

```bash
/srv/ai-ops/bin/insurance-rag-up
```

상태 확인:

```bash
/srv/ai-ops/bin/insurance-rag-status
```

Mac에서 브라우저 접속:

```bash
ssh -N -L 18080:127.0.0.1:18080 ai-hang@100.88.5.57
```

```text
http://localhost:18080
```

## wrapper 역할

### `insurance-rag-prepare`

운영 산출물을 확인하고, 옵션에 따라 누락 산출물을 빌드한다.

확인 대상:

- default `chunks.jsonl`
- default BM25/Chroma
- v2 manual BM25/Chroma
- v1/v2 combined BM25/Chroma
- GraphDB SQLite
- 비급여 표준코드 SQLite
- v1/v2 pair mapping
- embedding/reranker local model config

기본은 strict check다.

```bash
/srv/ai-ops/bin/insurance-rag-prepare
```

누락 산출물을 가능한 범위에서 생성:

```bash
/srv/ai-ops/bin/insurance-rag-prepare --build-missing
```

### `insurance-rag-up`

FastAPI + SPA 서비스를 `127.0.0.1:18080`에 tmux 세션으로 기동한다.

기본값:

- provider: `sglang`
- model: `qwen3-next-80b-a3b-instruct-fp8`
- app port: `18080`
- tmux session: `insurance-rag-api`
- app log: `logs/fastapi_YYYYmmdd_HHMMSS.log`

내부 처리:

1. secrets/env 로드
2. runtime artifact readiness 확인
3. SGLang 모델 전환
4. FastAPI + SPA tmux 기동
5. `/api/health` readiness 대기
6. Mac 터널 명령 출력

기존 앱 교체:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace
```

다른 모델:

```bash
/srv/ai-ops/bin/insurance-rag-up --provider sglang --model qwen3-30b-a3b-instruct-2507-fp8
```

모델 전환 없이 앱만 기동:

```bash
/srv/ai-ops/bin/insurance-rag-up --no-llm-switch
```

### `insurance-rag-status`

다음을 한 번에 확인한다.

- tmux 앱 세션
- FastAPI 포트
- `/api/health`
- `/api/system/models`
- SGLang/vLLM/Ollama endpoint
- default/v2/combined index
- GraphDB
- standard code DB
- users.json

JSON 출력:

```bash
/srv/ai-ops/bin/insurance-rag-status --json
```

### `insurance-rag-desktop-launcher`

DGX 데스크톱에서 더블클릭으로 실행되는 GUI launcher다.

동작:

1. 현재 실행 중인 LLM 서버 상태를 확인한다.
2. SGLang/vLLM/Ollama 중 실행 중인 서버가 있으면 “현재 실행 중인 서버 유지” 선택지를 표시한다.
3. 준비된 모델 후보를 라디오 버튼으로 표시한다.
4. 선택 후 `insurance-rag-up`을 호출해 LLM 서버와 앱을 준비한다.
5. 준비가 끝나면 `http://localhost:18080`을 기본 브라우저로 연다.

GUI 의존성:

- DGX 기본 `zenity`
- DGX 기본 `xdg-open`
- Python stdlib JSON 파서

SSH나 headless 환경에서 상태만 점검:

```bash
/srv/ai-ops/bin/insurance-rag-desktop-launcher --status
```

## 환경변수 override

필요 시 다음 값을 override할 수 있다.

```text
INSURANCE_RAG_PROJECT_DIR=/srv/shared/projects/insurance-rag-chatbot
AI_OPS_ROOT=/srv/ai-ops
INSURANCE_RAG_APP_HOST=127.0.0.1
INSURANCE_RAG_APP_PORT=18080
INSURANCE_RAG_APP_SESSION=insurance-rag-api
INSURANCE_RAG_PROVIDER=sglang
INSURANCE_RAG_MODEL=gpt-oss-20b
```

## 1.0 조건 충족 여부

이번 wrapper 추가 후 목표 운영 흐름은 다음과 같이 단순화된다.

```bash
/srv/ai-ops/bin/insurance-rag-up
/srv/ai-ops/bin/insurance-rag-status
```

즉, 운영 준비가 완료된 DGX에서는 2개 이하 명령으로 앱 기동과 확인이 가능하다.

## DGX live 검증 결과

2026-06-05 DGX Spark `aitopatom-255d`에서 wrapper를 `/srv/ai-ops/bin`에 설치하고 live 기동을 검증했다.

설치:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash ops/install_ai_ops_wrappers.sh
```

1.0 운영 명령 1:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace
```

결과:

- runtime preparation check 통과
- SGLang `gpt-oss-20b` 전환 완료
- `insurance-rag-api` tmux 세션 생성
- FastAPI + SPA `http://127.0.0.1:18080` ready

1.0 운영 명령 2:

```bash
/srv/ai-ops/bin/insurance-rag-status
```

결과:

- `api_health`가 `ok`
- `api_models`가 `ok`
- `sglang`이 `ok`
- `default_bm25`, `default_chroma`, `v2_bm25`, `combined_bm25`, `graph_db`, `standard_db`, `users_json`이 모두 `ok`
- `vllm`은 현재 서버가 떠 있지 않아 `warn`이지만 기본 운영 경로가 SGLang이므로 실패 조건은 아님

추가 확인:

- `curl http://127.0.0.1:18080/`에서 SPA HTML 응답 확인
- `curl http://127.0.0.1:18080/api/system/models`에서 기본 모델 `sglang:gpt-oss-20b` 확인

판단:

- one-time 설치 이후 DGX에서는 `insurance-rag-up`과 `insurance-rag-status` 2개 명령으로 앱 기동 및 상태 확인이 가능하다.
- Mac 사용자는 별도로 SSH 터널을 열고 `http://localhost:18080`으로 접속하면 된다.

데스크톱 사용자는 설치된 `~/Desktop/신한EZ손해보험 보상지원 AI 챗봇.desktop` 아이콘을 더블클릭하면 LLM 선택 창을 통해 같은 기동 흐름을 사용할 수 있다.

## Desktop launcher 패치 기록

2026-06-05 더블클릭 실행기에서 `qwen3-next-80b-a3b-thinking-fp8` 선택 시 앱 기동 실패가 확인됐다.

원인:

- launcher가 모델 디렉터리의 `config.json`만 보고 선택지를 노출했다.
- 실제 SGLang 전환 스크립트는 모델별 `chat_template.jinja`까지 요구한다.
- 해당 모델은 `config.json`은 있으나 `chat_template.jinja`가 없어 `switch-sglang-model` 단계에서 실패했다.

패치:

- launcher 선택지 생성 기준을 provider별 runtime readiness로 변경했다.
- SGLang은 `config.json`과 chat template이 모두 있을 때만 선택지에 노출한다.
- `gpt-oss-20b`는 공용 `gpt_oss_harmony.jinja` 존재를 확인한다.
- vLLM은 모델 `config.json`과 `.venv-vllm/bin/python` 존재를 함께 확인한다.
- headless 검증용 `--choices` 모드를 추가했다.

검증:

```bash
/srv/ai-ops/bin/insurance-rag-desktop-launcher --choices
```

현재 노출 선택지:

```text
current|sglang|gpt-oss-20b
start|sglang|gpt-oss-20b
start|sglang|qwen3-30b-a3b-instruct-2507-fp8
start|vllm|gemma-4-26b-a4b-nvfp4
start|vllm|gemma-4-31b-it-nvfp4
start|ollama|exaone3.5:7.8b
```

후속 조치:

- 이후 `prepare-llm-model-assets`가 `tokenizer_config.json`의 `chat_template`를 `chat_template.jinja`로 생성하도록 보강되었다.
- Qwen Next Instruct/Thinking 모델은 실제 DGX smoke test를 통과한 뒤 다시 실행기 선택지에 승격되었다.
- 따라서 현재 실행기는 "파일이 있는 모델"이 아니라 "다운로드 완료 + provider별 필수 런타임 산출물 존재 + 전환 스크립트 지원" 기준으로 모델을 노출한다.

## 2026-06-05 Qwen Thinking 기준 1.0 live 검증

검증 명령:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
/srv/ai-ops/bin/insurance-rag-status
```

확인 결과:

- FastAPI + SPA가 `http://127.0.0.1:18080`에서 ready 상태가 됐다.
- SGLang OpenAI-compatible endpoint가 `http://127.0.0.1:30000/v1`에서 ready 상태가 됐다.
- `/api/system/models`의 기본 로컬 모델이 `sglang:qwen3-next-80b-a3b-thinking-fp8`로 표시됐다.
- `/v1/models`의 served model이 `qwen3-next-80b-a3b-thinking-fp8`로 표시됐다.
- `insurance-rag-status`에서 `api_health`, `api_models`, `sglang`, 주요 index, GraphDB, standard DB, `users_json`이 모두 `ok`였다.
- `vllm`은 현재 SGLang 서버만 띄운 상태라 `warn`으로 표시되며, SGLang 운영 경로의 장애로 보지 않는다.

추가 검증:

- Qwen Thinking 모델의 streaming 응답에서 내부 추론 문장이 사용자 응답으로 노출되지 않도록 client 후처리를 보강했다.
- DGX 전체 Python 회귀 테스트는 `548 passed, 3 warnings`로 통과했다.

판단:

- DGX 준비가 완료된 상태에서는 CLI 기준 `insurance-rag-up`과 `insurance-rag-status` 두 명령으로 앱 기동과 상태 점검이 가능하다.
- DGX 데스크톱 사용자는 아이콘 더블클릭 후 모델 선택 창에서 같은 흐름을 사용할 수 있다.
