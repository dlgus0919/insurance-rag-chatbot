# [Gap Analysis] 백엔드 FastAPI 구현체와 메인 원격 저장소(Streamlit) 간 아키텍처 교차검증 보고서

**작성일**: 2026-05-21  
**작성자**: AI 서브 개발자  
**상태**: ⚠️ 검토 필요 (아키텍처 불일치 및 소스 누락 감지)  
**대상 문서**: [75_BACKEND_FINAL_DELIVERY_REPORT.md](file:///Users/june_kim/Downloads/75_BACKEND_FINAL_DELIVERY_REPORT.md)

---

## 1. 개요 및 목적

팀원이 최종 완료 보고로 제출한 `75_BACKEND_FINAL_DELIVERY_REPORT.md` (이하 **백엔드 보고서**)와 현재 DGX Spark 원격 저장소(`master` 브랜치)의 실제 소스코드 및 설계를 교차검증하였습니다. 

검증 결과, 백엔드 보고서가 전제하고 있는 **"FastAPI 기반 REST API + RDBMS"** 구조와 현재 메인 저장소의 **"Streamlit 모놀리식 단일 앱"** 구조 사이에 **매우 심각한 아키텍처 불일치 및 소스코드 누락(Gap)**이 존재함을 확인하였습니다. 이에 두 설계 간의 결점과 미스매치 요소를 정리하고, 향후 통합을 위한 제안을 보고합니다.

---

## 2. 아키텍처 및 구성 요소 비교 요약

| 비교 항목 | 백엔드 보고서 (75번 문서 기준) | 메인 원격 저장소 (`master` 브랜치 실제 상태) |
| :--- | :--- | :--- |
| **기본 아키텍처** | 3-Tier 아키텍처 (FastAPI API 서버 + 프론트/클라이언트 분리) | Monolithic 아키텍처 (Streamlit 서버에서 RAG 파이프라인 및 UI 통합 실행) |
| **주요 프레임워크** | `FastAPI`, `uvicorn`, `slowapi` | `Streamlit` |
| **인증 방식** | JWT 토큰 기반 인증 (HttpOnly 쿠키 저장) | ID/PW 인증 후 Streamlit `st.session_state` 및 세션 쿠키 관리 |
| **사용자 역할 (RBAC)** | 3가지 역할 (`admin`, `user`, `viewer`) | 2가지 역할 (`admin`, `employee`) |
| **대화 이력 저장소** | SQLite RDBMS (`SQLAlchemy` 비동기 ORM + `aiosqlite` 드라이버) | 로컬 JSON 파일 기반 저장소 (`data/chat_history/{user_id}/{chat_id}.json`) |
| **RAG/LLM 코드 경로** | `src/core/retriever.py`, `src/core/llm_router.py` | `src/rag/pipeline.py`, `src/retrieval/*`, `src/llm/*` (기존 RAG 구조 유지) |
| **API 스트리밍** | SSE(Server-Sent Events) 스트림 API (`status`→`sources`→`token`→`done`) | Streamlit Generator를 사용한 실시간 Chat UI 스트리밍 렌더링 |
| **테스트 스위트** | 총 314개 테스트 (FastAPI API, RBAC, 레이트 리미팅 등 테스트 포함) | 총 276개 테스트 (Streamlit 연동 및 OCR 파이프라인 위주 테스트) |
| **배포 환경 구성** | `Nginx` (Reverse Proxy) + `systemd` 서비스 (`shinhan-api.service`) | `tmux` + 쉘 래퍼 스크립트 (`/srv/ai-ops/bin/run-insurance-rag`) |

---

## 3. 세부 미스매치 및 결점 분석 (Gap Detail)

### 3.1 백엔드 소스코드 및 패키지 의존성 완전 누락
* **현상**: 백엔드 보고서에 기술된 FastAPI 엔드포인트 파일(`src/api/main.py`, `src/api/routes/*.py`), RDBMS 모델 파일(`src/api/models/`), JWT 토큰 핸들러 등 핵심 API 구현 코드가 메인 원격 저장소(`master` 브랜치)에 단 하나도 반영되어 있지 않습니다.
* **의존성 누락**: 메인 저장소의 `requirements.txt`에 백엔드 구동을 위한 `fastapi`, `uvicorn`, `sqlalchemy`, `aiosqlite`, `slowapi` 등의 의존성 라이브러리가 전혀 존재하지 않습니다.
* **테스트 누락**: 백엔드 API 작동 및 RBAC 검증을 위한 31개의 신규 테스트 파일(`tests/test_api_*.py`, `test_rate_limit.py` 등)이 누락되어 있어, 원격 저장소에서는 총 276개의 테스트만 통과하는 상태입니다.

### 3.2 사용자 역할 및 접근 제어 정책의 충돌
* **현상**: 
  * 백엔드 보고서에서는 `admin`, `user`, `viewer` 3가지 역할 및 `require_permission()` 기반 데코레이터 접근 제어를 정의합니다.
  * 반면, 실제 원격 코드인 `src/auth/users.py`에서는 `admin`과 `employee` 2가지 역할만 정의되어 있으며, `users.json` 파일에 회원 정보를 직접 해싱하여 관리합니다.
* **결점**: 두 아키텍처의 권한 등급 및 인증 체계가 불일치하므로, 통합 시 어떤 권한 구조를 메인으로 유지할지 협의가 필요합니다.

### 3.3 대화 저장 모델의 이원화 (RDBMS vs 로컬 파일)
* **현상**:
  * 백엔드 보고서는 SQLite 데이터베이스의 `sessions`, `messages` 테이블을 기반으로 1대N 관계를 정의하고 대화 히스토리를 데이터베이스에 영속화합니다.
  * 실제 원격 코드인 `src/ui/chat_store.py`는 유저별 대화 내역 및 RAG 출처(Chunk 메타데이터)를 직렬화하여 특정 JSON 파일로 디스크에 읽고 쓰는 파일 저장 방식을 고수하고 있습니다.
* **결점**: 별도의 데이터베이스 마이그레이션 스크립트나 동기화 모듈 없이 이 두 구조를 강제로 혼합할 경우 기존 저장된 대화 데이터 유실 혹은 데이터 모델 불일치 오류가 발생할 수 있습니다.

### 3.4 RAG 파이프라인 파일 경로 및 클래스명의 불일치
* **현상**: 백엔드 보고서에서는 RAG 엔진과 검색기 경로를 `src/core/retriever.py`, `src/core/llm_router.py`로 설명하고 있으나, 실제 원격 저장소에는 `src/core` 폴더가 존재하지 않으며, `src/rag/pipeline.py` 및 `src/retrieval/vector_store.py`, `src/llm/factory.py` 등의 모듈화된 설계를 사용하고 있습니다.
* **결점**: 백엔드 개발 팀이 기존 설계 구조를 무시하고 독자적인 네이밍 규칙으로 RAG 래퍼를 생성했거나, 완전히 다른 브랜치에서 기존 코드를 마이그레이션하지 않은 채 별도로 개발을 진행했음을 뜻합니다.

### 3.5 문서 번호 인덱싱 충돌
* **현상**: 메인 원격 저장소의 `docs/` 폴더에 이미 보관되어 있는 69번~74번 문서 인덱스(`69_PROJECT_MID_CHECKPOINT_20260513.md` 등)와 백엔드 보고서 내부에서 인용하는 69번~74번 문서 인덱스(`docs/69_baek_week2.md` 등)의 파일명과 내용이 완전히 충돌하고 있습니다.

---

## 4. 향후 조치 제안 및 아키텍처 통합 방향

현재 프로젝트의 실제 코드가 백엔드 최종 보고서의 내용과 100% 분리되어 있기 때문에, 이 상태로는 백엔드 보고서에 기술된 FastAPI 엔드포인트를 프로덕션 환경에 즉시 배포할 수 없습니다. 다음과 같은 단계적 조치를 제안합니다.

### 1단계: 백엔드 소스코드 브랜치 역추적 및 확보
* 백엔드 개발 팀이 작업한 소스코드가 저장되어 있는 별도의 Git 브랜치가 존재하는지, 혹은 다른 리포지토리에 방치되어 있는지를 먼저 파악하여 DGX 원격 저장소의 독립된 피처 브랜치(예: `feature/fastapi-backend`)로 코드를 가져와야 합니다.

### 2단계: API 서버와 Streamlit UI 간의 역할 정리
* **안 A (추천)**: **API 중심 아키텍처 전환**  
  RAG 파이프라인을 FastAPI로 일원화하고, 기존의 `streamlit_app.py`는 단지 FastAPI API를 호출하는 단순한 UI 클라이언트로 역할을 분리(De-coupling)시킵니다. 이를 통해 중복되는 대화 저장 로직(`chat_store.py`)과 사용자 인증 로직(`users.py`)을 FastAPI의 SQLite/JWT 기반의 통일된 설계로 일괄 전환합니다.
* **안 B**: **Streamlit 모놀리식 유지 및 FastAPI 백엔드 트랙 폐기**  
  만약 원격 서버의 리소스 절약이나 단일 프로세스 관리의 편리함이 최우선이라면, 백엔드 개발 팀의 결과물을 반영하지 않고 현재 Streamlit 모놀리식 구조를 메인으로 채택합니다. 이 경우 75번 백엔드 보고서는 폐기 및 롤백이 불가피합니다.

### 3단계: 데이터 모델 통합 및 마이그레이션 설계
* SQLite 데이터베이스 스키마와 기존 JSON 파일 기반 대화 파일 간의 마이그레이션 스크립트를 작성하여, 사용자가 과거에 작성한 `/data/chat_history`의 데이터를 유실 없이 SQLite `messages` 및 `sessions` 테이블로 이관할 수 있는 절차를 마련해야 합니다.
