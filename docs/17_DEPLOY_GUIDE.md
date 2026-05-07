# 클라우드 배포 가이드 (Streamlit Community Cloud)

## 1. GitHub 저장소 준비

1. `.gitignore`를 확인합니다.
   - `.env`, `users.json`, `logs/`, `data/`, `*.pdf`는 새로 추가되는 파일 기준으로 커밋하지 않습니다.
   - 현재 저장소에 이미 추적 중인 공개 PDF와 일부 인덱스 파일은 유지합니다.
2. PDF 공개 가능 여부를 확인합니다.
   - `cloud_safe=True`: 심평원 고시 PDF, 공개 약관 PDF
   - `cloud_safe=False`: 보상가이드북 등 사내 자료 가능성이 있는 파일
3. 사내 자료는 공개 저장소나 GitHub Release asset에 올리지 않습니다.

## 2. 인덱스 자산 패키징

로컬에서 클라우드 안전 문서만 인덱싱합니다.

```bash
python scripts/ingest.py --cloud-only --stage all
```

생성된 인덱스와 클라우드에서 사용할 공개 PDF만 zip으로 묶습니다.

```bash
zip -r assets.zip data/index/ BZ202603053039374.pdf "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf"
```

GitHub Release를 만들고 `assets.zip`을 업로드한 뒤 다운로드 URL을 복사합니다.

## 3. Streamlit Community Cloud 설정

1. [https://streamlit.io/cloud](https://streamlit.io/cloud)에 GitHub로 로그인합니다.
2. New app을 선택합니다.
3. Repository, branch, main file을 설정합니다.
   - Main file: `src/ui/streamlit_app.py`
4. Advanced settings에서 Python 3.11을 선택합니다.
5. Secrets에 다음 값을 입력합니다.

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_DEFAULT_MODEL = "gpt-5.2-chat-latest"
OPENAI_MAX_TOKENS = "1500"
OPENAI_CANDIDATE_MODELS = "gpt-5.5,gpt-5.2-chat-latest,gpt-5.4-mini,gpt-5-mini"
ALLOW_OLLAMA = "false"
CLOUD_DEPLOY = "true"
EMBEDDING_MODEL = "BAAI/bge-m3"
HF_MODEL_DOWNLOAD = "true"
INDEX_RELEASE_URL = "https://github.com/koreaben777/insurance-rag-chatbot/releases/download/rag-assets-v1/assets.zip"

USERS_JSON_PATH = "/tmp/users_cloud_v1.json"

USERS_JSON = '{"version":1,"users":[{"username":"admin","password_hash":"$pbkdf2-sha256$...","role":"admin","display_name":"관리자","created_at":"2026-05-06T00:00:00+00:00","password_updated_at":"2026-05-06T00:00:00+00:00"}]}'
```

`USERS_JSON`의 `password_hash`는 로컬에서 `python scripts/manage_users.py init`으로 생성한 `users.json` 내용을 사용합니다. 평문 비밀번호를 secrets에 넣지 않습니다.

`gpt-5.5`, `gpt-5.4-mini`, `gpt-5.2-chat-latest`, `gpt-5-mini`는 Chat Completions와 streaming을 지원하는 모델로 웹앱의 기존 OpenAI 스트리밍 클라이언트에서 사용할 수 있습니다. `gpt-5.2-pro`, `gpt-5.5-pro`처럼 현재 스트리밍 웹앱 경로와 맞지 않는 pro 계열 모델은 후보 목록에 넣지 않습니다.

`HF_MODEL_DOWNLOAD=true`는 Streamlit Cloud 웹 게시 테스트에서 BGE-M3를 HuggingFace에서 내려받도록 허용합니다. 로컬 실행과 인제스트는 기본값 `false`를 유지해 기존 캐시 기반 파이프라인을 보존합니다. BGE-M3는 큰 모델이므로 다운로드 또는 로드가 실패하면 BM25-only로 폴백하지 않고 명시 오류를 확인합니다.

## 4. 배포 후 점검

- 첫 부팅 로그에 인덱스 다운로드 성공 메시지가 보입니다.
- 로그인 화면이 표시됩니다.
- OpenAI 모델만 선택지에 표시됩니다.
- 일반 질의 모드에서 답변과 출처가 표시됩니다.
- 관리자 페이지에 진입할 수 있습니다.
- 관리자 통계 탭에서 OpenAI 누적 토큰이 표시됩니다.

## 5. Hugging Face Spaces 대안

Streamlit Community Cloud의 메모리 한도 때문에 인덱스 로딩이 실패하면 Hugging Face Spaces의 Streamlit SDK를 사용합니다.

1. 새 Space를 만들고 SDK를 Streamlit으로 선택합니다.
2. 저장소 파일을 업로드하거나 GitHub와 동기화합니다.
3. Settings의 Variables and secrets에 Streamlit Cloud와 같은 값을 설정합니다.
4. `ALLOW_OLLAMA=false`, `CLOUD_DEPLOY=true`를 유지합니다.

HF Spaces도 공개 설정일 수 있으므로 사내 자료와 비밀값을 파일로 업로드하지 않습니다.

## 6. 운영 주의사항

- 클라우드 로그는 플랫폼 재시작 시 사라질 수 있습니다. 알파에서는 관리자 페이지에서 CSV를 주기적으로 내려받습니다.
- OpenAI 모델은 외부 서버를 호출합니다. 질문과 검색 청크가 OpenAI로 전송됩니다.
- 사내 가이드북이 필요한 경우 공개 가능 여부를 먼저 확인하고, 불가능하면 로컬 실행 환경에서만 사용합니다.
