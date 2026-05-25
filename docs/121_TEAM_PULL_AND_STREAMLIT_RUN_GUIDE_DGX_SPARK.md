# 121. 팀원 Pull 이후 Streamlit 실행 가이드 (DGX Spark)

작성일: 2026-05-26

## 목적

이 문서는 팀원이 DGX Spark에 **본인 Linux 계정**으로 로그인한 뒤, 개인 워크스페이스에서 GitHub `master`를 pull하고 최신 Streamlit 앱을 실행해보는 절차를 정리한다.

전제:

- 팀원은 `/srv/shared/projects/insurance-rag-chatbot` 공용 repo를 직접 수정하지 않는다.
- 팀원은 `/srv/shared/workspaces/<user>/insurance-rag-chatbot` 개인 워크스페이스에서 실행한다.
- 대형 모델, secret, OCR 원본, Chroma/BM25/GraphDB 산출물은 GitHub에 올라가지 않는다.
- 공용 DGX Spark에는 `/srv/ai-ops`와 공용 repo의 런타임 산출물이 이미 준비되어 있다.

## 현재 공용 런타임 상태

공용 준비 완료 모델:

| 모델 | Provider | 실행 포트 | 상태 |
| --- | --- | --- | --- |
| `nemotron-3-nano-30b-a3b-nvfp4` | vLLM | `30001` | 검증 완료, 권장 신규 테스트 모델 |
| `qwen3-30b-a3b-instruct-2507-fp8` | SGLang | `30000` | 검증 완료, 신규 비교 테스트 모델 |
| `gpt-oss-20b` | SGLang | `30000` | 기존 비교 기준 모델 |
| `gemma-4-26b-a4b-nvfp4` | vLLM | `30001` | 기존 비교 기준 모델 |

주의:

- Nemotron은 SGLang 경로에서 첫 chat completion 단계가 불안정하므로 **vLLM 경로만 사용**한다.
- Qwen은 SGLang 경로로 사용한다.
- 대형 모델은 한 번에 하나만 GPU에 올리는 것을 원칙으로 한다.

## 1. 개인 계정으로 접속

Mac에서:

```bash
ssh <user>@100.88.5.57
```

DGX shell에서 본인 계정인지 확인:

```bash
whoami
```

## 2. 개인 워크스페이스 준비

이미 clone이 있으면:

```bash
cd /srv/shared/workspaces/$USER/insurance-rag-chatbot
git status --short
git branch --show-current
git pull origin master
```

처음 clone하는 경우:

```bash
mkdir -p /srv/shared/workspaces/$USER
cd /srv/shared/workspaces/$USER
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
```

가상환경이 없다면 공용 repo와 같은 방식으로 준비한다. 이미 `.venv`가 있는 경우 이 단계는 건너뛴다.

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

## 3. GitHub에 없는 런타임 파일 연결

개인 워크스페이스에는 GitHub에 없는 `data/` 산출물이 없을 수 있다. 가장 빠른 방법은 공용 repo에서 복사하는 것이다.

```bash
cd /srv/shared/workspaces/$USER/insurance-rag-chatbot
mkdir -p data reports

rsync -a /srv/shared/projects/insurance-rag-chatbot/data/extracted/ data/extracted/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/extracted_v2_manual/ data/extracted_v2_manual/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/processed/ data/processed/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index/ data/index/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index_v2_manual/ data/index_v2_manual/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index_v1_v2_combined/ data/index_v1_v2_combined/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/mapping/ data/mapping/
rsync -a /srv/shared/projects/insurance-rag-chatbot/reports/mapping_low_confidence/ reports/mapping_low_confidence/ 2>/dev/null || true
```

필수 파일 빠른 확인:

```bash
test -f data/index/bm25.pkl
test -f data/index/chroma/chroma.sqlite3
test -f data/index_v2_manual/bm25.pkl
test -f data/index_v2_manual/chroma/chroma.sqlite3
test -f data/index_v1_v2_combined/bm25.pkl
test -f data/index_v1_v2_combined/chroma/chroma.sqlite3
test -f data/index/relational/standard_codes.sqlite
test -f data/index/graph/insurance_graph.sqlite
```

## 4. 공용 LLM 모델과 switch script 확인

아래 파일은 repo 밖 공용 `/srv/ai-ops`에 있어야 한다.

```bash
test -f /srv/ai-ops/llm/models/nemotron-3-nano-30b-a3b-nvfp4/config.json
test -f /srv/ai-ops/llm/models/qwen3-30b-a3b-instruct-2507-fp8/config.json
test -f /srv/ai-ops/llm/models/qwen3-30b-a3b-instruct-2507-fp8/chat_template.jinja
test -f /srv/ai-ops/llm/models/gpt-oss-20b/config.json
test -f /srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4/config.json
test -x /srv/ai-ops/bin/switch-vllm-model
test -x /srv/ai-ops/bin/switch-sglang-model
```

모델 서버 상태 확인:

```bash
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30001/v1/models || true
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30000/v1/models || true
```

## 5. Streamlit 실행

개인 계정은 공용 secret 파일 권한이 없을 수 있으므로, 아래처럼 secret 자동 로드를 비활성화하고 공용 `/srv/ai-ops` 모델 경로를 명시한다.

```bash
cd /srv/shared/workspaces/$USER/insurance-rag-chatbot

PRIVATE_ENV_FILE=/dev/null \
OFFLINE_ENV_FILE=/dev/null \
RERANKER_ENABLED=false \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
VLLM_BASE_URL=http://127.0.0.1:30001/v1 \
VLLM_API_KEY=EMPTY \
VLLM_DEFAULT_MODEL=nemotron-3-nano-30b-a3b-nvfp4 \
VLLM_CANDIDATE_MODELS=nemotron-3-nano-30b-a3b-nvfp4,gemma-4-26b-a4b-nvfp4 \
VLLM_STRICT_AVAILABLE_MODELS=false \
VLLM_ENABLE_APP_SWITCH=true \
VLLM_SWITCH_SCRIPT=/srv/ai-ops/bin/switch-vllm-model \
SGLANG_BASE_URL=http://127.0.0.1:30000/v1 \
SGLANG_API_KEY=EMPTY \
SGLANG_DEFAULT_MODEL=qwen3-30b-a3b-instruct-2507-fp8 \
SGLANG_CANDIDATE_MODELS=qwen3-30b-a3b-instruct-2507-fp8,gpt-oss-20b \
SGLANG_STRICT_AVAILABLE_MODELS=false \
SGLANG_ENABLE_APP_SWITCH=true \
SGLANG_SWITCH_SCRIPT=/srv/ai-ops/bin/switch-sglang-model \
bash scripts/prepare_streamlit_runtime.sh \
  --run-streamlit \
  --replace \
  --port 8502 \
  --skip-offline-assets \
  --cpu-index
```

권장 포트:

- 공용 관리자 검증: `8501`
- 팀원 개인 테스트: `8502`, `8503`, `8504` 등 서로 다른 포트

## 6. Mac에서 접속

Streamlit을 `8502`로 열었다면 Mac에서:

```bash
ssh -L 8502:localhost:8502 <user>@100.88.5.57
```

브라우저:

```text
http://localhost:8502
```

## 7. 모델 선택 기준

우선 순서:

1. `vllm:nemotron-3-nano-30b-a3b-nvfp4`
2. `sglang:qwen3-30b-a3b-instruct-2507-fp8`
3. 기존 비교용 `sglang:gpt-oss-20b`
4. 기존 비교용 `vllm:gemma-4-26b-a4b-nvfp4`

모델 전환은 시간이 걸린다. 전환 중에는 다른 대형 모델 기동 명령을 추가로 실행하지 않는다.

직접 전환해야 할 때:

```bash
/srv/ai-ops/bin/switch-vllm-model nemotron-3-nano-30b-a3b-nvfp4
/srv/ai-ops/bin/switch-sglang-model qwen3-30b-a3b-instruct-2507-fp8
```

## 8. Smoke 질문

Streamlit 접속 후 아래 질문으로 먼저 확인한다.

```text
N39.3 진단으로 질병급여 실손의료비 청구가 가능한가요?
```

```text
전신성 복막염 수술의 1-3종, 1-5종, 신1-5종 수술종수를 알려주세요.
```

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘.
```

```text
심평원 문서에서 ZZ9999 코드의 항목명과 점수를 알려주세요.
```

정상 기준:

- 빈 답변이 아니어야 한다.
- 출처가 표시되어야 한다.
- 없는 코드 질문은 지어내지 않고 확인 불가로 답해야 한다.
- GraphDB 관련 질문은 구조화 근거 또는 candidate/missing 상태를 구분해야 한다.

## 9. 문제 해결

### 9.1 포트가 이미 사용 중

```bash
ss -tlnp | grep ':8502' || true
pgrep -af "streamlit run src/ui/streamlit_app.py"
```

자기 계정 프로세스만 종료한다.

```bash
pkill -u $USER -f "streamlit run src/ui/streamlit_app.py" || true
```

다른 팀원 또는 `ai-hang` 소유 프로세스는 임의로 종료하지 않는다.

### 9.2 모델 endpoint가 안 뜸

현재 모델 확인:

```bash
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30001/v1/models || true
curl -fsS -H "Authorization: Bearer EMPTY" http://127.0.0.1:30000/v1/models || true
```

로그 확인:

```bash
tail -120 /srv/ai-ops/logs/vllm/gemma4.log
tail -120 /srv/ai-ops/logs/sglang/sglang-local.log
```

### 9.3 GraphDB 누락

공용 repo에서 복사:

```bash
mkdir -p data/index/graph
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index/graph/ data/index/graph/
```

검증:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
```

### 9.4 secret 권한 오류

개인 계정에서 `/srv/ai-ops/secrets/...` 접근 오류가 나면, 실행 명령에 아래 두 값을 반드시 포함한다.

```bash
PRIVATE_ENV_FILE=/dev/null
OFFLINE_ENV_FILE=/dev/null
```

secret 파일 내용을 출력하거나 복사하지 않는다.

## 10. 테스트 결과 공유 양식

팀원이 테스트 후 공유할 최소 정보:

```text
계정:
workspace:
git commit:
Streamlit port:
선택 모델:
질문:
답변 요약:
출처 표시 여부:
오류 로그:
재현 명령:
```

현재 commit 확인:

```bash
git rev-parse --short HEAD
```

Streamlit 로그:

```bash
ls -t logs/*streamlit* | head
tail -120 <로그파일>
```
