# 보험 문서 RAG 챗봇 (Beta)

자사 약관·심평원 고시·실무가이드 등 보험 문서 7종을 검색하고 답변하는 RAG 챗봇입니다.  
CLOVA OCR 파이프라인, BGE-M3 임베딩, ChromaDB, BM25, RRF 융합, Parquet 테이블 인덱스, Ollama/OpenAI LLM 호출로 구성됩니다.  
현재 버전은 사용자 계정 로그인, 관리자 로그 대시보드, 사이드바 문서 필터, Ollama 로컬 모델, OpenAI API 모델 선택을 지원합니다.

현재 단계: 베타 Stage 2 — D3·D4 자사 약관 인덱싱 **완료** / 사이드바 필터 보강 진행 중 (`feature/eundeo/apply-smoke-test`).

원본 PDF/XLSX, OCR 추출본, 백업 자료는 GitHub에 절대 푸시하지 않습니다.

## 현재 인덱스 현황

| 문서 (doc_short) | 청크 수 | 비고 |
|---|---|---|
| 심평원 | 2,286 | 건강보험 요양급여 고시 |
| 자사_SOL건강 | 1,494 | SOL건강보험 약관 (D3) |
| 상담사례집 | 1,117 | 보험 분쟁 상담 사례 (OCR) |
| 실무가이드 | 927 | 수술·장해 실무가이드 (OCR) |
| 표준약관 | 856 | 표준 보험 약관 |
| 자사_SOL운전자 | 761 | SOL운전자보험 약관 (D4) |
| 약관 | 384 | 신한 이지로운 실손 약관 |
| **합계** | **7,825** | ChromaDB + BM25 인덱스 |

Parquet 테이블 인덱스: `data/index/surgery_grades.parquet` (2,408행), `data/index/disability_rates.parquet` (100행).

## 운영 환경

DGX Spark (`aitopatom-255d`, Tailscale `100.88.5.57`) 에서 팀 공용 서버로 운영합니다.  
Streamlit은 `127.0.0.1:8501`에서 실행 중이며 SSH 터널로 팀원이 접속합니다.  
Discord `#dgx-ops` 채널에서 `/status`, `/codex`, `/claude` 등 13개 명령으로 서버를 조작합니다.  
운영 상세 절차는 `docs/DGX_SPARK_ENV_SETUP_20260518.md` 및 `docs/DISCORD_HARNESS_RUNBOOK.md`를 참고하세요.

## 사전 요구사항

- Python 3.11 권장
- macOS Apple Silicon 또는 Linux
- Ollama 설치 및 실행
- 권장 모델 (DGX 운영): `ollama pull exaone3.5:7.8b`
- 최소 사양 (로컬): `ollama pull qwen2.5:3b-instruct`
- Ollama 데스크톱 앱 실행 또는 `ollama serve`
- BGE-M3 모델 사전 다운로드
- OpenAI 모델을 사용할 경우 OpenAI API 키
- 비급여 표준 모델 SQLite 적재를 수행할 경우 `openpyxl`

기본값에서는 외부 네트워크가 필요한 모델 다운로드를 실행 코드에서 수행하지 않습니다. BGE-M3가 HuggingFace 캐시에 없는 경우 인덱싱 또는 검색 단계에서 중단됩니다. Streamlit Cloud 웹 게시 테스트에서만 `HF_MODEL_DOWNLOAD=true`를 설정해 HuggingFace 원격 다운로드를 명시적으로 허용할 수 있습니다.

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

일반 문서(PDF 텍스트 추출 가능):

```bash
python scripts/ingest.py --stage all
```

OCR 문서(실무가이드·상담사례집) 포함:

```bash
python scripts/ingest.py --include-ocr --stage all
```

단계별 실행도 가능합니다.

```bash
python scripts/ingest.py --stage chunks
python scripts/ingest.py --stage index
```

BGE-M3 임베딩은 DGX GPU 기준 수십 분, M4 Mac CPU 기준 수 시간까지 걸릴 수 있습니다. 한 번 생성된 `data/index/`는 재사용합니다.

Parquet 테이블 인덱스 재생성 (OCR 데이터 변경 시):

```bash
python scripts/build_table_index.py
```

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
OPENAI_API_KEY=<OPENAI_API_KEY>
OPENAI_DEFAULT_MODEL=gpt-5.2-chat-latest
OPENAI_MAX_TOKENS=1500
OPENAI_CANDIDATE_MODELS=gpt-5.5,gpt-5.2-chat-latest,gpt-5.4-mini,gpt-5-mini
```

OpenAI 모델을 선택하면 질문과 검색된 문서 청크가 OpenAI API로 전송됩니다.

## 클라우드 배포

Streamlit Community Cloud 또는 Hugging Face Spaces 배포 절차는 `docs/17_DEPLOY_GUIDE.md`를 참고하세요.

클라우드 배포에서는 보통 다음 환경변수를 사용합니다.

```bash
EMBEDDING_MODEL=BAAI/bge-m3
HF_MODEL_DOWNLOAD=true
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

평가 문항은 `eval/smoke_qa_v2.jsonl`에 있으며 10건(실손·상해·면책 시나리오)으로 구성됩니다. 기준은 retrieval recall@8 0.7 이상, 출처 페이지 정확도 0.6 이상입니다.

OCR 문서(실무가이드·상담사례집) 포함 평가:

```bash
python scripts/eval.py --ocr
```

retrieval-only 평가 (Ollama 불필요):

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

## 트러블슈팅

Ollama 미연결: Ollama 데스크톱 앱을 켜거나 `ollama serve`를 실행하세요.

모델 미존재 또는 태그명 오타: `ollama list`로 설치 모델명을 확인하고 `.env`의 `OLLAMA_MODEL` 값을 맞추세요.

BGE-M3 로드 실패: 로컬에서는 네트워크가 가능한 환경에서 `SentenceTransformer("BAAI/bge-m3")`를 먼저 실행해 HuggingFace 캐시에 저장하세요. Streamlit Cloud에서는 웹 게시 테스트 목적일 때만 `HF_MODEL_DOWNLOAD=true`를 설정해 원격 다운로드를 허용하세요.

kiwipiepy 설치 실패: BM25 토크나이저는 정규식 기반 토큰화로 폴백합니다. 다만 한국어 검색 품질은 낮아질 수 있습니다.

Chroma 또는 BM25 인덱스 없음: `python scripts/ingest.py --stage index`를 다시 실행하세요.

관리자 계정 없음: `python scripts/manage_users.py init`을 실행해 첫 관리자를 생성하세요.

OpenAI 모델이 보이지 않음: `.env` 또는 클라우드 secrets에 `OPENAI_API_KEY`가 설정되어 있는지 확인하세요.

## 베타 이월 / 진행 중

| 항목 | 상태 |
|---|---|
| 사이드바 필터 보강 (자사/타사 토글, 상품 유형) | 진행 중 (`feature/eundeo/apply-smoke-test`) |
| smoke_qa_v2 recall 개선 (약관 청크 재분할) | 명세 완료 (#61), 착수 예정 |
| Streamlit 수동 QA (S01~S14 시나리오) | `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` |
| 보험금 자동 계산 (Task 2) | 미착수, Parquet 데이터 활용 예정 |
| unresolved 수술종수 셀 133개 수동 검토 | 미착수 |
| bge-reranker-v2 리랭킹 | 미착수 |
| 멀티턴 질의 재작성 | 미착수 |
| 인덱스 버전 관리와 증분 업데이트 | 미착수 |
| 세션 영속화와 사용자별 히스토리 | 미착수 |
| SSO/OAuth/OIDC | 미착수 |
| 클라우드 로그 영속 저장소 연동 | 미착수 |
| Top-K·온도 자동 설정 | 미착수 |
