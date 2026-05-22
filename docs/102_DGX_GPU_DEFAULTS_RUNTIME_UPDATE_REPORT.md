# 102. DGX GPU 기본 운영값 수정 보고서

## 목적

DGX Spark의 장기 운영 기본값을 다음 정책으로 정리했다.

- Streamlit 앱: CPU
- RAG query embedding: CPU 기본
- Reranker: CPU 기본
- SGLang/vLLM 대형 LLM: GPU
- 인덱스 생성/대량 임베딩: 별도 실행 시 GPU 사용

## 변경 파일

Repo 변경:

- `scripts/prepare_offline_assets.py`
- `scripts/run_offline_streamlit_test.sh`
- `docs/101_OFFLINE_STREAMLIT_TEST_RUNNER_REPORT.md`
- `docs/102_DGX_GPU_DEFAULTS_RUNTIME_UPDATE_REPORT.md`

DGX 운영 wrapper 변경:

- `/srv/ai-ops/bin/switch-sglang-model`
- `/srv/ai-ops/bin/switch-vllm-model`

## 핵심 변경

### 1. Streamlit/RAG CPU 기본값 유지

`scripts/run_offline_streamlit_test.sh`는 기존처럼 `FORCE_GPU=1`이 아닌 경우 다음을 적용한다.

```bash
export CUDA_VISIBLE_DEVICES=""
```

따라서 Streamlit 앱, RAG query embedding, reranker는 기본적으로 GPU를 보지 않는다.

### 2. 대형 LLM wrapper에서 GPU 재노출

Streamlit이 대형 모델을 로딩할 때 호출하는 switch wrapper 내부에서 GPU를 다시 노출하도록 수정했다.

```bash
SGLANG_CUDA_VISIBLE_DEVICES="${SGLANG_CUDA_VISIBLE_DEVICES:-0}"
VLLM_CUDA_VISIBLE_DEVICES="${VLLM_CUDA_VISIBLE_DEVICES:-0}"
```

각 wrapper는 tmux session에서 모델 서버를 띄우기 직전에 `CUDA_VISIBLE_DEVICES`를 위 값으로 export한다.

이로써 Streamlit 프로세스는 CPU 모드로 유지하면서도, SGLang/vLLM 하위 모델 서버는 GPU 0을 사용할 수 있다.

### 3. offline.env 생성 기본값 보강

`scripts/prepare_offline_assets.py`가 생성하는 `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`에 다음 값을 추가했다.

```env
SGLANG_CUDA_VISIBLE_DEVICES=0
VLLM_BASE_URL=http://127.0.0.1:30001/v1
VLLM_API_KEY=EMPTY
VLLM_DEFAULT_MODEL=gemma-4-26b-a4b-nvfp4
VLLM_CANDIDATE_MODELS=gemma-4-26b-a4b-nvfp4
VLLM_STRICT_AVAILABLE_MODELS=true
VLLM_ENABLE_APP_SWITCH=true
VLLM_SWITCH_SCRIPT=/srv/ai-ops/bin/switch-vllm-model
VLLM_SWITCH_TIMEOUT=1200
VLLM_CUDA_VISIBLE_DEVICES=0
```

## 기대 동작

통합 실행:

```bash
bash scripts/run_offline_streamlit_test.sh --replace
```

예상 동작:

1. Streamlit은 CPU 모드로 실행된다.
2. 로그인 단계에서 `SGLang · gpt-oss-20b`를 선택하면 `/srv/ai-ops/bin/switch-sglang-model`이 GPU 0으로 SGLang 서버를 띄운다.
3. 로그인 단계에서 `vLLM · gemma-4-26b-a4b-nvfp4`를 선택하면 `/srv/ai-ops/bin/switch-vllm-model`이 GPU 0으로 vLLM 서버를 띄운다.
4. 앱 내부의 RAG embedding/reranker는 GPU를 점유하지 않는다.

## 인덱스 생성 시 권장 실행

대량 인덱스 생성 또는 대량 embedding 생성은 별도 터미널에서 GPU를 열고 실행한다.

```bash
unset CUDA_VISIBLE_DEVICES
# 또는
export CUDA_VISIBLE_DEVICES=0
```

그 다음 필요한 `scripts/ingest.py --stage index ...` 명령을 실행한다.

## 검증

이번 변경에서 수행한 검증:

```bash
bash -n scripts/run_offline_streamlit_test.sh
bash -n /srv/ai-ops/bin/switch-sglang-model
bash -n /srv/ai-ops/bin/switch-vllm-model
python -m py_compile scripts/prepare_offline_assets.py
```

대형 모델 실제 기동 검증은 사용자의 Streamlit 테스트 흐름에서 이어서 수행한다.
