# 245 GPT-OSS 120B DGX Spark 편입 불가 판정 보고서

## 1. 결론

현재 프로젝트의 DGX Spark 환경에서는 `gpt-oss-120b`를 보험 RAG 앱의 사용 가능한 LLM 모델로 편입하지 않는다.

이 결론은 “GPT-OSS 120B가 어떤 환경에서도 실행 불가능하다”는 뜻이 아니다. 이 보고서의 판단 범위는 다음 조건으로 제한된다.

- 하드웨어: DGX Spark, `NVIDIA GB10`
- 로컬 모델 경로: `/srv/ai-ops/llm/models/gpt-oss-120b`
- 검토한 서빙 경로: SGLang, vLLM, Transformers 계열 로컬 로딩, TensorRT-LLM
- 운영 요구사항: 앱 기동 안정성, OpenAI-compatible `/health`, `/v1/models`, `/v1/chat/completions` 응답, 보험 RAG 앱과 병행 가능한 메모리 여유

프로젝트 판정:

```text
gpt-oss-120b는 로컬 파일이 존재하지만, 현재 DGX Spark 앱에서 실행 가능한 모델로 지원하지 않는다.
상태는 available이 아니라 blocked_runtime으로 취급한다.
```

## 2. 왜 편입 불가능으로 판단했는가

### 2.1 단일 실패가 아니라 여러 경로의 누적 실패다

`gpt-oss-120b` 편입 불가 판정은 TensorRT-LLM 명령 하나가 실패했기 때문만은 아니다. 이전 SGLang 계열 검토와 이번 TensorRT-LLM smoke 결과를 합쳐 내린 판단이다.

프로젝트 내부 근거:

- `docs/206_PROJECT_DEVELOPMENT_ENVIRONMENT.md`
  - `gpt-oss-120b`는 로컬 파일 다운로드는 되었으나 DGX Spark 메모리 부족으로 실사용 기동 실패로 기록되어 있다.
- `docs/207_PROJECT_ENVIRONMENT_AND_DATABASE_OVERVIEW.md`
  - SGLang 경로에서 파일은 staged 상태지만, DGX Spark 메모리 부족으로 현재 실사용 불가로 기록되어 있다.
- `docs/72_DGX_SPARK_SGLANG_LOCAL_LLM_PLAN.md`
  - `openai/gpt-oss-120b`는 품질 검토 후보로는 의미가 있으나, 크기와 serving format 제약 때문에 1차 운영 후보에서 제외되어 있다.
- 이번 TensorRT-LLM 실기동 결과
  - 모델 로딩과 warmup까지 진입했지만 `Only SM100 is supported by FP4 block scale MOE`로 종료됐다.

즉, 문제는 “스크립트 옵션 하나를 고치면 되는 오류”가 아니라 현재 DGX Spark에서 120B급 MXFP4/MoE 모델을 안정적으로 앱 서빙하는 경로가 없다는 점이다.

### 2.2 SGLang/vLLM/Transformers 계열은 메모리와 운영성 기준을 만족하지 못했다

SGLang 경로는 이미 이전 검토에서 DGX Spark 메모리 부족으로 실사용 기동 실패로 기록되어 있다. vLLM과 Transformers 계열도 현재 프로젝트에서 `gpt-oss-120b`에 대해 안정적인 smoke 통과 기록이 없다.

설령 Transformers 계열에서 CPU/offload/swap을 강하게 사용해 “로드만” 시도할 수 있더라도, 이것은 앱 편입 기준을 만족하지 않는다. 보험 RAG 앱에서 필요한 것은 단순 로딩 성공이 아니라 다음 조건이다.

- 서버가 안정적으로 떠 있어야 한다.
- `/health`, `/v1/models`, `/v1/chat/completions`가 일관되게 응답해야 한다.
- RAG 검색, reranker, FastAPI 앱, 프론트엔드 요청과 병행해도 메모리 압박으로 죽지 않아야 한다.
- 사용자가 일반 질의를 할 때 실무적으로 기다릴 수 있는 속도로 답해야 한다.

현재 120B 경로는 이 조건을 만족한다는 증거가 없다.

### 2.3 TensorRT-LLM 경로는 메모리 문제가 아니라 커널/하드웨어 호환성에서 막혔다

TensorRT-LLM 재시도 전 저장공간을 확보하고, Docker image pull과 모델 파일 확인까지 완료했다.

실행 명령:

```bash
/srv/ai-ops/bin/switch-trtllm-model openai/gpt-oss-120b
```

실패 결과:

```text
TensorRT-LLM session exited while loading openai/gpt-oss-120b
RuntimeError: Only SM100 is supported by FP4 block scale MOE
RuntimeError: Executor worker returned error
```

관측된 진행:

- Docker container 시작 성공
- 모델 파일 인식 성공
- TensorRT-LLM이 model weights에 `68.67 GB`를 할당
- GPT-OSS MoE warmup 중 `mxe4m3_mxe2m1_block_scale_moe_runner` 경로에서 실패

해석:

- 저장공간 부족이 아니다.
- Docker image 부재가 아니다.
- 모델 파일 미완성이 아니다.
- 가장 강한 원인은 DGX Spark의 `NVIDIA GB10` 환경에서 현재 TensorRT-LLM GPT-OSS FP4/MXFP4 MoE 커널 경로가 지원되지 않는 것이다.

공식 참고:

- NVIDIA GPT-OSS TensorRT-LLM deployment guide: https://nvidia.github.io/TensorRT-LLM/deployment-guide/deployment-guide-for-gpt-oss-on-trtllm.html
- OpenAI GPT-OSS 120B model card: https://huggingface.co/openai/gpt-oss-120b

## 3. Backend별 판정

| Backend | 프로젝트 판정 | 이유 |
|---|---|---|
| SGLang | `gpt-oss-120b` 편입 불가 | 이전 DGX Spark 기동 시 메모리 부족으로 실사용 실패 기록이 있다. |
| vLLM | `gpt-oss-120b` 편입 불가 | 이 프로젝트에서 안정적인 120B smoke 통과 기록이 없고, 예상 메모리 압박이 운영 기준을 넘는다. |
| Transformers/local Python | 앱 서빙 경로로 부적합 | offload로 로딩 가능성을 실험할 수는 있어도 속도, 안정성, 메모리 여유 기준을 만족하기 어렵다. |
| TensorRT-LLM | DGX Spark GB10에서 편입 불가 | 실제 smoke에서 `Only SM100 is supported by FP4 block scale MOE`로 실패했다. |

## 4. 프로젝트에 미치는 영향

### 4.1 앱 기본 모델 정책

`gpt-oss-120b`를 앱 기본값, 운영 선택지, DGX 바탕화면 실행기의 일반 시작 후보로 노출하면 안 된다.

필요한 정책:

- `gpt-oss-120b`는 `available`이 아니라 `blocked_runtime`으로 표시한다.
- 일반 사용자용 모델 선택 UI에서는 숨기거나 비활성화한다.
- 관리자 진단에서는 “파일은 있으나 현재 DGX Spark runtime 미지원”으로 표시한다.
- 앱 기본 모델은 기존 검증 모델로 유지한다.

### 4.2 모델 파일 보존 정책

`/srv/ai-ops/llm/models/gpt-oss-120b`는 당장 삭제하지 않는다. 이유는 다음과 같다.

- 이미 다운로드된 대형 artifact라 재확보 비용이 크다.
- 향후 TensorRT-LLM/driver/runtime이 GB10 호환 경로를 제공할 경우 재검증에 사용할 수 있다.
- 외부 또는 내부 상위 GPU 서버로 이전 검증할 때 기준 artifact로 사용할 수 있다.

다만 “파일이 있음”은 “운영 가능”을 의미하지 않는다. 이 둘은 반드시 분리해서 표시해야 한다.

### 4.3 저장공간 영향

120B TensorRT-LLM 실패 경로 전용으로 받은 Docker image는 결론 이후 삭제했다.

삭제한 image:

```text
nvcr.io/nvidia/tensorrt-llm/release:spark-single-gpu-dev
```

삭제 전후:

```text
삭제 전 / 여유: 85G, 사용률 91%
삭제 후 / 여유: 120G, 사용률 87%
```

보존한 항목:

- `/srv/ai-ops/llm/models/*`
- `vllm/vllm-openai:v0.20.1`
- `paddleocr-vl:latest-nvidia-gpu-sm120`
- 사용자별 `/srv/shared/workspaces/*`
- 프로젝트 `.git`

## 5. 편입을 위해 필요한 조건

`gpt-oss-120b`를 다시 편입 후보로 올리려면 최소 하나 이상의 조건이 충족되어야 한다.

### 5.1 DGX Spark GB10 호환 TensorRT-LLM 경로가 공식 제공되어야 한다

필요 조건:

- NVIDIA가 GB10/DGX Spark에서 GPT-OSS 120B FP4/MXFP4 MoE를 지원한다고 문서화
- 해당 image 또는 runtime에서 `Only SM100 is supported by FP4 block scale MOE` 문제가 해결
- `/health`, `/v1/models`, `/v1/chat/completions` smoke 통과
- 보험 RAG 앱과 연결한 실제 질의 smoke 통과

### 5.2 다른 local backend가 120B 전체 smoke를 통과해야 한다

SGLang, vLLM, Transformers 계열 중 하나가 다음을 통과해야 한다.

- 모델 서버 안정 기동
- OpenAI-compatible endpoint 응답
- 최소 1건 이상의 한국어 보험 RAG 질의 응답
- 앱과 병행 시 메모리 여유 확인
- 재시작 후 동일하게 재현 가능

단순히 “로드가 한 번 됨”은 편입 조건이 아니다.

### 5.3 120B를 지원 가능한 별도 GPU 서버에서 운영해야 한다

현실적인 대안은 120B를 DGX Spark가 아닌 지원 GPU 서버에서 띄우고, 보험 RAG 앱은 OpenAI-compatible endpoint로 연결하는 것이다.

이 경우에도 다음 조건이 필요하다.

- 금융권 망분리 정책에 맞는 내부망 또는 승인된 폐쇄망 endpoint
- API key/접속정보의 안전한 관리
- 장애 시 DGX Spark 검증 모델로 fallback
- 답변 품질 평가와 지연 시간 평가

## 6. 현재 권장 운영 방향

`gpt-oss-120b`는 연구/재검증용 artifact로 보존하되, 현재 운영 로직에서는 제외한다.

권장 상태:

```text
model_id: gpt-oss-120b
artifact: present
runtime_status: blocked_runtime
app_default: false
user_selectable: false
admin_visible: true
reason: DGX Spark GB10에서 SGLang 메모리 실패 및 TensorRT-LLM FP4/MoE 커널 미지원
```

운영 모델은 이미 smoke 또는 평가를 통과한 후보를 우선한다.

- SGLang `gpt-oss-20b`
- Qwen 계열 검증 후보
- Gemma/Nemotron/vLLM 계열 검증 후보
- 필요 시 Ollama fallback

## 7. 검증 기록

스크립트 문법 검증:

```bash
bash -n ops/bin/switch-trtllm-model ops/bin/insurance-rag-up ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher
```

결과: 통과

관련 Python 테스트:

```bash
.venv/bin/python -m pytest tests/test_llm_factory.py -q
```

결과: `22 passed`

## 8. 남은 위험

- 미래의 NVIDIA driver, TensorRT-LLM image, model artifact 변경으로 이 결론이 바뀔 수 있다.
- 하지만 현재 기준으로는 성공한 120B smoke run이 없으므로, 운영 앱에 편입하면 앱 기동 실패와 사용자 혼란을 만들 가능성이 높다.
- 따라서 재검증 전까지 `gpt-oss-120b`는 “다운로드됨”이 아니라 “실행 차단됨”으로 표현해야 한다.
