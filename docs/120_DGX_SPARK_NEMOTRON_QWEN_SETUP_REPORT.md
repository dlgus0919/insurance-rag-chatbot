# 120. DGX Spark Nemotron/Qwen Runtime Setup Report

작성일: 2026-05-26

## 목적

DGX Spark 환경에서 신규 후보 LLM 2종을 기존 OpenAI-compatible 로드 파이프라인에 맞춰 내려받고, Streamlit에서 바로 질의 테스트할 수 있도록 런타임을 준비했다.

## 준비한 모델

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
  - 로컬 경로: `/srv/ai-ops/llm/models/nemotron-3-nano-30b-a3b-nvfp4`
  - 검증 경로: vLLM, `http://127.0.0.1:30001/v1`
- `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`
  - 로컬 경로: `/srv/ai-ops/llm/models/qwen3-30b-a3b-instruct-2507-fp8`
  - 검증 경로: SGLang, `http://127.0.0.1:30000/v1`

## 변경한 운영 설정

- `/srv/ai-ops/bin/switch-sglang-model`
  - `qwen3-30b-a3b-instruct-2507-fp8` alias 추가
  - `nemotron-3-nano-30b-a3b-nvfp4` alias 추가
  - Nemotron SGLang 경로는 CUDA graph 비활성화 옵션을 적용했으나 첫 chat completion 단계에서 안정화되지 않았다.
- `/srv/ai-ops/bin/switch-vllm-model`
  - `nemotron-3-nano-30b-a3b-nvfp4` alias 추가
  - `--trust-remote-code --reasoning-parser nemotron_v3` 옵션 적용
- Qwen은 `tokenizer_config.json`의 `chat_template`를 `chat_template.jinja`로 추출해 SGLang 로더가 사용할 수 있게 했다.

## 검증 결과

- Qwen/SGLang
  - `/srv/ai-ops/bin/switch-sglang-model qwen3-30b-a3b-instruct-2507-fp8`
  - `/v1/chat/completions` 한국어 smoke 응답 정상
- Nemotron/vLLM
  - `/srv/ai-ops/bin/switch-vllm-model nemotron-3-nano-30b-a3b-nvfp4`
  - `/v1/models` 및 `/v1/chat/completions` 한국어 smoke 응답 정상
- Streamlit
  - 포트: `8501`
  - 로그: `/srv/shared/projects/insurance-rag-chatbot/logs/streamlit_8501_new_models.log`
  - health check: `http://127.0.0.1:8501/_stcore/health` 응답 `ok`

## 현재 런타임 상태

- 활성 모델: `nemotron-3-nano-30b-a3b-nvfp4` via vLLM, port `30001`
- Streamlit: port `8501` 백그라운드 실행 중
- Qwen은 다운로드 및 switch alias 준비가 끝났으며, Streamlit UI에서 선택 시 SGLang switch script로 기동 가능하다.

## 접속 가이드

Mac에서 다음 터널을 연다.

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저에서 접속한다.

```text
http://localhost:8501
```

모델 선택에서 다음을 우선 확인한다.

- `vllm:nemotron-3-nano-30b-a3b-nvfp4`
- `sglang:qwen3-30b-a3b-instruct-2507-fp8`

## 남은 위험

- Nemotron은 SGLang 경로에서 서버 startup 직후 첫 chat completion 단계가 안정적이지 않아, 현재 실사용 경로는 vLLM으로 고정하는 것이 안전하다.
- Qwen은 SGLang에서 smoke 응답은 정상이나, 실제 보험 RAG 품질은 별도 matrix 평가가 필요하다.
- 두 모델을 동시에 띄우면 DGX Spark GPU 메모리를 과점유할 수 있으므로 한 번에 하나의 대형 모델만 운영해야 한다.
