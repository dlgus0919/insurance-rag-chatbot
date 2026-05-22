# 103. Streamlit 실행 전 런타임 준비 가이드

## 목적

이 문서는 팀원이 GitHub `master`를 pull한 뒤 DGX Spark에서 Streamlit 앱을 실행하기 전에 확인해야 할 작업을 정리한다.

중요한 전제:

- GitHub에는 코드와 문서만 올라간다.
- OCR 원본/보정본, Chroma/BM25 인덱스, 대형 LLM 모델, secret/env 파일은 GitHub에 올리지 않는다.
- 따라서 새 워크스페이스나 새 clone에서 앱을 실행하려면 Git에 없는 런타임 파일을 먼저 준비해야 한다.
- 공용 운영 repo `/srv/shared/projects/insurance-rag-chatbot`에는 현재 필요한 런타임 파일이 준비되어 있다. 개인 워크스페이스에서 실행할 경우 아래의 비-Git 파일 준비 절차를 따른다.

## 현재 권장 실행 위치

관리자/공용 검증은 아래 메인 repo에서 수행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
```

팀원 개인 개발은 각자 워크스페이스에서 수행하되, Streamlit 전체 기능 검증은 공용 repo 또는 공용 repo에서 런타임 파일을 복사한 워크스페이스에서만 안정적으로 가능하다.

예시:

```bash
cd /srv/shared/workspaces/<user>/insurance-rag-chatbot
git pull origin master
```

## Streamlit 중단

기존 Streamlit만 중단하려면:

```bash
pkill -f '[s]treamlit run src/ui/streamlit_app.py' || true
pkill -f '[r]un_offline_streamlit_test.sh' || true
ss -tlnp | grep ':8501' || true
```

`8501` 출력이 없으면 Streamlit 포트는 비어 있다.

대형 모델 서버까지 내리는 명령은 별도이다. Gemma4/vLLM을 끄려면:

```bash
tmux kill-session -t vllm-gemma4 2>/dev/null || true
```

SGLang을 끄려면:

```bash
tmux kill-session -t sglang-local 2>/dev/null || true
```

## GitHub에 없는 필수 런타임 파일

아래 파일/디렉터리는 Streamlit 전체 기능 실행에 필요하지만 GitHub에는 올라가지 않는다.

### 1. OCR 원본 데이터

필수:

```text
data/extracted/실무가이드/manifest.json
data/extracted/상담사례집/manifest.json
data/extracted/실무가이드/text/
data/extracted/실무가이드/tables/
data/extracted/상담사례집/text/
data/extracted/상담사례집/tables/
```

새 워크스페이스에 없으면 공용 repo에서 복사한다.

```bash
mkdir -p data
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/extracted/ data/extracted/
```

### 2. OCR v2 manual 보정 데이터

둘 중 하나가 필요하다.

권장: 공용 repo에서 이미 풀린 보정본을 복사한다.

```bash
mkdir -p data
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/extracted_v2_manual/ data/extracted_v2_manual/
```

또는 handoff 압축본을 워크스페이스에 둔다.

```text
handoff/ocr_v2_manual_handoff_YYYYMMDD.tar.gz
```

이 압축본이 있으면 `scripts/prepare_streamlit_runtime.sh`가 `data/extracted_v2_manual/`이 없을 때 자동 반입한다.

### 3. 비급여 표준코드 SQLite DB

보험금 지급예상액 계산 기능에 필요하다.

```text
data/index/relational/standard_codes.sqlite
```

새 워크스페이스에 없으면:

```bash
mkdir -p data/index/relational
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index/relational/standard_codes.sqlite \
  data/index/relational/standard_codes.sqlite
```

### 4. 생성 산출물: chunks, indexes, mapping

아래 파일들은 GitHub에 없지만 `scripts/prepare_streamlit_runtime.sh`가 생성할 수 있다.

```text
data/processed/chunks_v1_original_ocr.jsonl
data/processed/chunks_v1_rechunked_only_sangdam.jsonl
data/processed/chunks_v1_rechunked_target16.jsonl
data/processed/chunks_v2_manual.jsonl
data/processed/chunks_v1_v2_combined.jsonl
data/index_v2_manual/
data/index_v1_v2_combined/
data/mapping/v1_v2_pairs_실무가이드.jsonl
data/mapping/v1_v2_pairs_상담사례집.jsonl
reports/mapping_low_confidence/
```

시간을 줄이고 싶으면 공용 repo의 이미 생성된 산출물을 복사한다.

```bash
mkdir -p data reports
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/processed/ data/processed/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index_v2_manual/ data/index_v2_manual/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/index_v1_v2_combined/ data/index_v1_v2_combined/
rsync -a /srv/shared/projects/insurance-rag-chatbot/data/mapping/ data/mapping/
rsync -a /srv/shared/projects/insurance-rag-chatbot/reports/mapping_low_confidence/ reports/mapping_low_confidence/
```

재생성하려면 아래 통합 스크립트를 실행한다.

### 5. 로컬 임베딩/reranker/LLM 모델

아래는 repo 밖 `/srv/ai-ops`에 있어야 한다.

```text
/srv/ai-ops/models/embedding/bge-m3/
/srv/ai-ops/models/reranker/bge-reranker-v2-m3/
/srv/ai-ops/llm/models/gpt-oss-20b/
/srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4/
/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja
```

공용 DGX에서는 준비되어 있다. 누락되었을 때는 네트워크가 가능한 상태에서 다음을 실행한다.

```bash
.venv/bin/python scripts/prepare_offline_assets.py \
  --root /srv/ai-ops \
  --env-path /srv/ai-ops/secrets/insurance-rag-chatbot/offline.env
```

완전 망분리 상태라면 위 다운로드는 실패한다. 이 경우 모델 디렉터리를 외부 저장소나 handoff에서 `/srv/ai-ops`로 먼저 반입해야 한다.

### 6. secret/env 및 운영 wrapper

아래 파일은 GitHub에 올리지 않는다.

```text
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env
/srv/ai-ops/bin/switch-vllm-model
/srv/ai-ops/bin/switch-sglang-model
```

주의:

- secret 파일 내용을 출력하거나 문서에 붙여넣지 않는다.
- 개인 워크스페이스에서 실행하더라도 공용 secret 파일은 관리자 정책에 따라 접근 권한이 제한될 수 있다.
- 접근 권한이 없으면 공용 repo에서 관리자 계정으로 Streamlit을 실행해 테스트한다.

## 현재 DGX 공용 repo 기준 준비 상태

2026-05-22 기준 공용 repo와 `/srv/ai-ops`에는 다음이 준비되어 있음을 확인했다.

```text
OK data/extracted/실무가이드/manifest.json
OK data/extracted/상담사례집/manifest.json
OK data/extracted_v2_manual/실무가이드/manifest.json
OK data/extracted_v2_manual/상담사례집/manifest.json
OK data/index/relational/standard_codes.sqlite
OK /srv/ai-ops/models/embedding/bge-m3/config.json
OK /srv/ai-ops/models/reranker/bge-reranker-v2-m3/config.json
OK /srv/ai-ops/llm/models/gpt-oss-20b/config.json
OK /srv/ai-ops/llm/models/gemma-4-26b-a4b-nvfp4/config.json
OK /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
OK /srv/ai-ops/secrets/insurance-rag-chatbot/offline.env
OK /srv/ai-ops/bin/switch-vllm-model
OK /srv/ai-ops/bin/switch-sglang-model
```

## 통합 준비 스크립트

준비 스크립트:

```bash
scripts/prepare_streamlit_runtime.sh
```

기본 동작:

- 이미 있는 산출물은 건너뛴다.
- 누락된 chunks/index/mapping만 생성한다.
- `data/extracted_v2_manual/`이 없고 `handoff/ocr_v2_manual_handoff_*.tar.gz`가 있으면 자동으로 푼다.
- 기본적으로 batch index/embedding 생성은 `CUDA_VISIBLE_DEVICES=0`을 사용한다.
- Streamlit/RAG query embedding은 런타임에서 CPU 기본값을 사용한다.
- 대형 LLM은 SGLang/vLLM wrapper가 GPU 0을 사용한다.

준비만 실행:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh
```

팀원 개인 워크스페이스에서 실행:

```bash
cd /srv/shared/workspaces/<user>/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh
```

## 준비 후 Streamlit 실행

공용 repo에서 기존 Streamlit을 교체하고 실행:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
```

개인 워크스페이스에서 8502 포트로 실행:

```bash
cd /srv/shared/workspaces/<user>/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace --port 8502
```

맥북에서 한 번에 실행:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace"
```

## 브라우저 접속

공용 8501 포트:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저:

```text
http://localhost:8501
```

개인 워크스페이스를 8502로 띄웠다면:

```bash
ssh -L 8502:localhost:8502 <user>@100.88.5.57
```

브라우저:

```text
http://localhost:8502
```

## 주요 옵션

```bash
bash scripts/prepare_streamlit_runtime.sh --run-streamlit
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --port 8502
bash scripts/prepare_streamlit_runtime.sh --skip-offline-assets
bash scripts/prepare_streamlit_runtime.sh --no-verify-load
bash scripts/prepare_streamlit_runtime.sh --cpu-index
bash scripts/prepare_streamlit_runtime.sh --force-chunks
bash scripts/prepare_streamlit_runtime.sh --force-indexes
bash scripts/prepare_streamlit_runtime.sh --force-mapping
bash scripts/prepare_streamlit_runtime.sh --skip-v2-handoff-import
```

## 실행 후 테스트할 기능

1. 일반 질의
   - 예: `로봇 수술의 코드를 알려주세요.`
   - 기대: 답변 본문이 먼저 나오고, 하단에 출처가 붙는다.
2. 퀵 코드 검색
3. 약관 정형 검색
4. 보험금 지급예상액 계산
5. OCR index mode
   - 기본 운영 인덱스
   - 보정본 OCR만
   - 원본+보정본 OCR 통합
6. vLLM `gemma-4-26b-a4b-nvfp4`
7. SGLang `gpt-oss-20b`
8. Ollama `exaone3.5:7.8b` fallback

## 로그

준비 로그:

```text
logs/prepare_streamlit_runtime_YYYYMMDD_HHMMSS.log
```

Streamlit 로그:

```text
logs/offline_streamlit_test_YYYYMMDD_HHMMSS.log
```

vLLM 로그:

```text
/srv/ai-ops/logs/vllm/gemma4.log
```

SGLang 로그:

```text
/srv/ai-ops/logs/sglang/sglang-local.log
```

## 주의사항

- `--force-indexes`는 기존 Chroma/BM25 인덱스를 재작성하므로 다른 팀원이 테스트 중일 때는 피한다.
- Gemma4/vLLM은 큰 메모리를 점유한다. 테스트가 끝나면 필요에 따라 `tmux kill-session -t vllm-gemma4`로 종료한다.
- Streamlit만 끄고 싶으면 `pkill -f '[s]treamlit run src/ui/streamlit_app.py'`를 사용한다.
- GitHub에 올라가지 않는 런타임 파일을 임의로 `git add -f`하지 않는다.
- secret/env 파일은 절대 출력하거나 커밋하지 않는다.
