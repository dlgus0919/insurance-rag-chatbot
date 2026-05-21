# DGX Spark SGLang 로컬 LLM 전환 계획

작성일: 2026-05-19
상태: 계획/검토 문서
대상: 보험 문서 RAG 챗봇 로컬 답변 생성 LLM 고도화

---

## 1. 결론

기존 GPT 계획은 방향은 맞지만, 우리 프로젝트 운영 조건과 맞지 않는 부분이 있다.

수정된 운영 원칙은 다음이다.

1. Docker를 기본 전제로 두지 않는다.
2. 맥북에서는 모델 스냅샷을 우선 내려받고, SGLang은 `manylinux aarch64` wheelhouse 후보를 별도 폴더에 미리 받아둘 수 있다.
3. SGLang wheelhouse는 "오프라인 설치 후보"로 취급한다. DGX Spark 복구 후 Python/CUDA/torch 호환성을 확인한 뒤 실제 설치 여부를 결정한다.
4. 현재 검증된 Ollama `exaone3.5:7.8b` 경로는 제거하지 않고 fallback으로 유지한다.
5. 앱 코드는 Ollama 전용에서 `OpenAI-compatible local provider`를 추가하는 방식으로 확장한다.
6. OCR Vision 후보정용 OpenAI API 코드는 이번 전환 대상이 아니다.

---

## 2. 현재 프로젝트 기준 사실

현재 DGX 1차 운영 기준:

```text
DGX repo: /srv/shared/projects/insurance-rag-chatbot
Streamlit: 127.0.0.1:8501
현재 로컬 LLM: Ollama exaone3.5:7.8b
chunks.jsonl: 7825
Chroma count: 7825
eval.py --ocr retrieval recall@8: 1.000
```

현재 코드 구조:

```text
src/llm/base.py          LLMClient 프로토콜
src/llm/ollama_client.py Ollama /api/generate 직접 호출
src/llm/openai_client.py OpenAI Chat Completions 직접 호출
src/llm/factory.py       모델 ID 기반 Ollama/OpenAI 선택
src/config.py            OLLAMA_* 및 OPENAI_* 환경변수
scripts/eval.py          OllamaClient 직접 import
scripts/cli.py           OllamaClient 직접 import
```

따라서 수정은 "Ollama 삭제"가 아니라 "provider 확장"이어야 한다.

---

## 3. GPT 계획에서 정정할 부분

| 항목           | GPT 계획                          | 정정                                                                                                                                                                           |
| -------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SGLang 설치    | ARM64 Docker image pull/save      | 우리 운영 방식에서는 Docker를 기본으로 두지 않는다. 네이티브 venv 설치를 우선한다.                                                                                             |
| 맥북 사전 준비 | 모델 + Docker tar + SGLang 이미지 | 맥북에서는 모델 스냅샷과 checksum을 우선 준비한다. 추가로 no-Docker 운영을 위해 PyPI wheelhouse 후보를 받을 수 있지만, DGX에서 호환성 검증 전까지 확정 설치파일로 보지 않는다. |
| 실행 host      | `--host 0.0.0.0`                | 처음에는 `127.0.0.1` 바인딩을 기본으로 한다. 외부 노출은 SSH 터널/프록시 정책 확정 후 결정한다.                                                                              |
| context length | 262K급 장문 context 전제          | 첫 smoke는 32K 또는 64K로 시작한다. 262K는 KV cache와 unified memory 압박이 커서 검증 후 확장한다.                                                                             |
| 모델 선택      | 3개 동시 상주 가능성              | DGX Spark 128GB에서는 한 번에 1개 주력 모델만 active serving하고 나머지는 교체 기동한다.                                                                                       |
| fallback       | Ollama 제거/대체                  | Ollama `exaone3.5:7.8b`는 운영 fallback으로 유지한다.                                                                                                                        |

---

## 4. 모델 선정

이번 모델은 Codex/Claude 개발 보조용이 아니라, 보험 RAG 챗봇의 최종 답변 생성용이다.

2026-05-19 기준으로 최신 공개 가중치 후보를 다시 확인했다. 선정 기준은 다음 순서로 둔다.

1. 한국어 보험 문서 RAG 답변 품질
2. 장문 context와 표 기반 근거 답변 적합성
3. DGX Spark 128GB unified memory에서의 현실적인 기동 가능성
4. SGLang 또는 Transformers OpenAI-compatible serving 가능성
5. 라이선스와 gated 여부
6. MacBook 내부 저장소에 미리 받을 수 있는 용량

### 4.1 1차 다운로드/검증 후보

| 우선 | 모델                                         | 역할                    | 판단                                                                                            |
| ---: | -------------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------- |
|    1 | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`     | 기본 RAG 답변 생성      | 한국어/장문/표 기반 질문에 가장 먼저 검증할 주력 후보                                           |
|    2 | `nvidia/Gemma-4-26B-A4B-NVFP4`             | 경량/고속 실험 후보     | Gemma 4 계열 중 DGX Spark 실험용으로 가장 용량이 작고, NVIDIA 최적화 포맷이라 smoke test에 적합 |
|    3 | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | reasoning fallback      | 80B 기동 실패 시 대체 검증용. 장해율/수술종수처럼 추론이 필요한 질의 비교에 유용                |
|    4 | `google/gemma-4-31B-it`                    | Gemma 4 dense 품질 비교 | Apache 2.0, 140+ 언어, 256K context 장점. 다만 BF16 dense라 26B NVFP4보다 메모리 부담이 큼      |
|    5 | `Qwen/Qwen3-Next-80B-A3B-Thinking-FP8`     | 복잡한 검토 모드        | 기본 챗보다 관리자/고난도 검토용 후보                                                           |

### 4.2 2차 실험 또는 보류 후보

| 모델                                          | 판단                                                                                                                                                  |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `openai/gpt-oss-20b`                        | Apache 2.0, SGLang 예제가 있고 reasoning effort를 조정할 수 있다. 다만 harmony format 의존이 있어 앱 prompt/message 변환을 별도로 검증해야 한다.      |
| `openai/gpt-oss-120b`                       | 품질 검토 후보로는 의미가 있으나, repo 전체 다운로드는 중복 파일 때문에 크고 serving format 제약이 있다. 1차 운영 후보에서는 제외한다.                |
| `zai-org/GLM-4.5-Air-FP8`                   | MIT, SGLang 문서가 명시되어 있으나 권장 실행 예시가 multi-GPU `tp-size` 전제다. 단일 DGX Spark 검증 전까지 보류한다.                                |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` | 10M context와 MoE 구조는 매력적이나 gated/manual license이고 BF16 weight가 200GB 이상이다. MacBook 사전 다운로드/단일 DGX Spark 운영 우선순위는 낮다. |
| `moonshotai/Kimi-K2-Instruct`               | 매우 큰 MoE 계열로 로컬 단일 DGX Spark에는 비현실적이다. 비교 조사 대상으로만 유지한다.                                                               |

`Qwen3-Coder-30B`는 코딩 에이전트 용도로는 유효하지만, 보험 RAG 앱의 기본 답변 생성 모델로는 우선순위가 낮다.

다운로드 순서는 저장공간이 허용하는 범위에서 다음을 권장한다.

```text
1. Qwen3-Next-80B-A3B-Instruct-FP8
2. nvidia/Gemma-4-26B-A4B-NVFP4
3. DeepSeek-R1-Distill-Qwen-32B
4. google/gemma-4-31B-it
5. Qwen3-Next-80B-A3B-Thinking-FP8
```

---

## 5. 맥북에서 지금 준비할 것

외장 SSD 기준 경로:

```bash
mkdir -p /Volumes/DGX_TRANSFER/models
mkdir -p /Volumes/DGX_TRANSFER/sglang/wheelhouse
mkdir -p /Volumes/DGX_TRANSFER/sglang/src
mkdir -p /Volumes/DGX_TRANSFER/manifests
```

외장 SSD가 없으면 맥북 내부 저장소에 아래처럼 만든다.

```bash
mkdir -p "$HOME/DGX_TRANSFER/models"
mkdir -p "$HOME/DGX_TRANSFER/sglang/wheelhouse"
mkdir -p "$HOME/DGX_TRANSFER/sglang/src"
mkdir -p "$HOME/DGX_TRANSFER/manifests"
```

### 5.1 모델별 예상 다운로드 용량

Hugging Face LFS metadata 기준:

| 모델                                          |                                   예상 다운로드 | 라이선스/접근          | 비고                             |
| --------------------------------------------- | ----------------------------------------------: | ---------------------- | -------------------------------- |
| `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`      |                            82.05 GB (76.42 GiB) | Apache 2.0 / public    | 기본 RAG 답변 생성 1순위         |
| `nvidia/Gemma-4-26B-A4B-NVFP4`              |                            18.79 GB (17.50 GiB) | Apache 2.0 / public    | 가장 작은 최신 고성능 smoke 후보 |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`  |                            65.53 GB (61.03 GiB) | MIT / public           | reasoning fallback               |
| `google/gemma-4-31B-it`                     |                            62.55 GB (58.25 GiB) | Apache 2.0 / public    | Gemma 4 dense 품질 비교          |
| `Qwen/Qwen3-Next-80B-A3B-Thinking-FP8`      |                            82.05 GB (76.42 GiB) | Apache 2.0 / public    | 고난도 검토 모드                 |
| `openai/gpt-oss-20b`                        |  약 13.76 GB 선택 다운로드 / 41.27 GB 전체 repo | Apache 2.0 / public    | harmony format 검증 필요         |
| `openai/gpt-oss-120b`                       | 약 65.24 GB 선택 다운로드 / 195.74 GB 전체 repo | Apache 2.0 / public    | 1차 운영 후보 제외               |
| `zai-org/GLM-4.5-Air-FP8`                   |                          112.56 GB (104.83 GiB) | MIT / public           | multi-GPU 전제 예시가 있어 보류  |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` |                          217.28 GB (202.36 GiB) | Llama 4 / gated manual | 사전 다운로드 비권장             |

권장 묶음별 저장공간:

```text
최소 실험 세트: Gemma-4-26B-NVFP4 + SGLang wheelhouse = 35~45 GB 여유
주력 1개 세트: Qwen3-Next-Instruct + SGLang wheelhouse = 110~120 GB 여유
권장 3개 세트: Qwen3-Next-Instruct + Gemma-4-26B-NVFP4 + DeepSeek-32B + SGLang wheelhouse = 200~230 GB 여유
전체 1차 후보 5개: 약 310.97 GB 모델 + SGLang wheelhouse = 360~400 GB 여유
```

주의:

- `openai/gpt-oss-*`는 repo 안에 `metal/`, `original/`, 일반 safetensors가 함께 있어 전체 repo를 받으면 용량이 커진다. 실험 시에는 필요한 파일만 `--include`로 제한한다.
- `meta-llama/Llama-4-*`는 gated/manual 접근과 큰 weight 때문에 MacBook 내부 저장소 사전 다운로드 대상에서 제외한다.
- `Gemma 4`는 최신 공개 후보로 반드시 고려하되, 운영 주력 후보는 Qwen3-Next와 직접 비교한 뒤 결정한다.

Hugging Face CLI:

```bash
python3 -m pip install -U "huggingface_hub[cli]"
hf auth login
```

모델 다운로드:

```bash
hf download Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 \
  --local-dir "$HOME/DGX_TRANSFER/models/Qwen3-Next-80B-A3B-Instruct-FP8"

hf download nvidia/Gemma-4-26B-A4B-NVFP4 \
  --local-dir "$HOME/DGX_TRANSFER/models/Gemma-4-26B-A4B-NVFP4"

hf download deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
  --local-dir "$HOME/DGX_TRANSFER/models/DeepSeek-R1-Distill-Qwen-32B"

hf download google/gemma-4-31B-it \
  --local-dir "$HOME/DGX_TRANSFER/models/gemma-4-31B-it"

hf download Qwen/Qwen3-Next-80B-A3B-Thinking-FP8 \
  --local-dir "$HOME/DGX_TRANSFER/models/Qwen3-Next-80B-A3B-Thinking-FP8"
```

`gpt-oss` 실험용 선택 다운로드 예시:

```bash
hf download openai/gpt-oss-20b \
  --include "model*.safetensors" "*.json" "*.model" "*.txt" \
  --local-dir "$HOME/DGX_TRANSFER/models/gpt-oss-20b"
```

checksum:

```bash
cd "$HOME/DGX_TRANSFER"
find models -type f -print0 | xargs -0 shasum -a 256 > manifests/SHA256SUMS.txt
du -sh models/*
```

### 5.2 SGLang 설치 후보 파일

SGLang 자체 PyPI wheel은 작다. `sglang==0.5.12` 기준 aarch64 wheel은 Python 버전별로 약 7.8 MB다.

다만 실제 SGLang 설치는 `torch`, `flashinfer`, `sglang-kernel`, `flash-attn-4`, `transformers` 등 대형/커널 의존성이 붙는다. PyPI metadata 기준 주요 직접 의존 wheel의 대략적인 크기는 다음과 같다.

| 패키지                | 버전/조건                           | 예상 크기 |
| --------------------- | ----------------------------------- | --------: |
| `sglang`            | `0.5.12`, cp311 aarch64           |    7.8 MB |
| `torch`             | `2.11.0`, cp311 manylinux aarch64 |  419.7 MB |
| `flashinfer_cubin`  | `0.6.11.post1`                    |  360.9 MB |
| `sglang-kernel`     | `0.4.2.post2`, aarch64            |  189.3 MB |
| `flashinfer_python` | `0.6.11.post1`                    |   13.7 MB |
| `tilelang`          | `0.1.8`, aarch64                  |   40.4 MB |
| `transformers`      | `5.6.0`                           |   10.4 MB |
| `torchvision`       | `0.27.0`, aarch64                 |    7.8 MB |
| `torchaudio`        | `2.11.0`, aarch64                 |    1.6 MB |

주요 직접 의존성만 합산해도 약 1.1 GB이며, 전체 resolver 결과는 추가 Python 의존성과 CUDA kernel wheel을 포함하므로 보수적으로 3~8 GB를 예상한다. 안전하게는 `sglang/wheelhouse`에 10~15 GB 여유를 둔다.

no-Docker 사전 다운로드 후보 명령:

```bash
python3 -m pip install -U pip
python3 -m pip download \
  --dest "$HOME/DGX_TRANSFER/sglang/wheelhouse" \
  --platform manylinux_2_34_aarch64 \
  --implementation cp \
  --python-version 3.11 \
  --abi cp311 \
  --only-binary=:all: \
  "sglang==0.5.12"
```

주의:

- 위 명령은 DGX에서 Python 3.11 venv를 쓸 계획일 때의 후보안이다.
- DGX에서 Python 3.10/3.12를 쓸 경우 `--python-version`과 `--abi`를 바꿔 다시 받아야 한다.
- 일부 커널 패키지는 ARM64 wheel 제공 여부와 CUDA 버전에 따라 실패할 수 있다. 실패하면 해당 목록을 기록하고 DGX 복구 후 온라인 설치로 보완한다.
- Docker image tar는 기본 계획에서 제외한다. 다만 native SGLang 설치가 실패하면 NVIDIA가 DGX Spark용으로 안내하는 NGC SGLang container를 fallback으로 검토한다.

---

## 6. DGX 복구 후 배치 경로

모델과 SGLang wheelhouse는 repo 안에 넣지 않는다.

권장 경로:

```text
/srv/ai-ops/llm/models/
/srv/ai-ops/sglang/
/srv/ai-ops/sglang/wheelhouse/
/srv/ai-ops/logs/sglang/
/srv/ai-ops/bin/run-sglang-local
/srv/ai-ops/bin/check-sglang-local
```

외장 SSD 또는 rsync 반입:

```bash
mkdir -p /srv/ai-ops/llm/models
rsync -avh --progress /media/$USER/DGX_TRANSFER/models/ /srv/ai-ops/llm/models/
rsync -avh --progress /media/$USER/DGX_TRANSFER/sglang/wheelhouse/ /srv/ai-ops/sglang/wheelhouse/
rsync -avh --progress /media/$USER/DGX_TRANSFER/manifests/ /srv/ai-ops/llm/manifests/

cd /srv/ai-ops/llm
shasum -a 256 -c manifests/SHA256SUMS.txt
```

---

## 7. SGLang 네이티브 설치 전략

Docker를 사용하지 않는 조건에서는 DGX 복구 후 아래 순서로 진행한다.

1. DGX의 Python, CUDA, torch, architecture 확인
2. 별도 venv 생성
3. SGLang minimal import 검증
4. `nvidia/Gemma-4-26B-A4B-NVFP4`로 launch_server smoke
5. `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` 검증
6. `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` 검증
7. 필요 시 `google/gemma-4-31B-it`, `Qwen3-Next-80B-A3B-Thinking-FP8` 비교 검증

초안:

```bash
mkdir -p /srv/ai-ops/sglang
cd /srv/ai-ops/sglang
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip uv

# 사전 다운로드한 wheelhouse가 있으면 먼저 시도한다.
python -m pip install --no-index --find-links /srv/ai-ops/sglang/wheelhouse "sglang==0.5.12"
```

주의:

- SGLang 공식 설치 문서는 pip/uv, source, Docker를 모두 지원하지만, DGX Spark 전용 공식 가이드는 컨테이너 경로를 우선 제시한다.
- no-Docker 조건에서는 source/venv 설치가 가능하더라도 CUDA 13, Blackwell, ARM64 wheel 호환성 검증이 필수다.
- SGLang 자체 설치는 wheelhouse로 먼저 시도하되, 실패 시 DGX 복구 후 온라인 설치 또는 NVIDIA NGC container fallback을 검토한다.

---

## 8. SGLang 실행 초안

초기 바인딩은 localhost로 제한한다.

```bash
source /srv/ai-ops/sglang/.venv/bin/activate

python -m sglang.launch_server \
  --model-path /srv/ai-ops/llm/models/Qwen3-Next-80B-A3B-Instruct-FP8 \
  --served-model-name qwen3-next-80b-instruct \
  --host 127.0.0.1 \
  --port 30000 \
  --trust-remote-code \
  --context-length 32768
```

검증:

```bash
curl -s http://127.0.0.1:30000/v1/models

curl -s http://127.0.0.1:30000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-next-80b-instruct",
    "messages": [{"role": "user", "content": "보험 약관 RAG 답변 생성 테스트입니다. 한 문장으로 답하세요."}],
    "temperature": 0.2,
    "max_tokens": 128
  }'
```

장문 context는 다음 순서로 확장한다.

```text
32768 -> 65536 -> 131072 -> 262144
```

---

## 9. 앱 코드 수정 계획

구현 방향:

1. `src/llm/openai_compatible_client.py` 추가 또는 `OpenAIClient` 일반화
2. `src/config.py`에 `LOCAL_LLM_*` 환경변수 추가
3. `src/llm/factory.py`에서 provider 분기 확장
4. `scripts/eval.py`, `scripts/cli.py`의 `OllamaClient` 직접 import 제거
5. Streamlit 모델 선택 UI에서 provider 라벨 분리
6. 관리자 페이지에 SGLang endpoint 상태 표시
7. Ollama fallback은 유지

권장 env:

```bash
LOCAL_LLM_PROVIDER=openai-compatible
LOCAL_LLM_BASE_URL=http://127.0.0.1:30000/v1
LOCAL_LLM_API_KEY=EMPTY
LOCAL_LLM_MODEL=qwen3-next-80b-instruct
LOCAL_LLM_CANDIDATE_MODELS=qwen3-next-80b-instruct,gemma-4-26b-nvfp4,deepseek-r1-qwen-32b,gemma-4-31b-it,qwen3-next-80b-thinking

ALLOW_OLLAMA=true
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=exaone3.5:7.8b
OLLAMA_CANDIDATE_MODELS=exaone3.5:7.8b
```

UI 라벨:

```text
Local · SGLang/OpenAI-compatible · qwen3-next-80b-instruct
Local · Ollama fallback · exaone3.5:7.8b
Cloud · OpenAI · ...
```

자동 fallback은 첫 구현에서 과하게 넣지 않는다. 사용자가 모델 선택으로 fallback을 고르는 방식이 디버깅과 평가 재현성에 더 안전하다.

---

## 10. 테스트 계획

단위 테스트:

```text
provider env parsing
OpenAI-compatible payload 생성
streaming SSE parsing
서버 연결 실패 시 명확한 오류 메시지
Ollama fallback 유지
list_available_models에서 SGLang 후보 노출
```

통합 검증:

```bash
pytest tests/test_llm_factory.py -v
pytest -q

# retrieval-only는 SGLang 없이도 통과해야 함
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 \
python scripts/eval.py --ocr

# SGLang 기동 후 LLM 포함
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
LOCAL_LLM_PROVIDER=openai-compatible \
LOCAL_LLM_BASE_URL=http://127.0.0.1:30000/v1 \
LOCAL_LLM_API_KEY=EMPTY \
LOCAL_LLM_MODEL=qwen3-next-80b-instruct \
python scripts/eval.py --ocr
```

정상 기준:

```text
retrieval recall@8: 1.000 유지
Streamlit에서 SGLang local 모델 답변 생성
Ollama fallback 선택 가능
```

---

## 11. Codex 구현 요청 프롬프트

```text
현재 insurance-rag-chatbot은 DGX Spark에서 Ollama exaone3.5:7.8b로 로컬 답변 생성을 수행한다. Docker는 기본 운영 방식으로 사용하지 않는다. SGLang은 DGX 복구 후 별도 venv에서 OpenAI-compatible endpoint로 띄울 예정이다.

목표:
보험 RAG 챗봇의 로컬 답변 생성 LLM에 SGLang OpenAI-compatible provider를 추가한다. 기존 Ollama exaone3.5:7.8b는 fallback으로 유지한다.

반드시 먼저 읽을 파일:
- src/llm/base.py
- src/llm/factory.py
- src/llm/ollama_client.py
- src/llm/openai_client.py
- src/config.py
- scripts/eval.py
- scripts/cli.py
- src/ui/streamlit_app.py
- src/ui/admin_page.py
- tests/test_llm_factory.py

구현 요구:
1. OpenAI-compatible local provider를 추가한다.
2. 다음 env를 지원한다.
   - LOCAL_LLM_PROVIDER=openai-compatible
   - LOCAL_LLM_BASE_URL=http://127.0.0.1:30000/v1
   - LOCAL_LLM_API_KEY=EMPTY
   - LOCAL_LLM_MODEL=qwen3-next-80b-instruct
   - LOCAL_LLM_CANDIDATE_MODELS=qwen3-next-80b-instruct,gemma-4-26b-nvfp4,deepseek-r1-qwen-32b,gemma-4-31b-it,qwen3-next-80b-thinking
3. Ollama 코드는 삭제하지 않는다.
4. scripts/eval.py와 scripts/cli.py의 OllamaClient 직접 의존을 factory/provider 기반으로 바꾼다.
5. Streamlit UI에서 Local SGLang과 Ollama fallback을 구분 표시한다.
6. OpenAI Vision OCR 후보정 코드는 건드리지 않는다.
7. docs에 DGX Spark + SGLang no-Docker 운영 절차를 추가한다.
8. 테스트를 추가한다.
   - env parsing
   - OpenAI-compatible request payload 생성
   - 서버 연결 실패 시 graceful error
   - Ollama fallback 유지
   - list_available_models에서 SGLang 후보 노출

제약:
- 모델 파일, Docker tar, /srv/ai-ops/llm/models는 git에 포함하지 않는다.
- API key/secret은 코드에 하드코딩하지 않는다.
- LOCAL_LLM_MODEL은 물리 경로가 아니라 served-model-name 논리 이름을 사용한다.
- retrieval-only eval 정상 기준을 깨지 않는다.
```

---

## 12. 참고 자료

- NVIDIA DGX Spark hardware overview: https://docs.nvidia.com/dgx/dgx-spark/hardware.html
- NVIDIA SGLang for DGX Spark: https://build.nvidia.com/spark/sglang/overview
- SGLang installation docs: https://docs.sglang.ai/get_started/install.html
- SGLang OpenAI-compatible API: https://sgl-project-sglang-93.mintlify.app/backend/openai-compatible-api
- Qwen3-Next-80B-A3B-Instruct-FP8: https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct-FP8
- DeepSeek-R1-Distill-Qwen-32B: https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
- Google Gemma 4 announcement: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- google/gemma-4-31B-it: https://huggingface.co/google/gemma-4-31B-it
- nvidia/Gemma-4-26B-A4B-NVFP4: https://huggingface.co/nvidia/Gemma-4-26B-A4B-NVFP4
- openai/gpt-oss-20b: https://huggingface.co/openai/gpt-oss-20b
- openai/gpt-oss-120b: https://huggingface.co/openai/gpt-oss-120b
- GLM-4.5-Air-FP8: https://huggingface.co/zai-org/GLM-4.5-Air-FP8
- Llama 4 Scout: https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct
