# 보험 문서 RAG 챗봇 (Alpha)

1,429페이지 건강보험 고시 PDF를 로컬에서 검색하고 답변하는 RAG 챗봇입니다.  
PDF 파싱, 계층형 청킹, BGE-M3 임베딩, ChromaDB, BM25, RRF 융합, Ollama LLM 호출로 구성됩니다.  
현재 버전은 사용자 계정 로그인, 관리자 로그 대시보드, Ollama 로컬 모델, OpenAI API 모델 선택을 지원합니다.

## 사전 요구사항

- Python 3.11 권장
- macOS Apple Silicon 또는 Linux
- Ollama 설치 및 실행
- 기본 모델: `ollama pull qwen2.5:3b-instruct`
- Ollama 데스크톱 앱 실행 또는 `ollama serve`
- BGE-M3 모델 사전 다운로드
- OpenAI 모델을 사용할 경우 OpenAI API 키

외부 네트워크가 필요한 모델 다운로드는 실행 코드에서 수행하지 않는 것을 전제로 합니다. BGE-M3가 HuggingFace 캐시에 없는 경우 인덱싱 단계에서 중단됩니다.

```bash
python - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("BAAI/bge-m3")
PY
```

다른 Ollama 모델을 쓰려면 `.env`에서 `OLLAMA_MODEL` 값을 바꿉니다. OpenAI 모델을 쓰려면 `.env`에 `OPENAI_API_KEY`를 추가합니다.

## 셋업

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

입력 PDF `BZ202603053039374.pdf`는 프로젝트 루트에 있어야 합니다.

최초 실행 전 관리자 계정을 만듭니다.

```bash
python scripts/manage_users.py init
```

직원 계정은 CLI 또는 관리자 페이지에서 추가합니다.

```bash
python scripts/manage_users.py add employee01 employee
python scripts/manage_users.py list
```

기존 `APP_PASSWORD` 단일 비밀번호 방식은 M15부터 사용하지 않습니다.

## 인덱싱

```bash
python scripts/ingest.py --stage all
```

단계별 실행도 가능합니다.

```bash
python scripts/ingest.py --stage chunks
python scripts/ingest.py --stage index
```

M4 Mac CPU 기준 BGE-M3 임베딩은 30분에서 수 시간까지 걸릴 수 있습니다. 한 번 생성된 `data/index/`는 재사용합니다.

## 실행

CLI:

```bash
python scripts/cli.py
```

Streamlit:

```bash
streamlit run src/ui/streamlit_app.py
```

OpenAI 모델 사용 예시:

```bash
OPENAI_API_KEY=sk-...
OPENAI_DEFAULT_MODEL=gpt-5-mini
OPENAI_MAX_TOKENS=1500
```

OpenAI 모델을 선택하면 질문과 검색된 문서 청크가 OpenAI API로 전송됩니다.

## 클라우드 배포

Streamlit Community Cloud 또는 Hugging Face Spaces 배포 절차는 `docs/17_DEPLOY_GUIDE.md`를 참고하세요.

클라우드 배포에서는 보통 다음 환경변수를 사용합니다.

```bash
ALLOW_OLLAMA=false
CLOUD_DEPLOY=true
INDEX_RELEASE_URL=https://github.com/.../releases/download/.../assets.zip
```

클라우드용 인덱스는 공개 가능한 문서만 포함해 생성합니다.

```bash
python scripts/ingest.py --cloud-only --stage all
```

## 평가

```bash
python scripts/eval.py
```

평가 문항은 `eval/smoke_qa.jsonl`에 있으며, 코드 조회 5개와 의미 검색 5개로 구성됩니다. 기준은 retrieval recall@8 0.7 이상, 출처 페이지 정확도 0.6 이상입니다.

## 트러블슈팅

Ollama 미연결: Ollama 데스크톱 앱을 켜거나 `ollama serve`를 실행하세요.

모델 미존재 또는 태그명 오타: `ollama list`로 설치 모델명을 확인하고 `.env`의 `OLLAMA_MODEL` 값을 맞추세요.

BGE-M3 다운로드 실패: 네트워크가 가능한 환경에서 `SentenceTransformer("BAAI/bge-m3")`를 먼저 실행해 HuggingFace 캐시에 저장하세요.

kiwipiepy 설치 실패: BM25 토크나이저는 정규식 기반 토큰화로 폴백합니다. 다만 한국어 검색 품질은 낮아질 수 있습니다.

Chroma 또는 BM25 인덱스 없음: `python scripts/ingest.py --stage index`를 다시 실행하세요.

관리자 계정 없음: `python scripts/manage_users.py init`을 실행해 첫 관리자를 생성하세요.

OpenAI 모델이 보이지 않음: `.env` 또는 클라우드 secrets에 `OPENAI_API_KEY`가 설정되어 있는지 확인하세요.

## 알파 범위 외 / 베타 이월

- OCR
- bge-reranker-v2 리랭킹
- 멀티턴 질의 재작성
- 코드 정확매칭 우선 라우팅
- 인덱스 버전 관리와 증분 업데이트
- 세션 영속화와 사용자별 히스토리
- LLM 7B/8B 업그레이드 평가
- SSO/OAuth/OIDC
- 클라우드 로그 영속 저장소 연동
- Top-K·온도 자동 설정
