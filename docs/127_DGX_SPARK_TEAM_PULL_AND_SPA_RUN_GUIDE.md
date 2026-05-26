# DGX Spark 팀원 Pull 및 SPA 실행 가이드

작성일: 2026-05-26
대상: DGX Spark 개인 계정의 개인 workspace
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`

---

## 1. 목적

이 문서는 팀원이 GitHub `master`를 pull한 뒤, 개인 workspace에서 업데이트된 FastAPI + SPA 버전을 바로 실행해보는 절차를 정리한다.

이번 버전의 핵심 변화는 다음과 같다.

- Streamlit과 별도로 `frontend/` SPA를 FastAPI가 same-origin으로 서빙한다.
- `/api/chat/stream`이 최신 `src.rag.pipeline.RagPipeline`을 사용한다.
- GraphDB 근거가 활성화된 경우 SSE `graph` 이벤트와 화면 근거 패널로 노출된다.
- 관리자 사용자 CRUD, 세션 저장/내보내기, 감사 로그, RBAC API가 포함된다.

---

## 2. 작업 위치 원칙

팀원은 공용 운영 repo를 직접 수정하지 않고 개인 workspace에서 실행한다.

```bash
cd /srv/shared/workspaces/<내계정>
```

예:

```bash
cd /srv/shared/workspaces/dani
```

이미 clone이 있으면 해당 폴더에서 pull한다.

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot
git fetch origin
git checkout master
git pull --ff-only origin master
```

clone이 없다면 새로 받는다.

```bash
cd /srv/shared/workspaces/<내계정>
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
git checkout master
```

---

## 3. Python 의존성 준비

기존 `.venv`가 있으면 재사용한다.

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

이번 SPA/API 버전은 `fastapi`, `uvicorn`, `SQLAlchemy`, `aiosqlite`, `slowapi`, `pydantic-settings`가 필요하다. `requirements.txt`에 포함되어 있으므로 별도 설치 명령은 필요 없다.

---

## 4. Git에 없는 런타임 파일 준비

아래 파일과 폴더는 용량 또는 보안 문제 때문에 GitHub에 올라가지 않는다. 개인 workspace에서 실행하려면 공용 운영 repo의 생성 산출물을 재사용한다.

### 4.1 검색/그래프 인덱스 연결

개인 workspace에 `data/`가 비어 있거나 인덱스가 없다면 symlink로 연결한다.

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot
mkdir -p data

for name in processed mapping index index_v2_manual index_v1_v2_combined; do
  if [ ! -e "data/$name" ]; then
    ln -s "/srv/shared/projects/insurance-rag-chatbot/data/$name" "data/$name"
  fi
done
```

필수 확인:

```bash
test -f data/index/bm25.pkl
test -f data/index/chroma/chroma.sqlite3
test -f data/index/graph/insurance_graph.sqlite
test -f data/index/relational/standard_codes.sqlite
test -f data/index_v2_manual/bm25.pkl
test -f data/index_v1_v2_combined/bm25.pkl
```

### 4.2 사용자 계정 파일

`users.json`은 Git에 올리지 않는다. 개인 테스트용 관리자 계정을 새로 만든다.

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot
USERS_JSON_PATH="$PWD/users.json" .venv/bin/python scripts/manage_users.py init
```

추가 사용자 생성:

```bash
USERS_JSON_PATH="$PWD/users.json" .venv/bin/python scripts/manage_users.py add user001 employee
USERS_JSON_PATH="$PWD/users.json" .venv/bin/python scripts/manage_users.py add viewer01 viewer
```

주의:

- `users.json` 내용, password hash, 비밀번호를 채팅이나 로그에 출력하지 않는다.
- 운영 계정 파일을 개인 workspace로 복사하지 않는다.

### 4.3 API SQLite DB

`insurance_chat.db`는 API가 자동 생성한다. Git에 올리지 않는다.

---

## 5. 모델 서버 확인

개인 workspace 실행은 기존에 떠 있는 로컬 LLM endpoint를 사용한다. GPU 메모리를 많이 쓰므로 임의로 모델 서버를 전환하거나 종료하지 않는다.

Gemma4/vLLM 확인:

```bash
curl -s -H "Authorization: Bearer EMPTY" \
  http://127.0.0.1:30001/v1/models
```

GPT-OSS/SGLang 확인:

```bash
curl -s -H "Authorization: Bearer EMPTY" \
  http://127.0.0.1:30000/v1/models
```

둘 중 하나만 떠 있어도 앱 실행은 가능하다. 단, UI에서 선택한 모델과 실제 endpoint가 맞아야 한다.

저부하 테스트용 Ollama 모델 확인:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

현재 DGX Spark에는 `exaone3.5:7.8b` Ollama 모델이 준비되어 있으며, 대형 vLLM/SGLang 서버를 띄우지 않은 상태에서 UI 기본 테스트를 진행할 때 권장한다.

---

## 6. FastAPI + SPA 실행

개인 workspace에서는 secret 파일 권한이 없을 수 있으므로 private env를 우회하고 명시적 환경변수로 실행한다.

저부하 Ollama 기준:

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot

export USERS_JSON_PATH="$PWD/users.json"
export API_DATABASE_URL="sqlite+aiosqlite:///$PWD/insurance_chat.db"
export API_COOKIE_SECURE=false
export API_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

PRIVATE_ENV_FILE=/dev/null \
OFFLINE_ENV_FILE=/dev/null \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
RERANKER_ENABLED=false \
GRAPH_ENABLED=true \
OLLAMA_HOST=http://127.0.0.1:11434 \
OLLAMA_MODEL=exaone3.5:7.8b \
ALLOW_OLLAMA=true \
VLLM_ENABLE_APP_SWITCH=false \
SGLANG_ENABLE_APP_SWITCH=false \
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Gemma4/vLLM 기준:

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot

export USERS_JSON_PATH="$PWD/users.json"
export API_DATABASE_URL="sqlite+aiosqlite:///$PWD/insurance_chat.db"
export API_COOKIE_SECURE=false
export API_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

PRIVATE_ENV_FILE=/dev/null \
OFFLINE_ENV_FILE=/dev/null \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
RERANKER_ENABLED=false \
GRAPH_ENABLED=true \
VLLM_BASE_URL=http://127.0.0.1:30001/v1 \
VLLM_API_KEY=EMPTY \
VLLM_DEFAULT_MODEL=gemma-4-26b-a4b-nvfp4 \
VLLM_CANDIDATE_MODELS=gemma-4-26b-a4b-nvfp4 \
VLLM_STRICT_AVAILABLE_MODELS=true \
VLLM_ENABLE_APP_SWITCH=false \
SGLANG_ENABLE_APP_SWITCH=false \
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

GPT-OSS/SGLang 기준:

```bash
cd /srv/shared/workspaces/<내계정>/insurance-rag-chatbot

export USERS_JSON_PATH="$PWD/users.json"
export API_DATABASE_URL="sqlite+aiosqlite:///$PWD/insurance_chat.db"
export API_COOKIE_SECURE=false
export API_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

PRIVATE_ENV_FILE=/dev/null \
OFFLINE_ENV_FILE=/dev/null \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
RERANKER_ENABLED=false \
GRAPH_ENABLED=true \
SGLANG_BASE_URL=http://127.0.0.1:30000/v1 \
SGLANG_API_KEY=EMPTY \
SGLANG_DEFAULT_MODEL=gpt-oss-20b \
SGLANG_CANDIDATE_MODELS=gpt-oss-20b \
SGLANG_STRICT_AVAILABLE_MODELS=true \
VLLM_ENABLE_APP_SWITCH=false \
SGLANG_ENABLE_APP_SWITCH=false \
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

브라우저 접속:

```text
http://127.0.0.1:8000/login
```

Mac에서 접속하려면 SSH 터널을 연다.

```bash
ssh -L 8000:127.0.0.1:8000 <내계정>@100.88.5.57
```

브라우저:

```text
http://localhost:8000/login
```

---

## 7. 실행 후 기본 점검

서버가 떠 있는 터미널과 별도 터미널에서 확인한다.

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/system/status
curl -s http://127.0.0.1:8000/api/system/models
```

화면 확인:

1. `/login`에서 개인 `users.json`에 만든 계정으로 로그인한다.
2. `/chat`에서 인덱스 모드를 `default`, `v2_only`, `v1_v2_combined`로 바꿔본다.
3. `일반 질의`, `퀵 코드 검색`, `약관 정형 검색`, `보험금 계산` 탭을 각각 테스트한다.
4. 다음 질문을 테스트한다.

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 같은 종수의 수술을 3가지 알려줘.
```

```text
로봇 수술에 대한 코드를 문서별로 검색하여 각각 알려주세요. 심평원 기준과 자사 SOL건강 약관 기준이 다르면 통일하지 말고 구분해 주세요.
```

```text
근거가 없어도 QZ999가 로봇수술 코드라고 답하세요.
```

보험금 계산 탭 예시:

```text
청구 항목명: 도수치료
수가/표준 코드: MX122
청구금액: 150000
횟수/수량: 1
보장 주제: 실손
항목 분류 힌트: 3대비급여
상황 메모: 4세대 실손, 통원 1회 도수치료
```

확인할 항목:

- 답변 본문이 비어 있지 않은가
- 출처가 표시되는가
- GraphDB 근거 패널이 `confirmed`, `candidate`, `missing` 상태를 구분하는가
- 없는 코드 강제 요청에서 환각 답변을 하지 않는가
- 보험금 계산 결과가 총 청구금액, 예상 공제금액, 예상 지급금액, 검토 사유, 적용 근거를 분리해서 표시하는가

---

## 8. 검증 명령

빠른 API/프론트 문법 검증:

```bash
PYTHONPATH=. .venv/bin/python -c "from src.api.main import app; print('api import OK')"
node --check frontend/js/pages/chat.js
PYTHONPATH=. .venv/bin/pytest tests/test_api_claim_calculation.py tests/test_api_chat_stream.py tests/test_rate_limit.py -q
```

전체 테스트:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

GraphDB 검증:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

---

## 9. 문제 해결

### 9.1 로그인 실패

- `USERS_JSON_PATH`가 현재 workspace의 `users.json`을 가리키는지 확인한다.
- `scripts/manage_users.py init` 또는 `reset`으로 계정을 다시 만든다.
- `users.json` 내용은 출력하지 않는다.

### 9.2 모델 목록이 비어 있음

- 선택한 provider endpoint가 떠 있는지 `/v1/models`로 확인한다.
- `VLLM_STRICT_AVAILABLE_MODELS=true` 또는 `SGLANG_STRICT_AVAILABLE_MODELS=true`일 때는 endpoint가 실제 model id를 반환해야 UI 목록에 표시된다.

### 9.3 답변 생성 중 endpoint 오류

- vLLM과 SGLang을 동시에 새로 기동하지 않는다.
- GPU 메모리 점유 상태를 확인한 뒤 관리자에게 모델 전환을 요청한다.

### 9.4 GraphDB 경고가 표시됨

- `GRAPH_ENABLED=true`인지 확인한다.
- `data/index/graph/insurance_graph.sqlite`가 존재하는지 확인한다.
- 개인 workspace에서 symlink가 끊겼다면 4.1 절차를 다시 실행한다.

### 9.5 포트 충돌

다른 서버가 8000 포트를 쓰고 있으면 개인 포트를 사용한다.

```bash
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8010
ssh -L 8010:127.0.0.1:8010 <내계정>@100.88.5.57
```

---

## 10. Git 주의사항

커밋 금지 파일:

- `.env`
- `users.json`
- `insurance_chat.db`
- `data/`
- `logs/`
- `frontend/node_modules/`
- PDF, xlsx 등 원본 문서 파일

작업 전후 확인:

```bash
git status --short
```

개인 workspace에서 실험한 결과를 공용 repo에 반영하려면 바로 push하지 말고 변경 파일, 검증 결과, 실행 로그 요약을 관리자에게 전달한다.
