# 178. DGX Large LLM Launcher Integration Report

## 목적

DGX에 다운로드된 대형 LLM을 데스크톱 실행기와 운영 wrapper에서 선택해 기동할 수 있도록 정리했다.

## 변경 사항

- `ops/bin/switch-sglang-model` 추가
  - `gpt-oss-20b`
  - `gpt-oss-120b` 지원 경로 추가
  - `qwen3-30b-a3b-instruct-2507-fp8`
  - `qwen3-next-80b-a3b-instruct-fp8`
  - `qwen3-next-80b-a3b-thinking-fp8`
  - `nemotron-3-nano-30b-a3b-nvfp4`
- `ops/bin/switch-vllm-model` 추가
  - `gemma-4-26b-a4b-nvfp4`
  - `gemma-4-31b-it-nvfp4`
  - `nemotron-3-nano-30b-a3b-nvfp4`
  - `exaone-4.0-32b-awq`
- `ops/bin/prepare-llm-model-assets` 추가
  - `tokenizer_config.json`에만 존재하는 `chat_template`를 `chat_template.jinja`로 생성한다.
  - Qwen3 Next Instruct/Thinking 모델의 누락 템플릿을 실제 DGX에서 생성했다.
- `insurance-rag-desktop-launcher` 선택 목록 확장
  - 다운로드 미완료 `.incomplete` 파일이 있으면 선택 목록에서 숨긴다.
  - SGLang/vLLM별 실제 실행 가능한 모델만 표시한다.
- 앱 내부 모델 메타데이터 확장
  - `gpt-oss-120b`
  - `exaone-4.0-32b-awq`

## 현재 실행기 노출 모델

SGLang:

- `gpt-oss-20b`
- `qwen3-30b-a3b-instruct-2507-fp8`
- `qwen3-next-80b-a3b-instruct-fp8`
- `qwen3-next-80b-a3b-thinking-fp8`

vLLM:

- `gemma-4-26b-a4b-nvfp4`
- `gemma-4-31b-it-nvfp4`
- `nemotron-3-nano-30b-a3b-nvfp4`
- `exaone-4.0-32b-awq`

Ollama:

- 현재 설치된 `exaone3.5:7.8b`

## 현재 숨김 처리된 모델

- `gpt-oss-120b`
  - `config.json`과 일부 파일은 있으나 Hugging Face download cache에 `.incomplete` 파일이 남아 있다.
  - 다운로드 완료 후에는 별도 코드 수정 없이 실행기 목록에 나타날 수 있다.
- `llama-3.3-70b-instruct-q4-k-m`
  - 현재 GGUF 단일 파일 형태로만 존재한다.
  - SGLang/vLLM OpenAI 호환 서버 경로가 아니라 Ollama 또는 llama.cpp import/serve 경로가 별도로 필요하다.

## DGX 검증 결과

다음 모델은 실제 서버 기동과 `/chat/completions` smoke 요청을 통과했다.

- `qwen3-next-80b-a3b-instruct-fp8` via SGLang
- `qwen3-next-80b-a3b-thinking-fp8` via SGLang
- `nemotron-3-nano-30b-a3b-nvfp4` via vLLM
- `exaone-4.0-32b-awq` via vLLM
- `gemma-4-26b-a4b-nvfp4` via vLLM

초기 검증 직후에는 SGLang/vLLM 대형 서버를 모두 종료했다.

## 2026-06-05 Qwen Thinking 앱 연동 및 응답 정규화

문제:

- `qwen3-next-80b-a3b-thinking-fp8`은 SGLang 비스트리밍/스트리밍 응답에서 내부 추론 문장을 `content`에 함께 노출할 수 있었다.
- 이 상태에서는 사용자가 최종 답변 전에 영어 reasoning 문장 또는 `</think>` 토큰을 볼 수 있어 1.0 운영 기준에 맞지 않는다.

패치:

- `src/llm/openai_compatible_client.py`에 thinking 계열 모델 감지를 추가했다.
- non-stream 응답은 `</think>` 이후의 사용자 표시 텍스트만 반환한다.
- stream 응답은 `</think>`가 관측될 때까지 토큰 출력을 보류하고, 이후 최종 답변만 방출한다.
- GPT-OSS Harmony final-channel gating과 Nemotron vLLM thinking 비활성화 로직은 기존 경로를 유지했다.

검증:

```bash
pytest tests/test_openai_compatible_client.py tests/test_llm_factory.py -q
```

결과:

```text
28 passed
```

DGX 전체 회귀:

```bash
pytest tests/ -q
```

결과:

```text
548 passed, 3 warnings
```

Live Qwen Thinking 검증:

```text
/api/system/models default: sglang:qwen3-next-80b-a3b-thinking-fp8
/v1/models served model: qwen3-next-80b-a3b-thinking-fp8
stream visible output: 정상입니다.
reasoning leak check: true
```

현재 상태:

- 최종 검증 시점에는 Qwen Thinking SGLang 서버와 FastAPI 앱이 실행 중이다.
- `insurance-rag-status` 기준 SGLang 운영 경로는 정상이다.
- `vllm warn`은 vLLM 서버를 동시에 띄우지 않은 상태의 표시이며 SGLang 운영 경로 실패가 아니다.

## 남은 작업

- `gpt-oss-120b` 다운로드 완료 후 smoke 검증
- GGUF Llama 70B를 사용할 경우 Ollama import 또는 llama.cpp OpenAI 호환 서버 wrapper 추가
- 각 모델의 실제 보험 RAG 답변 품질/속도 비교 평가

위 항목은 모델 확장 및 품질 비교 과제이며, Qwen Thinking을 포함한 현재 launcher/운영 wrapper의 1.0 기동 가능성 판단을 막는 blocking 결함은 아니다.
