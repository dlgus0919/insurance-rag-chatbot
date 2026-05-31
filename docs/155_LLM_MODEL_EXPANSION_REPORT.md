# 155. LLM Model Expansion Report

작성일: 2026-05-29

## 목적

DGX Spark의 로컬 LLM 후보를 확장하여 다음 모델을 프로젝트에서 선택/운영할 수 있게 한다.

- `gemma-4-31b-it-nvfp4` (`nvidia/Gemma-4-31B-IT-NVFP4`, vLLM)
- `qwen3-next-80b-a3b-instruct-fp8` (`Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`, SGLang)
- `qwen3-next-80b-a3b-thinking-fp8` (`Qwen/Qwen3-Next-80B-A3B-Thinking-FP8`, SGLang)

## 변경 내용

- `src/config.py`
  - vLLM 기본 후보에 Gemma4 31B NVFP4 alias를 추가했다.
  - SGLang 기본 후보에 Qwen3 Next 80B Instruct/Thinking FP8 alias를 추가했다.
- `src/llm/factory.py`
  - 로그인/모델 선택 UI에 표시할 모델 family, size, use case 메타데이터를 추가했다.
- DGX 운영 스크립트
  - `/srv/ai-ops/bin/switch-vllm-model`에 `gemma-4-31b-it-nvfp4` case를 추가했다.
  - `/srv/ai-ops/bin/switch-sglang-model`에 Qwen3 Next 80B Instruct/Thinking case를 추가했다.

## 다운로드 위치

```text
/srv/ai-ops/llm/models/gemma-4-31b-it-nvfp4
/srv/ai-ops/llm/models/qwen3-next-80b-a3b-instruct-fp8
/srv/ai-ops/llm/models/qwen3-next-80b-a3b-thinking-fp8
```

다운로드 로그:

```text
/srv/ai-ops/logs/model-download/llm-model-download-20260529.log
```

## 검증

- HF Hub model info 접근 확인
- 로컬 코드 syntax compile 확인
- DGX 코드 syntax compile 확인
- DGX 모델 switch script `bash -n` 확인

## 남은 확인

대형 모델 파일 다운로드가 완료된 뒤 실제 기동 검증이 필요하다.

```bash
/srv/ai-ops/bin/switch-vllm-model gemma-4-31b-it-nvfp4
/srv/ai-ops/bin/switch-sglang-model qwen3-next-80b-a3b-instruct-fp8
/srv/ai-ops/bin/switch-sglang-model qwen3-next-80b-a3b-thinking-fp8
```
