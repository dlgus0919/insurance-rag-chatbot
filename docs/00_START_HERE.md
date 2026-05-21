# 00. START HERE - 프로젝트 진입 및 기준 가이드

이 문서는 `insurance-rag-chatbot` 프로젝트에 신규 편입된 개발자(사람 및 AI 에이전트)가 프로젝트를 파악하기 위해 **가장 먼저 읽어야 하는 핵심 기준 문서 7가지**를 안내합니다.

현재 프로젝트는 번호 충돌이나 역사적 문서의 난립이 있으므로, 본 가이드에 지정된 활성(Active) 기준 문서를 우선적으로 참고하시기 바랍니다.

---

## 📌 신규 개발자 필독 문서 Top 7

### 1. [87_AI_SUBDEVELOPER_ONBOARDING_HANDOFF.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/87_AI_SUBDEVELOPER_ONBOARDING_HANDOFF.md)
* **목적**: 신규 서브 개발자를 위한 온보딩 및 인수인계 문서
* **핵심 내용**: DGX Spark 원격 개발 환경 접속 방법, Streamlit 기동법, git commit/push 규칙, 원격 테스트 수행 방법 및 비밀정보 보안 수칙이 포함되어 있습니다.

### 2. [88_BACKEND_ARCHITECTURE_GAP_ANALYSIS.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/88_BACKEND_ARCHITECTURE_GAP_ANALYSIS.md)
* **목적**: 백엔드 FastAPI 구현 아키텍처와 현재 RAG 챗봇 구조 간의 갭 분석 보고서
* **핵심 내용**: 외부 백엔드 개발 결과물과 현재 Streamlit 모놀리식 단일 앱 설계 간의 불일치 원인, 소스코드 및 의존성 유실, 사용자 역할 충돌 및 이를 통합하기 위한 조치 방안을 서술합니다.

### 3. [89_DOCS_INDEX_COLLISION_REPAIR_AND_PROJECT_IMPROVEMENT_SPEC.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/89_DOCS_INDEX_COLLISION_REPAIR_AND_PROJECT_IMPROVEMENT_SPEC.md)
* **목적**: 문서 번호 충돌 보정 정책 및 현 단계 개선 요구사항 명세
* **핵심 내용**: `docs/` 내 129개 문서의 중복 번호 분석 결과, 신규 문서 네이밍/반입 규칙 및 RAG 파이프라인의 구조적 결점과 해결 우선순위를 정의합니다.

### 4. [90_BACKEND_FINAL_DELIVERY_REPORT_IMPORTED.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/90_BACKEND_FINAL_DELIVERY_REPORT_IMPORTED.md)
* **목적**: 팀원이 작성한 백엔드(FastAPI + SQLite + JWT + RBAC) 최종 보고서 (수입본)
* **핵심 내용**: Week 1~4에 개발된 API 설계 명세, 에러 응답 규격, 레이트 리미팅 정책 및 배포 운영 가이드라인이 들어있습니다.

### 5. [DGX_SPARK_RUNBOOK.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/DGX_SPARK_RUNBOOK.md)
* **목적**: DGX Spark GPU 서버 상세 환경 구성 및 기동 런북
* **핵심 내용**: LLM 서버(SGLang, vLLM, Ollama) 기동 및 포트 충돌 대처 방법, 다중 GPU 할당 방법 등이 구체적으로 설명되어 있습니다.

### 6. [AI_REVIEWER_GUIDE.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/AI_REVIEWER_GUIDE.md)
* **목적**: AI 리뷰어(Claude) 및 자동 검증 파이프라인 가이드
* **핵심 내용**: 구현된 기능의 아키텍처 준수성 검토 및 Git PR 단위의 자동 리뷰 워크플로우를 기술합니다.

### 7. [PERSONAL_AGENT_WORKFLOW.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/PERSONAL_AGENT_WORKFLOW.md)
* **목적**: 개발자 개인용 에이전트와 공용 에이전트 간의 분리 작업 가이드
* **핵심 내용**: Linux 개인 계정에서의 codex/claude 로그인 및 공용 Secrets 접근 차단, Discord Bot을 활용한 협업 구조를 다룹니다.

---

## 🛠️ 개발 및 테스트 기본 명령

* **기본 테스트**:
  ```bash
  source .venv/bin/activate
  pytest -q
  ```
* **RAG 회귀 평가 (Retrieval Accuracy)**:
  ```bash
  RERANKER_ENABLED=false python scripts/eval.py --ocr
  ```
* **오프라인 모드 검증**:
  ```bash
  OFFLINE_MODE=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false python scripts/eval.py --ocr
  ```
