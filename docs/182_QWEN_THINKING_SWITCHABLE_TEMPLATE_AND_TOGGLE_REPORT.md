# Qwen Thinking 1.0.x 응답 안정화 보고서

작성일: 2026-06-05

## 목적

`qwen3-next-80b-a3b-thinking-fp8` 사용 시 영어 내부 추론과 `<think>` 블록이 사용자 응답으로 노출될 수 있는 문제를 1.0.x 운영 경로에서 차단하고, 사용자가 명시적으로 선택할 때만 모델 reasoning 모드를 켤 수 있도록 안정화했다.

## 원인

- 기존 DGX Qwen Thinking `chat_template.jinja`는 `enable_thinking`을 읽지 않고 assistant generation prompt를 항상 `<think>`로 시작했다.
- 템플릿 교체 후에도 `switch-sglang-model`이 현재 served model id만 보고 `already active`로 종료하면, 실행 중 SGLang이 이전 템플릿을 계속 사용했다.
- Qwen Thinking 체크포인트는 assistant prompt가 단순히 `<think>` 없이 시작되더라도 스스로 `<think>`를 생성할 수 있었다.

## 수정

- `ops/templates/qwen3_thinking_switchable.jinja`를 추가했다.
  - `enable_thinking=false`: `<|im_start|>assistant\n</think>\n\n`로 시작해 빈 reasoning block이 이미 종료된 상태를 모델에 제공한다.
  - `enable_thinking=true`: 기존처럼 `<|im_start|>assistant\n<think>\n`로 reasoning 생성을 허용한다.
- `prepare-llm-model-assets`가 Qwen Thinking switchable template을 `/srv/ai-ops/llm/models/qwen3-next-80b-a3b-thinking-fp8/chat_template.jinja`에 설치하도록 했다.
- `switch-sglang-model`은 Qwen Thinking 템플릿의 `enable_thinking` 지원을 검사하고, Qwen Thinking이 이미 active여도 템플릿 반영을 위해 SGLang을 재로드한다.
- API schema에 `reasoning_mode: "off" | "on"`을 추가하고 기본값을 `off`로 고정했다.
- LLM client는 Qwen Thinking 요청마다 `chat_template_kwargs.enable_thinking`을 per-request로 설정한다.
- stream/non-stream 후처리는 `<think>`/`</think>`와 영어 reasoning-only 응답을 숨기며, final answer가 없으면 `THINKING_ONLY_OUTPUT` warning과 fallback을 반환한다.
- chat SSE audit detail에 `reasoning_mode`, `reasoning_supported`, `reasoning_filtered`, `warning_codes`를 기록한다.
- 프론트엔드 모델 선택이 Qwen Thinking일 때만 `추론 모드` 토글을 표시하고, payload의 `reasoning_mode`에 반영한다.

## DGX Live Smoke

실행:

```bash
/srv/ai-ops/bin/prepare-llm-model-assets
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
/srv/ai-ops/bin/insurance-rag-status
curl -fsS http://127.0.0.1:30000/v1/models
curl -fsS http://127.0.0.1:18080/api/system/models
```

결과:

- `/v1/models`: `qwen3-next-80b-a3b-thinking-fp8`
- `/api/system/models`: 기본 local model `sglang:qwen3-next-80b-a3b-thinking-fp8`
- SGLang 원문 smoke, `enable_thinking=false`: 한국어 최종 답변 생성, `reasoning_content=null`, `<think>` 미노출
- `/api/chat/stream`, `reasoning_mode=off`: fallback 없음, leak marker 없음, 한국어 최종 답변 생성
- `/api/chat/stream`, `reasoning_mode=on`: 해당 질의에서는 `</think>` 이후 final answer가 없어 `THINKING_ONLY_OUTPUT` warning과 fallback 처리, leak marker 없음
- audit log:
  - id 267: `reasoning_mode=off`, `reasoning_supported=true`, `reasoning_filtered=false`, `source_count=5`, `warning_codes=[]`
  - id 268: `reasoning_mode=on`, `reasoning_supported=true`, `reasoning_filtered=true`, `source_count=5`, `warning_codes=["THINKING_ONLY_OUTPUT"]`

## 검증

```bash
timeout 240 .venv/bin/pytest tests/test_openai_compatible_client.py tests/test_api_chat_stream.py tests/test_qwen_thinking_template.py -q
timeout 1200 .venv/bin/pytest tests/ -q
npx playwright test tests/e2e/chat.spec.js -g "토글 on/off" --project=chromium
bash -n ops/bin/prepare-llm-model-assets
bash -n ops/bin/switch-sglang-model
bash -n /srv/ai-ops/bin/insurance-rag-up
bash -n /srv/ai-ops/bin/insurance-rag-status
bash -n /srv/ai-ops/bin/insurance-rag-desktop-launcher
```

결과:

- 관련 pytest: 32 passed
- 전체 pytest: 557 passed
- Playwright 토글 e2e: 1 passed
- wrapper `bash -n`: 통과

## 남은 운영 판단

Qwen Thinking은 `reasoning_mode=off`에서 fallback 없이 한국어 최종 답변을 생성했다. `reasoning_mode=on`은 모델이 종료 토큰 없이 내부 추론만 길게 생성할 수 있으므로, 사용자 명시 선택 시에만 허용하고 final answer가 없으면 현재처럼 warning + fallback으로 처리한다.
