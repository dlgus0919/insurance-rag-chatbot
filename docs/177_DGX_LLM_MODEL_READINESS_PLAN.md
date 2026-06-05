# 177. DGX LLM Model Readiness Plan

## 목적

DGX에 다운로드된 대형 LLM을 “파일이 존재하는 모델”이 아니라 “더블클릭 launcher와 앱에서 실제로 기동 가능한 모델”로 승격하기 위한 준비 작업을 정리한다.

## 현재 기준

launcher 노출 기준은 보수적으로 둔다.

- SGLang: `config.json`과 chat template이 모두 있어야 노출
- `gpt-oss-20b`: 공용 `gpt_oss_harmony.jinja`가 있어야 노출
- vLLM: `config.json`과 `.venv-vllm/bin/python`이 있어야 노출
- Ollama: `/api/tags`에서 실제 실행 가능 모델이 조회되어야 노출

이 기준은 “다운로드 완료”와 “실사용 가능”을 분리하기 위한 것이다.

## 모델별 현재 상태

2026-06-05 DGX 점검 기준:

```text
gpt-oss-20b
- config: OK
- template: 공용 gpt_oss_harmony.jinja OK
- 상태: SGLang 실사용 가능

qwen3-30b-a3b-instruct-2507-fp8
- config: OK
- template: OK
- 상태: SGLang 기동 가능, 첫 기동 시간이 김

qwen3-next-80b-a3b-instruct-fp8
- config: OK
- template: OK
- 상태: SGLang smoke test 통과, launcher 노출 가능

qwen3-next-80b-a3b-thinking-fp8
- config: OK
- template: OK
- 상태: SGLang smoke test 및 앱 연동 검증 통과, Qwen Thinking 응답 정규화 적용

gemma-4-26b-a4b-nvfp4
- config: OK
- template: OK
- 상태: vLLM 후보

gemma-4-31b-it-nvfp4
- config: OK
- template: OK
- 상태: vLLM 후보
```

## 준비 작업 순서

### 1. 모델 파일 완전성 점검

각 모델별로 최소 파일을 확인한다.

```bash
test -f /srv/ai-ops/llm/models/<model>/config.json
test -f /srv/ai-ops/llm/models/<model>/tokenizer_config.json
test -f /srv/ai-ops/llm/models/<model>/chat_template.jinja
```

Qwen Next 계열은 현재 `chat_template.jinja`가 없으므로, Hugging Face 원본의 tokenizer chat template 또는 기존 Qwen3 계열 template과의 호환성을 확인해야 한다.

### 2. provider별 전환 스크립트 보강

대상:

- `/srv/ai-ops/bin/switch-sglang-model`
- `/srv/ai-ops/bin/switch-vllm-model`

요구사항:

- 없는 template을 요구하지 않도록 명확한 사전 실패 메시지 유지
- 모델별 `context-length`, `trust-remote-code`, CUDA graph 옵션을 명시
- 검증 전 모델은 launcher에 노출하지 않음

### 3. 단독 서버 기동 smoke test

각 모델별로 앱과 분리해 먼저 OpenAI-compatible endpoint를 검증한다.

```bash
/srv/ai-ops/bin/switch-sglang-model <model>
curl -s http://127.0.0.1:30000/v1/models
curl -s http://127.0.0.1:30000/v1/chat/completions ...
```

vLLM 모델은 `30001` 기준으로 동일하게 검증한다.

### 4. 앱 연동 검증

서버 단독 검증 통과 후 앱 wrapper로 연결한다.

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider <provider> --model <model>
/srv/ai-ops/bin/insurance-rag-status
curl -s http://127.0.0.1:18080/api/system/models
```

통과 기준:

- `api_health ok`
- `api_models ok`
- 선택 모델이 `/api/system/models`에 노출
- 브라우저 로그인 화면 진입
- 일반 질의 1건 응답

### 5. launcher 노출

위 검증을 통과한 모델만 `insurance-rag-desktop-launcher --choices`에 노출한다.

## Qwen3 30B 첫 기동 지연 진단

사용자가 DGX 데스크톱 launcher에서 `qwen3-30b-a3b-instruct-2507-fp8`로 전환했을 때 브라우저가 오래 열리지 않는 현상이 있었다.

진단 결과:

- SGLang 프로세스는 정상 생성됨
- `sglang::scheduler`가 GPU를 사용하며 실행 중이었음
- Torch Inductor compile worker들이 다수 생성됨
- SGLang 로그에서 CUDA graph capture 및 dynamic shape graph compile 진행이 확인됨
- GPU util 약 95%, 메모리 사용량 약 106GiB까지 상승

판단:

- Qwen3 30B 첫 기동이 오래 걸리는 현상 자체는 정상 범위다.
- 특히 첫 실행에서는 모델 로딩, CUDA graph capture, Torch Inductor compile이 겹쳐 수 분 이상 걸릴 수 있다.
- 이후 동일 모델 재기동은 캐시 상태에 따라 더 짧아질 수 있다.

추가로 확인된 실패:

- Qwen3 30B 모델은 최종적으로 SGLang `/v1/models`에 활성화되었다.
- 그러나 앱 재기동 단계에서 기존 FastAPI tmux 세션 종료 직후 `18080` 포트가 잠시 남아 있었고, wrapper가 listener PID를 찾지 못해 종료했다.
- 또한 wrapper가 `offline.env`를 읽은 뒤 선택 모델로 `SGLANG_DEFAULT_MODEL`을 강제 갱신하지 않아, Qwen3 서버가 떠 있어도 앱 기본 모델이 기존 `gpt-oss-20b` 또는 Ollama로 남을 수 있었다.

패치:

- `insurance-rag-common`에 `fuser`/`ss -ltnp` 기반 PID fallback을 추가했다.
- tmux 세션 종료 후 포트 해제를 기다리는 `wait_for_port_free`를 추가했다.
- PID를 못 찾는 transient 상태에서는 즉시 실패하지 않고 graceful release를 대기하도록 수정했다.
- `INSURANCE_RAG_PROVIDER/INSURANCE_RAG_MODEL`로 선택한 모델이 FastAPI 실행 환경의 `SGLANG_DEFAULT_MODEL`, `VLLM_DEFAULT_MODEL`, `OLLAMA_MODEL`에 우선 반영되도록 수정했다.

재검증:

```bash
/srv/ai-ops/bin/insurance-rag-up --provider sglang --model qwen3-30b-a3b-instruct-2507-fp8 --no-llm-switch --replace
curl -s http://127.0.0.1:18080/api/system/models
```

결과:

- FastAPI + SPA `http://127.0.0.1:18080` ready
- `/api/system/models` 기본값이 `sglang:qwen3-30b-a3b-instruct-2507-fp8`로 표시됨

## 2026-06-05 후속 완료 상태

완료:

1. Qwen Next 계열 chat template 생성 경로 추가
2. Qwen Next Instruct/Thinking `switch-sglang-model` 단독 smoke test
3. Qwen Next Thinking 앱 연동 테스트
4. Gemma/Nemotron/EXAONE vLLM 후보 smoke test
5. 통과 모델의 launcher 선택지 승격
6. Qwen Thinking 모델의 내부 추론 문장 노출 방지 후처리

남은 작업:

1. `gpt-oss-120b` 다운로드 완료 후 smoke 검증
2. GGUF Llama 70B를 사용할 경우 Ollama import 또는 llama.cpp OpenAI-compatible wrapper 추가
3. 각 모델별 보험 RAG 품질/속도 비교 평가

판단:

- 위 남은 작업은 모델 라인업 확장과 성능 비교 과제다.
- 현재 1.0 운영 가능성 판단의 blocking 결함은 아니다.
