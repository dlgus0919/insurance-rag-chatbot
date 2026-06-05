# DGX 1.0.0 Qwen Thinking 응답 서식 수정 보고서

작성일: 2026-06-05

## 배경

정식 1.0.0 후보 `c182f12`/`v1.0.0` 기준에서 Qwen Thinking 모델 사용 시 사용자 화면에 영어 내부 추론 문장 또는 `<think>` 계열 reasoning block이 노출될 수 있는 응답 서식 결함을 점검했다.

## 원인

- `/api/system/models`는 현재 SGLang `/v1/models`의 served model을 `sglang:qwen3-next-80b-a3b-thinking-fp8`로 노출한다.
- 프론트엔드는 SSE `token` 이벤트를 수신 즉시 assistant bubble에 누적 렌더링하고, `final` 이벤트가 오면 최종 답변으로 교체한다.
- 따라서 최종 후처리만으로는 스트리밍 중 노출된 reasoning을 되돌릴 수 없다.
- 기존 LLM client는 `</think>`가 오면 숨김 처리를 했지만, Qwen Thinking이 종료 토큰 없이 영어 reasoning만 반환하는 경우 빈 응답으로 끝나거나, 모델/형식 변형에 따라 token 단계 방어가 불충분할 위험이 있었다.

## 수정 내용

- `src/llm/openai_compatible_client.py`
  - Qwen Thinking SGLang 요청에 `chat_template_kwargs={"enable_thinking": False}`를 전달해 가능한 경우 서버 템플릿 단계에서 thinking 출력을 비활성화한다.
  - 스트리밍 시 thinking 모델은 최종 답변으로 판정되기 전까지 token을 emit하지 않는다.
  - `</think>` 이후 최종 답변, 명시적 답변 marker 이후 최종 답변, thinking 비활성화로 바로 오는 한국어 최종 답변을 모두 보존한다.
  - 종료 토큰 없이 영어 reasoning-only로 끝나면 내부 추론을 버리고 명확한 한국어 fallback 문구를 반환한다.
  - GPT-OSS Harmony gating과 vLLM Nemotron thinking 비활성화 경로는 유지했다.
- `tests/test_openai_compatible_client.py`
  - Qwen Thinking payload의 thinking 비활성화 옵션 검증 추가.
  - `</think>` 이후 최종 답변 케이스 유지.
  - `</think>` 없는 영어 reasoning-only 스트림의 fallback 검증 추가.
  - thinking 비활성화로 바로 한국어 최종 답변이 오는 스트림 검증 추가.
  - 일반 non-thinking 모델의 공백 토큰 보존 검증 추가.
- `tests/test_api_chat_stream.py`
  - 채팅 audit log에 실제 선택 모델이 기록되는지 검증 추가.

## DGX Live Smoke

실행 명령:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
/srv/ai-ops/bin/insurance-rag-status
curl -fsS http://127.0.0.1:30000/v1/models
curl -fsS http://127.0.0.1:18080/api/system/models
```

결과:

- SGLang `/v1/models`: `qwen3-next-80b-a3b-thinking-fp8`
- 앱 `/api/system/models`: `sglang:qwen3-next-80b-a3b-thinking-fp8`
- 앱 기본 local 모델: `sglang:qwen3-next-80b-a3b-thinking-fp8`
- 실제 `/api/chat/stream` 질의: HTTP 200, `token`/`final` 합산 검사에서 `<think>`, `</think>`, `Okay, let's`, `I need to`, `We need to`, `The question asks` 미검출
- `insurance_chat.db.audit_logs`: `CHAT_QUERY`, model=`sglang:qwen3-next-80b-a3b-thinking-fp8`, source_count=3

## 검증

```bash
timeout 240 .venv/bin/pytest tests/test_openai_compatible_client.py tests/test_llm_factory.py tests/test_api_chat_stream.py -q
```

결과: 42 passed, 1 warning

```bash
bash -n ops/bin/insurance-rag-up
bash -n ops/bin/insurance-rag-status
bash -n ops/bin/insurance-rag-desktop-launcher
bash -n /srv/ai-ops/bin/insurance-rag-up
bash -n /srv/ai-ops/bin/insurance-rag-status
bash -n /srv/ai-ops/bin/insurance-rag-desktop-launcher
```

결과: 모두 통과

```bash
timeout 1200 .venv/bin/pytest tests/ -q
```

결과: 552 passed, 3 warnings

## 태그 처리

현재 `v1.0.0` 태그는 결함이 있던 `c182f12`를 가리킨다. 이번 수정 커밋 생성 후에는 `v1.0.0` 태그를 그대로 두면 정식 1.0.0 태그가 결함 커밋을 계속 가리키게 된다.

권장 방안:

1. 원격 배포 전이면 사용자 승인 후 `v1.0.0` 태그를 수정 커밋으로 이동하고 force-with-lease 방식으로 태그만 갱신한다.
2. 이미 공유된 태그라면 `v1.0.1` 패치 태그를 새로 생성하고, `v1.0.0`은 결함 태그로 문서화한다.

사용자 승인 없이 원격 push나 태그 이동은 수행하지 않았다.
