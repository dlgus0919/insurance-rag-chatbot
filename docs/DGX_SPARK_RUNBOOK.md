# DGX Spark 운영 Runbook

작성일: 2026-05-15  
프로젝트: insurance-rag-chatbot  
DGX Host: aitopatom-255d  
Tailscale IP: 100.88.5.57

---

## 1. 현재 운영 상태 요약

DGX Spark에서 보험 문서 RAG 챗봇 운영 환경이 구성되어 있다.
현재 완료된 항목:

- Tailscale 기반 원격 접속
- 팀원별 Linux 계정 및 SSH key 접속
- VS Code Remote SSH 접속
- 공용 프로젝트 경로 구성
- Codex CLI 설치 및 sandbox 문제 해결
- 보험 RAG 프로젝트 이관
- 원본 PDF/XLSX 및 OCR 산출물 이관
- OCR 포함 ingest 성공
- Chroma / BM25 index 재생성 성공
- Streamlit 앱 실행 성공
- 관리자 계정 생성 및 로그인 성공
- Ollama 로컬 LLM 연결 성공
- exaone3.5:7.8b 로컬 답변 생성 성공
- 팀원 Mac에서 SSH 터널을 통한 앱 접속 성공
- 재부팅 후 복구 테스트 성공

정상 기준:

```text
chunks.jsonl line count: 7825
Chroma collection count: 7825
eval.py --ocr retrieval recall@8: 1.000
Ollama model: exaone3.5:7.8b
```

---

## 2. 주요 경로

프로젝트 경로:

```text
/srv/shared/projects/insurance-rag-chatbot
```

공용 프로젝트 루트:

```text
/srv/shared/projects
```

AI 운영 경로:

```text
/srv/ai-ops
```

비밀정보 경로:

```text
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
```

앱 실행 스크립트:

```text
/srv/ai-ops/bin/run-insurance-rag
```

운영 점검 스크립트:

```text
/srv/ai-ops/bin/check-insurance-rag
```

앱 상태/계정 파일:

```text
/srv/shared/projects/insurance-rag-chatbot/users.json
```

채팅 기록:

```text
/srv/shared/projects/insurance-rag-chatbot/data/chat_history/
```

백업 경로:

```text
/srv/ai-ops/backups/insurance-rag-chatbot
```

---

## 3. 앱 실행 방법

관리자 계정 ai-hang으로 DGX에 접속한다.

```bash
ssh ai-hang@100.88.5.57
```

앱 실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

이 스크립트는 다음 작업을 수행한다.

- 프로젝트 폴더로 이동
- Python 가상환경 활성화
- /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh 로드
- Streamlit 실행
- 로그 저장

Streamlit은 DGX 내부에서 다음 주소로 열린다.

```text
http://127.0.0.1:8501
```

---

## 4. tmux로 앱 유지 실행

일반 SSH 터미널에서 앱을 실행하면 터미널이 끊길 때 앱도 종료될 수 있다.
운영 시에는 tmux 사용을 권장한다.

새 tmux 세션 생성:

```bash
tmux new -s insurance-rag
```

tmux 안에서 앱 실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

tmux에서 빠져나오기:

```text
Ctrl + B
D
```

실행 중인 tmux 확인:

```bash
tmux ls
```

다시 접속:

```bash
tmux attach -t insurance-rag
```

앱 종료:

```text
tmux 세션 안에서 Ctrl + C
```

---

## 5. Mac에서 앱 접속 방법

앱은 DGX에서 실행하고, Mac에서는 SSH 터널로 접속한다.

Mac 로컬 터미널에서:

```bash
ssh -L 8501:localhost:8501 <계정명>@100.88.5.57
```

예:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

팀원 예:

```bash
ssh -L 8501:localhost:8501 muldae@100.88.5.57
```

그 후 Mac 브라우저에서 접속:

```text
http://localhost:8501
```

Mac의 8501 포트가 이미 사용 중이면 8502를 사용한다.

```bash
ssh -L 8502:localhost:8501 <계정명>@100.88.5.57
```

브라우저:

```text
http://localhost:8502
```

---

## 6. 재부팅 후 복구 체크리스트

DGX 재부팅 후 Mac에서 다시 접속한다.

```bash
ssh ai-hang@100.88.5.57
```

기본 상태 확인:

```bash
hostname
tailscale status
systemctl status ssh --no-pager
```

Ollama 확인:

```bash
systemctl is-active ollama
curl http://localhost:11434/api/tags
```

Chroma index 확인:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python - <<'PY'
import chromadb
client = chromadb.PersistentClient(path="data/index/chroma")
col = client.get_collection("insurance")
print("chroma count:", col.count())
PY
```

정상값:

```text
chroma count: 7825
```

앱 재실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

---

## 7. 운영 점검 스크립트

전체 상태 점검:

```bash
/srv/ai-ops/bin/check-insurance-rag
```

정상 기준:

```text
ssh active
ollama active
exaone3.5:7.8b model present
chroma count: 7825
streamlit process running
```

---

## 8. 평가 실행

Python 가상환경 및 환경변수 로드:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
set -a
source /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
set +a
```

retrieval-only OCR 평가:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 \
python scripts/eval.py --ocr
```

정상 기준:

```text
retrieval recall@8: 1.000
```

Ollama 포함 평가:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py --ocr
```

---

## 9. ingest 재생성 절차

주의: ingest는 data/processed/chunks.jsonl과 data/index/를 다시 생성한다.
실행 전 반드시 백업한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
mkdir -p data/processed_backup_before_ingest_$(date +%Y%m%d_%H%M%S)
rsync -avP data/processed/ data/processed_backup_before_ingest_$(date +%Y%m%d_%H%M%S)/
mkdir -p data/index_backup_before_ingest_$(date +%Y%m%d_%H%M%S)
rsync -avP data/index/ data/index_backup_before_ingest_$(date +%Y%m%d_%H%M%S)/
```

환경변수 로드:

```bash
source .venv/bin/activate
set -a
source /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
set +a
```

ingest 실행:

```bash
mkdir -p logs
RERANKER_ENABLED=false HF_MODEL_DOWNLOAD=true \
python scripts/ingest.py --include-ocr --stage all 2>&1 | tee logs/ingest_include_ocr_$(date +%Y%m%d_%H%M%S).log
```

정상 확인:

```bash
wc -l data/processed/chunks.jsonl
```

정상 기준:

```text
7825 data/processed/chunks.jsonl
```

Chroma 확인:

```bash
python - <<'PY'
import chromadb
client = chromadb.PersistentClient(path="data/index/chroma")
col = client.get_collection("insurance")
print(col.count())
PY
```

정상 기준:

```text
7825
```

---

## 10. Ollama 관리

서비스 상태:

```bash
systemctl is-active ollama
systemctl status ollama --no-pager
```

모델 목록:

```bash
curl http://localhost:11434/api/tags
```

현재 사용 모델:

```text
exaone3.5:7.8b
```

모델 수동 테스트:

```bash
ollama run exaone3.5:7.8b
```

종료:

```text
/bye
```

---

## 11. 비밀정보 관리

비밀정보는 Git에 넣지 않는다.

사용 경로:

```text
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
```

포함되는 주요 값:

```text
OPENAI_API_KEY
CLOVA_OCR_URL
CLOVA_OCR_SECRET
APP_PASSWORD
OLLAMA_HOST
OLLAMA_MODEL
```

내용 확인 시 값은 출력하지 않는다.

키 이름만 확인:

```bash
grep -nE 'OPENAI|CLOVA|APP_PASSWORD|OLLAMA|EMBEDDING|RERANKER' \
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh | sed 's/=.*/=<hidden>/'
```

---

## 12. Git에 올리면 안 되는 파일

다음은 Git 금지:

```text
.env
.env.*
users.json
users.json.tmp
logs/
data/chat_history/
raw/
*.pdf
*.xlsx
*.xls
data/extracted/
data/extracted_v2_manual/
data/index/chroma/
data/index/relational/*.sqlite
data/processed_backup*/
data/index_backup*/
.venv/
__pycache__/
.pytest_cache/
CLOVA_OCR_CUSTOM_API_EXTERNAL*.json
```

현재 .gitignore에 DGX runtime artifact 차단 규칙이 추가되어 있다.

이미 Git이 추적 중인 생성물은 별도 정책 결정이 필요하다.

현재 보류 대상:

```text
data/processed/chunks.jsonl
data/index/bm25.pkl
eval/smoke_qa_v2.jsonl
```

---

## 13. 백업

앱 상태 백업 예시:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
BACKUP_DIR="/srv/ai-ops/backups/insurance-rag-chatbot/app_state_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -av users.json "$BACKUP_DIR/" 2>/dev/null || true
rsync -avP data/chat_history/ "$BACKUP_DIR/chat_history/" 2>/dev/null || true
rsync -avP logs/ "$BACKUP_DIR/logs/" 2>/dev/null || true
chmod -R go-rwx "$BACKUP_DIR"
ls -lah "$BACKUP_DIR"
```

성공한 index 백업 예시:

```bash
mkdir -p data/processed_backup_success_manual
rsync -avP data/processed/ data/processed_backup_success_manual/
mkdir -p data/index_backup_success_manual
rsync -avP data/index/ data/index_backup_success_manual/
```

---

## 14. 장애 대응

앱이 안 뜨는 경우

```bash
pgrep -af "streamlit run"
tmux ls
```

필요 시 재실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

Mac에서 localhost:8501 접속이 안 되는 경우

Mac에서 SSH 터널이 열려 있는지 확인:

```bash
ssh -L 8501:localhost:8501 <계정명>@100.88.5.57
```

8501 충돌 시:

```bash
ssh -L 8502:localhost:8501 <계정명>@100.88.5.57
```

Ollama 답변이 안 되는 경우

```bash
systemctl is-active ollama
curl http://localhost:11434/api/tags
ollama run exaone3.5:7.8b
```

검색 결과가 이상한 경우

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python - <<'PY'
import chromadb
client = chromadb.PersistentClient(path="data/index/chroma")
col = client.get_collection("insurance")
print(col.count())
PY
```

정상값은 7825이다.

eval이 실패하는 경우

먼저 모델 캐시와 index를 확인한다.

```bash
du -sh ~/.cache/huggingface
wc -l data/processed/chunks.jsonl
```

정상값:

```text
chunks.jsonl: 7825 lines
```

---

## 15. 운영 원칙

- 앱은 DGX에서 실행한다.
- 팀원은 SSH 터널로 접속한다.
- 비밀정보는 /srv/ai-ops/secrets에만 둔다.
- 원본 PDF/XLSX는 Git에 올리지 않는다.
- users.json은 Git에 올리지 않는다.
- ingest 전에는 반드시 processed/index를 백업한다.
- 재부팅 후에는 Ollama, Chroma count, Streamlit 실행 상태를 확인한다.

## SGLang local provider 운영 (gpt-oss-20b)

기준일: 2026-05-20

### 목적

DGX Spark에서 `gpt-oss-20b`를 SGLang OpenAI-compatible provider로 제공한다. 기존 Ollama `exaone3.5:7.8b`는 fallback으로 유지한다.

### 운영 파일

Git에 포함하지 않는 DGX 운영 산출물:

- `/srv/ai-ops/llm/models/gpt-oss-20b/`
- `/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja`
- `/srv/ai-ops/bin/run-sglang-local`
- `/srv/ai-ops/bin/check-sglang-local`
- `/srv/ai-ops/logs/sglang/sglang-local.log`

`gpt-oss-20b`는 Harmony chat template이 없으면 `/v1/chat/completions`가 400으로 실패한다. 반드시 wrapper의 `--chat-template /srv/ai-ops/llm/templates/gpt_oss_harmony.jinja`를 유지한다.

### 기동

```bash
tmux new-session -d -s sglang-local /srv/ai-ops/bin/run-sglang-local
```

재기동:

```bash
tmux kill-session -t sglang-local
pkill -f 'sglang serve.*gpt-oss-20b' || true
tmux new-session -d -s sglang-local /srv/ai-ops/bin/run-sglang-local
```

상태 확인:

```bash
/srv/ai-ops/bin/check-sglang-local
```

### 앱 env

```env
OFFLINE_MODE=true
HF_MODEL_DOWNLOAD=false
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3
SGLANG_BASE_URL=http://127.0.0.1:30000/v1
SGLANG_API_KEY=EMPTY
SGLANG_DEFAULT_MODEL=gpt-oss-20b
SGLANG_REASONING_EFFORT=low
SGLANG_CANDIDATE_MODELS=gpt-oss-20b
ALLOW_OLLAMA=true
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=exaone3.5:7.8b
```

### 회귀 검증

SGLang이 GPU 메모리를 점유한 상태에서는 retrieval-only eval을 CPU 임베딩으로 실행한다.

```bash
CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 .venv/bin/python scripts/eval.py --ocr
```

정상 기준:

- `pytest -q`: 전체 통과
- `retrieval recall@8: 1.000`
- `data/processed/chunks.jsonl`: `7825` lines
- Chroma collection count: `7825`

### 롤백

앱에서 provider를 `Ollama`로 선택하거나 env를 다음처럼 되돌린다.

```env
LOCAL_LLM_PROVIDER=ollama
ALLOW_OLLAMA=true
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=exaone3.5:7.8b
```
