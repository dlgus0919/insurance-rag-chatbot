# 101. DGX 오프라인 Streamlit 테스트 런처 구현 보고서

## 목적

DGX Spark의 메인 프로젝트 디렉터리에서 로컬/망분리 조건의 Streamlit 테스트를 한 번의 터미널 명령으로 시작할 수 있도록 전용 실행 스크립트를 추가했다.

기존에는 테스트 전 다음 작업을 수동으로 나눠 수행해야 했다.

- `/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh` 및 `offline.env` 로드
- 오프라인 임베딩/reranker/LLM asset 존재 확인
- OCR v2 manual 및 v1/v2 combined index 존재 확인
- SGLang, vLLM, Ollama provider 준비 상태 확인
- GPU 메모리 경합 방지를 위한 `CUDA_VISIBLE_DEVICES=""` 적용
- Streamlit 실행 및 로그 파일 생성

## 추가 파일

- `scripts/run_offline_streamlit_test.sh`

## 핵심 동작

`scripts/run_offline_streamlit_test.sh`는 다음 순서로 동작한다.

1. 프로젝트 `.venv`를 활성화한다.
2. 존재하는 경우 `/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh`를 로드한다.
3. 기본적으로 `scripts/prepare_offline_assets.py`를 실행해 오프라인 asset 준비/검증을 수행한다.
4. 존재하는 경우 `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`를 로드한다.
5. 다음 오프라인 실행 기본값을 명시적으로 적용한다.
   - `OFFLINE_MODE=true`
   - `HF_MODEL_DOWNLOAD=false`
   - `HF_HUB_OFFLINE=1`
   - `TRANSFORMERS_OFFLINE=1`
   - `EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3`
   - `RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3`
   - `SGLANG_DEFAULT_MODEL=gpt-oss-20b`
   - `VLLM_DEFAULT_MODEL=gemma-4-26b-a4b-nvfp4`
   - `ALLOW_OLLAMA=true`
   - `OLLAMA_MODEL=exaone3.5:7.8b`
6. `FORCE_GPU=1`이 아닌 경우 `CUDA_VISIBLE_DEVICES=""`를 적용해 Streamlit/RAG 임베딩이 GPU를 점유하지 않게 한다.
7. 기본 인덱스, OCR v2 manual 인덱스, v1/v2 combined 인덱스, 비급여 표준코드 DB, 모델 전환 wrapper 존재를 확인한다.
8. SGLang/vLLM/Ollama endpoint 상태를 표시한다.
9. 지정 포트로 Streamlit을 실행하고 `logs/offline_streamlit_test_YYYYMMDD_HHMMSS.log`에 로그를 저장한다.

## 실행 명령

DGX에 접속한 뒤:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/run_offline_streamlit_test.sh
```

맥북에서 SSH 접속까지 한 번에 실행하려면:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && bash scripts/run_offline_streamlit_test.sh"
```

이 명령은 foreground로 Streamlit을 실행한다. 종료하려면 해당 터미널에서 `Ctrl+C`를 누른다.

## 맥북 브라우저 접속

Streamlit 실행 터미널은 그대로 둔 상태에서, 맥북의 다른 터미널을 열어 SSH 터널을 연결한다.

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저에서 접속한다.

```text
http://localhost:8501
```

## 자주 쓰는 옵션

포트가 이미 사용 중일 때 기존 보험 RAG Streamlit 프로세스를 교체 실행:

```bash
bash scripts/run_offline_streamlit_test.sh --replace
```

8502 포트로 실행:

```bash
bash scripts/run_offline_streamlit_test.sh --port 8502
```

OCR v2 manual 또는 v1/v2 combined 인덱스 생성이 아직 끝나지 않았지만 기본 인덱스만으로 먼저 앱을 열 때:

```bash
bash scripts/run_offline_streamlit_test.sh --allow-missing-ocr-indexes
```

오프라인 asset 준비 스크립트 실행을 생략하고 빠르게 실행할 때:

```bash
bash scripts/run_offline_streamlit_test.sh --skip-asset-prep
```

임베딩/reranker 실제 로드 검증을 생략하고 asset 파일 존재 중심으로 실행할 때:

```bash
bash scripts/run_offline_streamlit_test.sh --no-verify-load
```

## 모델 테스트 흐름

1. 앱 로그인 화면에서 대형 로컬 모델을 선택한다.
   - `SGLang · gpt-oss-20b`
   - `vLLM · gemma-4-26b-a4b-nvfp4`
2. 로그인 후 일반 질의, 퀵 코드 검색, 약관 정형 검색, 보험금 계산을 각각 테스트한다.
3. 사이드바의 `LLM Provider`와 `LLM 모델` 드롭다운에서 사용 가능한 provider/model 조합을 확인한다.
4. 작은 fallback 모델 검증이 필요하면 Ollama provider와 `exaone3.5:7.8b`를 선택한다.

대형 모델은 동시에 여러 개를 상주시킨다는 전제가 아니다. 로그인 단계 또는 앱 내 전환 시 기존 `/srv/ai-ops/bin/switch-sglang-model`, `/srv/ai-ops/bin/switch-vllm-model` wrapper가 반대쪽 대형 모델 세션을 종료하고 선택한 모델만 올린다.

## 기대되는 테스트 범위

스크립트 기본 모드에서 모든 필수 asset과 인덱스가 존재하면 다음 기능을 망분리 조건으로 테스트할 수 있다.

- 기본 RAG 질의
- 퀵 코드 검색
- 약관 정형 검색
- 보험금 지급예상액 계산
- OCR v2 manual index mode
- OCR v1/v2 combined comparison mode
- SGLang `gpt-oss-20b`
- vLLM `gemma-4-26b-a4b-nvfp4`
- Ollama `exaone3.5:7.8b` fallback

## 주의사항

- 이 스크립트는 Streamlit/RAG 임베딩을 CPU 모드로 실행한다. 대형 LLM provider는 선택한 모델에 따라 SGLang 또는 vLLM wrapper가 별도 tmux session에서 GPU/unified memory를 사용한다.
- `--replace`는 기존 보험 RAG Streamlit 프로세스를 종료할 수 있으므로, 다른 팀원이 같은 공용 앱을 보고 있는 경우 사용 전에 확인한다.
- OCR v2 manual 인덱스 생성 중에는 기본 모드가 missing index로 중단될 수 있다. 이 경우 생성 완료 후 다시 실행하거나 `--allow-missing-ocr-indexes`로 기본 인덱스만 테스트한다.
- 모델 파일, 인덱스, 로그, `/srv/ai-ops` runtime 산출물은 Git 커밋 대상이 아니다.

## 검증

구현 후 실행한 검증:

```bash
bash -n scripts/run_offline_streamlit_test.sh
```

대형 모델 기동, Streamlit 실제 브라우저 테스트, v2 manual 인덱스 사용 테스트는 현재 사용자가 별도로 진행 중인 인덱스 생성 작업과 GPU/RAM 자원 경합을 피하기 위해 이번 커밋 전 자동 실행하지 않았다.
