# 206. Project Development Environment

작성 기준일: 2026-06-09  
기준 버전: 정식 릴리스 `v1.0.5`

이 문서는 보험 문서 RAG 챗봇을 실제로 개발, 검증, 운영한 환경과 방법론을 정리한다. 설치 권장안이 아니라 현재 프로젝트의 실제 개발 이력과 운영 기준을 설명하는 문서다.

## 1. 개발 장비 및 운영체제

| 구분 | 실제 개발 환경 |
|---|---|
| 개발·운영 장비 | NVIDIA DGX Spark (`aitopatom-255d`) |
| OS | Ubuntu 24.04.4 LTS (Noble Numbat) |
| OS 계열 | Linux / Debian 계열 |
| Kernel | Linux 6.17.0-1018-nvidia |
| CPU 아키텍처 | ARM64 (`aarch64`) |
| CPU | ARM Cortex-X925 / Cortex-A725, 총 20코어 |
| 시스템 메모리 | 약 128 GB급 통합 메모리 |
| 저장장치 | NVMe 약 1 TB급 |
| CUDA Toolkit | CUDA 13.0 계열 |

팀원은 Tailscale과 SSH로 DGX Spark에 접속하고, 각자의 Linux 계정 및 개인 워크스페이스에서 개발했다.

```text
/srv/shared/workspaces/<user>/insurance-rag-chatbot
```

공용 운영본은 다음 경로를 기준으로 관리한다.

```text
/srv/shared/projects/insurance-rag-chatbot
```

## 2. 언어 및 개발 도구

| 도구 | 사용 목적 |
|---|---|
| Python 3.12 계열 | 백엔드, RAG, GraphDB, 인덱싱, 보험금 계산, 테스트 |
| pip/venv | Python 의존성 격리 |
| Node.js 24 계열 | 프론트엔드 빌드 및 E2E 테스트 |
| npm | JavaScript 패키지 관리 |
| Git/GitHub | 형상 관리, 브랜치 통합, 릴리스 태그 관리 |
| Bash/tmux | DGX 장시간 작업, LLM 서버, 운영 wrapper |
| Poppler/PyMuPDF/pdfplumber | PDF 변환 및 텍스트 추출 |
| SQLite CLI/Python sqlite3 | DB 점검 및 진단 |

Python 애플리케이션은 프로젝트 루트의 `.venv`를 기본으로 사용한다. 대형 LLM 서빙은 SGLang/vLLM/Ollama 실행 환경과 `/srv/ai-ops` 운영 스크립트로 분리한다.

## 3. 백엔드 및 데이터 환경

현재 주 실행 경로는 FastAPI가 SPA 정적 파일과 API를 함께 제공하는 구조다.

| 영역 | 사용 기술 |
|---|---|
| API 서버 | FastAPI, Uvicorn |
| 기존/보조 UI | Streamlit legacy |
| 설정 관리 | python-dotenv, pydantic-settings |
| 인증·업무 DB | SQLite, SQLAlchemy, aiosqlite |
| 벡터 검색 | ChromaDB |
| 키워드 검색 | BM25, Kiwi 형태소 분석기 |
| 임베딩 | BGE-M3, sentence-transformers |
| 모델 기반 처리 | PyTorch, Transformers |
| 표 데이터 | SQLite, Parquet, openpyxl |
| PDF 처리 | pdfplumber, PyMuPDF, Poppler |
| GraphRAG | SQLite 기반 GraphDB와 자체 graph retriever |
| 테스트 | pytest, pytest-cov |

검색 파이프라인은 `BGE-M3 임베딩 + ChromaDB + BM25 + RRF/Dynamic RRF + reranker` 조합으로 개발했다. 구조화 근거와 심사 경로는 SQLite GraphDB에 저장하고, 비급여표준모델은 별도 SQLite DB로 관리한다.

## 4. 프론트엔드 환경

프론트엔드는 별도 대형 프레임워크 없이 HTML, CSS, JavaScript ES Module 기반 SPA로 개발했다.

| 구분 | 사용 기술 |
|---|---|
| 화면 | HTML5, CSS3, Vanilla JavaScript |
| 모듈 방식 | JavaScript ES Module |
| 번들러 | esbuild |
| E2E 테스트 | Playwright |
| 서비스 방식 | FastAPI same-origin 정적 파일 제공 |

소스는 `frontend/`에 있으며, 운영 번들은 `frontend/dist/app.min.js`로 생성한다.

## 5. AI/RAG 실행 환경

### 5.1 임베딩 및 검색

| 구성 | 역할 |
|---|---|
| BGE-M3 | 문서 청크 임베딩 |
| ChromaDB | semantic retrieval |
| BM25 | keyword retrieval |
| RRF/Dynamic RRF | 벡터/키워드 검색 결과 융합 |
| reranker | 최종 근거 재정렬 |
| SQLite GraphDB | 약관 ontology, 수가코드, 판단 개념, evidence path 검색 |

### 5.2 LLM 제공 방식

프로젝트는 한 가지 모델에 고정하지 않고 다음 provider를 공통 인터페이스로 연결한다.

| Provider | 개발·검증 용도 |
|---|---|
| SGLang | DGX Spark 대형 로컬 LLM의 주 실행 경로 |
| vLLM | Gemma, Nemotron 등 모델별 호환 실행 경로 |
| Ollama | EXAONE, Llama GGUF 등 안정 fallback |
| OpenAI API | 클라우드 모델 비교 및 제한적 보조 검증 |

운영 기준은 로컬 LLM이다. OpenAI API는 폐쇄망/비용/보안 제약을 고려해 기본 운영 경로가 아니라 선택적 비교 및 보조 검증 경로로만 둔다.

## 6. OCR 개발 환경

OCR은 문서 특성에 따라 여러 방식을 조합했다.

| 방식 | 역할 |
|---|---|
| PDF 텍스트 직접 추출 | 텍스트 PDF 기본 파싱 |
| Poppler 기반 이미지 변환 | 스캔 PDF OCR 전처리 |
| NAVER CLOVA OCR | 한국어 문서 OCR 및 표 인식 |
| Tesseract/EasyOCR/PaddleOCR | 선택형 비교·검증 경로 |
| 수동 보정본 OCR | 품질이 중요한 문서의 보정본 인덱스 |

현재 앱 실행은 이미 생성된 OCR/인덱스 산출물을 사용하므로 모든 OCR 선택 의존성이 항상 설치되어 있을 필요는 없다.

## 7. 현재 정식 개발 방법론

현재 정식 개발 흐름은 다음을 기준으로 한다.

| 방법론 | 설명 |
|---|---|
| Codex 중심 개발 | 요구사항 분석, 코드 수정, 테스트, 문서화, 릴리스 정리 |
| DGX 메인 저장소 기준 개발 | `/srv/shared/projects/insurance-rag-chatbot`를 기준으로 최종 통합 |
| GitHub master 릴리스 관리 | 커밋, 태그, 푸시를 통해 버전 명시 |
| pytest/Playwright 검증 | 단위/통합/E2E 테스트로 회귀 방지 |
| 운영 wrapper | DGX 바탕화면 실행기 및 `/srv/ai-ops/bin` 스크립트로 앱 기동 |
| 실무자 승인 워크플로우 | ontology 후보를 실무자가 승인/보류/거절 후 active manifest에 반영 |
| 로컬 LLM 우선 운영 | SGLang/vLLM/Ollama 기반 오프라인 또는 준오프라인 운영 |

이 방식은 비용과 보안, 재현성을 모두 고려해 정착한 현재 기준이다.

## 8. 과거 사용했으나 폐기한 개발 방법론

다음 방법론은 과거 검토 또는 사용 이력이 있으나 현재 정식 개발 흐름에서는 제외한다.

| 도구/방법론 | 과거 활용 방식 | 현재 상태 | 폐기 사유 |
|---|---|---|---|
| Claude 기반 보조 개발/검토 | 설계 브레인스토밍, 코드 검토, 문서 초안 작성, 대안 비교 | 정식 개발 방법론에서 제외 | 사용량 증가에 따른 이용료 부담, Codex/DGX 중심 개발 흐름과 기능 중복 |
| Discord bot 기반 개발/운영 연계 | 개발 진행 공유, 원격 명령/알림, 팀 협업 보조 인터페이스 실험 | 정식 개발 방법론에서 제외 | 사용량 증가에 따른 이용료 부담, 운영 유지보수 복잡도 증가 |

Claude와 Discord bot은 프로젝트 초기에 생산성 보조 수단으로 의미가 있었지만, 장기 운영 관점에서는 사용량에 비례한 비용 부담과 관리 복잡도가 커졌다. 따라서 현재는 `Codex + DGX Spark + GitHub + 로컬 LLM + pytest/Playwright` 조합을 공식 개발·검증 방법론으로 둔다.

## 9. 협업 및 운영 방식

| 영역 | 현재 방식 |
|---|---|
| 원격 개발 | VS Code Remote SSH, 터미널 SSH |
| 네트워크 | Tailscale 사설망 |
| 저장소 | GitHub `koreaben777/insurance-rag-chatbot` |
| 개인 작업 | 사용자별 Linux 계정과 개인 workspace |
| 최종 통합 | DGX 메인 저장소의 master 기준 |
| 앱 기동 | DGX 바탕화면 실행기 또는 운영 wrapper |
| 외부 접속 | SSH tunnel로 `localhost:18080` 접근 |

## 10. 현재 한계 및 주의사항

| 항목 | 상태 |
|---|---|
| Streamlit | 초기/legacy UI 성격이며 현재 주 UI는 FastAPI + SPA |
| OpenAI API | 기본 운영 경로가 아니라 선택적 비교/보조 검증 경로 |
| gpt-oss-120b | 로컬 파일 다운로드는 되었으나 DGX Spark 메모리 부족으로 실사용 기동 실패 |
| OCR 선택 의존성 | 앱 실행에는 필수가 아니며 재OCR 작업 시 별도 환경 확인 필요 |
| 통합 Ingestion Registry | 설계안은 있으나 현재 실제 운영 DB 테이블은 아님 |

## 11. 개발 환경 요약

```text
NVIDIA DGX Spark
└── Ubuntu 24.04 LTS / ARM64 / CUDA
    ├── Python 3.12
    │   ├── FastAPI + Uvicorn
    │   ├── SQLite + SQLAlchemy + aiosqlite
    │   ├── BGE-M3 + ChromaDB + BM25 + RRF/Dynamic RRF
    │   ├── SQLite GraphDB + GraphRAG
    │   ├── deterministic claim calculation
    │   └── pytest
    ├── Node.js 24 + npm
    │   ├── Vanilla JavaScript SPA
    │   ├── esbuild
    │   └── Playwright
    ├── Local LLM serving
    │   ├── SGLang
    │   ├── vLLM
    │   └── Ollama
    └── Retired methods
        ├── Claude based development assistance
        └── Discord bot based development/ops assistance
```
