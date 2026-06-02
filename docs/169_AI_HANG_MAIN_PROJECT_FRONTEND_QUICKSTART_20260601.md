# 169. AI-Hang 메인 프로젝트 프론트엔드 실행 퀵스타트

작성일: 2026-06-01  
대상 프로젝트: `insurance-rag-chatbot`  
기준 위치: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 현재 확인된 서버 상태

2026-06-01 15:22 KST 기준 확인 결과:

- `SGLang`: 실행 중
  - endpoint: `http://127.0.0.1:30000/v1`
  - served model: `gpt-oss-20b`
- `Ollama`: 실행 중
  - endpoint: `http://127.0.0.1:11434`
  - installed model 확인: `exaone3.5:7.8b`
- `vLLM`: 현재 미가동
  - `127.0.0.1:30001` 리슨 없음
- 메인 프로젝트 FastAPI 앱:
  - `127.0.0.1:18080` 미가동

즉, 지금 바로 쓸 수 있는 로컬 LLM은 **SGLang GPT-OSS**와 **Ollama exaone3.5:7.8b**이고, 메인 앱 서버만 올리면 된다.

## 2. 권장 사용 형태

현재 메인 브랜치 프론트엔드는 FastAPI가 정적 파일까지 함께 서빙하는 구조다.

따라서 실행 단위는:

1. DGX에서 메인 프로젝트 폴더로 이동
2. 사용자/DB/JWT 환경변수 설정
3. FastAPI 서버를 `127.0.0.1:18080`에 실행
4. Mac에서 SSH 터널 연결
5. 브라우저에서 `http://localhost:18080/login` 접속

## 3. 사전 확인

DGX 접속 후:

```bash
cd /srv/shared/projects/insurance-rag-chatbot

ss -ltnp | egrep ':(18080|30000|30001|11434)\b' || true
```

정상 기대:

- `30000` 열려 있음: SGLang
- `11434` 열려 있음: Ollama
- `18080` 비어 있음: 메인 앱 서버를 여기서 실행

## 4. 계정 파일 준비

현재 프로젝트의 사용자 파일은 `users.json`이다.

이미 있으면 그대로 사용하고, 없으면 초기 관리자 생성:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
USERS_JSON_PATH="$PWD/users.json" .venv/bin/python scripts/manage_users.py init
```

일반 사용자 추가 예시:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
USERS_JSON_PATH="$PWD/users.json" .venv/bin/python scripts/manage_users.py add user001 employee
```

주의:

- 비밀번호는 터미널에 노출되지 않도록 직접 입력한다.
- 기존 `users.json`이 있으면 함부로 덮어쓰지 않는다.

## 5. 메인 앱 서버 실행

DGX에서 아래처럼 실행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot

export USERS_JSON_PATH="$PWD/users.json"
export API_DATABASE_URL="sqlite+aiosqlite:///$PWD/insurance_chat.db"
export API_COOKIE_SECURE=false
export API_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
RERANKER_ENABLED=false \
ALLOW_OLLAMA=true \
OLLAMA_HOST=http://127.0.0.1:11434 \
OLLAMA_MODEL=exaone3.5:7.8b \
SGLANG_BASE_URL=http://127.0.0.1:30000/v1 \
SGLANG_API_KEY=EMPTY \
SGLANG_DEFAULT_MODEL=gpt-oss-20b \
SGLANG_STRICT_AVAILABLE_MODELS=true \
SGLANG_ENABLE_APP_SWITCH=false \
VLLM_BASE_URL=http://127.0.0.1:30001/v1 \
VLLM_API_KEY=EMPTY \
VLLM_STRICT_AVAILABLE_MODELS=true \
VLLM_ENABLE_APP_SWITCH=false \
.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 18080
```

정상 로그 예시:

```text
INFO:     Started server process [...]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:18080
```

## 6. Mac에서 접속

Mac 터미널에서:

```bash
ssh -L 18080:127.0.0.1:18080 ai-hang@100.88.5.57
```

그 다음 브라우저에서:

```text
http://localhost:18080/login
```

## 7. 로그인 후 모델 선택에서 보일 항목

현재 상태 기준으로 로그인 화면에서 정상적으로 노출되어야 하는 로컬 모델은 다음이다.

- `Local · SGLang · GPT-OSS · 20B`
- `Local · Ollama · exaone3.5:7.8b`

현재 **vLLM 서버가 꺼져 있으므로**, vLLM 계열 모델은 선택지에 없거나 비활성 상태가 정상이다.

## 8. 빠른 동작 확인

앱 서버가 뜬 뒤 DGX에서:

```bash
curl -fsS http://127.0.0.1:30000/v1/models
curl -fsS http://127.0.0.1:11434/api/tags
curl -I http://127.0.0.1:18080/login
```

기대 결과:

- 첫 번째: `gpt-oss-20b` 확인
- 두 번째: `exaone3.5:7.8b` 확인
- 세 번째: `HTTP/1.1 200 OK` 또는 `304` 계열 응답

## 9. 자주 발생하는 문제

### 9.1 로그인 화면은 뜨는데 모델 선택이 이상함

확인:

```bash
curl -fsS http://127.0.0.1:30000/v1/models
curl -fsS http://127.0.0.1:11434/api/tags
```

원인:

- 실제 LLM endpoint 응답이 없으면 프론트엔드 모델 목록이 줄어든다.

### 9.2 `localhost:18080` 접속이 안 됨

확인:

```bash
ss -ltnp | grep 18080
```

원인:

- 앱 서버 미실행
- SSH 터널 미연결

### 9.3 `gpt-oss-20b`가 보이지 않음

확인:

```bash
curl -fsS http://127.0.0.1:30000/v1/models
```

원인:

- SGLang 서버가 내려갔거나 다른 모델로 교체됨
- `SGLANG_STRICT_AVAILABLE_MODELS=true` 상태에서 endpoint가 응답하지 않음

### 9.4 관리자 페이지는 열리지만 일부 진단 값이 비어 있음

가능 원인:

- 아직 `CHAT_QUERY` / `CHAT_QUERY_FAILED` audit log가 충분히 쌓이지 않음
- 현재 세션에서 일반 질의를 실행하지 않음

## 10. 요약

현재 메인 프로젝트를 가장 간단하게 써보는 경로는 다음이다.

1. DGX에서 메인 프로젝트 앱을 `18080`으로 실행
2. 이미 떠 있는 `30000(SGLang)` / `11434(Ollama)`를 그대로 사용
3. Mac에서 `ssh -L 18080:127.0.0.1:18080 ai-hang@100.88.5.57`
4. 브라우저에서 `http://localhost:18080/login` 접속

현재 기준으로 **즉시 사용 가능한 로컬 LLM은 GPT-OSS(SGLang)와 exaone(Ollama)** 이다.
