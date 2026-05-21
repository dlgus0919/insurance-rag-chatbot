# Gemma4 vLLM Provider Implementation Report

## 요약

`nvidia/Gemma-4-26B-A4B-NVFP4`는 native SGLang 경로에서 `<pad>` 반복을 반환했지만, vLLM OpenAI-compatible server 경로에서는 정상 한국어 답변을 생성했다. 따라서 Gemma4 계열 답변 모델의 운영 경로를 SGLang이 아니라 `vLLM` provider로 추가했다.

현재 구현 후 Streamlit은 로그인 단계에서 대형 로컬 모델을 선택할 수 있고, `gemma-4-26b-a4b-nvfp4`를 선택하면 vLLM server 경로를 사용한다. SGLang은 `gpt-oss-20b`용으로 유지한다.

## 웹 조사 근거

- NVIDIA `nvidia/Gemma-4-26B-A4B-NVFP4` model card는 NVFP4 checkpoint 실행 경로를 vLLM 중심으로 안내한다.
- vLLM `0.21.0`은 DGX Spark ARM64 환경에서 aarch64 wheel을 제공했고, `Gemma4ForConditionalGeneration`, ModelOpt NVFP4 checkpoint, `--tool-call-parser gemma4`, `--reasoning-parser gemma4` 옵션을 인식했다.
- SGLang Gemma4 문서는 별도 SGLang/Transformers 조합을 요구하지만, 현재 native SGLang 0.5.12 경로에서는 parser 옵션 추가 후에도 `<pad>` 반복이 지속됐다.

## 설치/운영 자산

DGX 운영 산출물:

- `/srv/shared/projects/insurance-rag-chatbot/.venv-vllm/`
  - vLLM 0.21.0
  - nvidia-modelopt 0.44.0
  - torch 2.11.0+cu130
- `/srv/ai-ops/bin/switch-vllm-model`
  - `gemma-4-26b-a4b-nvfp4` vLLM 서버를 127.0.0.1:30001에서 기동한다.
  - SGLang session을 먼저 내려 대형 모델 간 GPU/unified memory 충돌을 피한다.
- `/srv/ai-ops/bin/check-vllm-gemma4`
  - `/v1/models` 및 `/v1/chat/completions`를 확인한다.
  - `<pad>` 반복이 감지되면 실패 처리한다.
- `/srv/ai-ops/logs/vllm/gemma4.log`

vLLM 기동 핵심 옵션:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model /srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4 \
  --served-model-name gemma-4-26b-a4b-nvfp4 \
  --host 127.0.0.1 \
  --port 30001 \
  --trust-remote-code \
  --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --enable-auto-tool-choice \
  --max-model-len 32768 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.78
```

`--max-num-batched-tokens 8192`는 필수에 가깝다. 처음 기동 시 vLLM이 `Chunked MM input disabled but max_tokens_per_mm_item (2496) is larger than max_num_batched_tokens (2048)` 오류를 냈고, 이 값을 올린 뒤 정상 기동했다.

## 코드 변경

- `src/config.py`
  - `VLLM_BASE_URL`, `VLLM_DEFAULT_MODEL`, `VLLM_CANDIDATE_MODELS`, `VLLM_SWITCH_SCRIPT`, `VLLM_SWITCH_TIMEOUT` 추가.
- `src/llm/factory.py`
  - `vllm` provider 추가.
  - `OpenAICompatibleClient(... provider="vllm")`로 routing.
  - `gemma-4-26b-a4b-nvfp4`를 vLLM 검증완료 모델로 표시.
- `src/ui/streamlit_app.py`
  - 로그인 단계 대형 로컬 모델 선택을 provider-prefixed 방식으로 확장.
  - `vllm:gemma-4-26b-a4b-nvfp4` 선택 시 `/srv/ai-ops/bin/switch-vllm-model`을 호출.
  - Sidebar provider 드롭다운에 `vLLM` provider 추가.
- `tests/test_llm_factory.py`
  - vLLM routing test 추가.
- `.gitignore`
  - `.venv-vllm/` 제외.

## 검증 결과

### vLLM direct check

```bash
/srv/ai-ops/bin/check-vllm-gemma4
```

결과:

- `/v1/models`: `gemma-4-26b-a4b-nvfp4` 노출
- `/v1/chat/completions`: 정상 한국어 문장 생성
- `<pad>` 반복 없음

대표 응답:

> 실손보험은 피보험자가 질병이나 상해로 인해 실제로 부담한 의료비를 보상해 주는 보험입니다.

### 프로젝트 factory check

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
VLLM_BASE_URL=http://127.0.0.1:30001/v1 python - <<'PY'
from src.llm.factory import build_llm
llm = build_llm('gemma-4-26b-a4b-nvfp4', provider='vllm')
print(llm.generate('한국어로 한 문장만 답하세요. 실손보험이란 무엇인가요?', temperature=0.0))
PY
```

결과: 정상 한국어 문장 생성.

### RAG smoke

Gemma4 vLLM provider를 실제 RAG pipeline에 연결해 로봇 수술 코드 문서별 구분 질의를 실행했다.

결과:

- retrieval + vLLM generation 경로는 정상 실행.
- 답변 본문과 출처가 생성됨.
- 다만 심평원 `QZ966`을 놓치는 케이스가 관찰되어, 이는 모델 서버 문제가 아니라 기존에 발견한 심평원 표/코드 row-level retrieval 개선 과제로 분류한다.

### pytest

```bash
pytest tests/test_llm_factory.py -q
pytest -q
```

결과:

- `tests/test_llm_factory.py`: `13 passed`
- 전체: `274 passed, 3 warnings`

## 운영 방법

Gemma4를 대형 로컬 답변 모델로 기동:

```bash
/srv/ai-ops/bin/switch-vllm-model gemma-4-26b-a4b-nvfp4
/srv/ai-ops/bin/check-vllm-gemma4
```

Streamlit에서는 로그인 화면의 `대형 로컬 모델`에서 `Local · vLLM · Gemma 4 · 26B A4B NVFP4 · 검증완료`를 선택한다. 로그인 후 Provider 드롭다운에서 `vLLM`, 모델 드롭다운에서 `gemma-4-26b-a4b-nvfp4`를 사용할 수 있다.

SGLang으로 되돌리려면:

```bash
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
/srv/ai-ops/bin/check-sglang-local
```

`switch-sglang-model`은 vLLM session을 내리고, `switch-vllm-model`은 SGLang session을 내리므로 두 대형 모델이 동시에 GPU/unified memory를 나눠 쓰지 않는다.

## 남은 과제

- Gemma4 vLLM 경로는 direct/RAG smoke까지 통과했지만, 대형 모델 평가셋 12문항 전체 품질 평가는 아직 별도 실행 대상이다.
- 심평원 수가코드/표 row-level retrieval 문제는 Gemma4로도 남는다. 답변 모델 교체가 아니라 검색 색인 개선이 필요하다.
- 완전 오프라인 모드에서는 `.venv-vllm` wheelhouse와 vLLM 의존성까지 handoff 자산으로 보존해야 한다.
