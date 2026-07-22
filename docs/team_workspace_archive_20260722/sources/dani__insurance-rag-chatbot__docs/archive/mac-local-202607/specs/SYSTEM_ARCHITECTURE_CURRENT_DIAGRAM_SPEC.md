# 현행 챗봇 아키텍처 다이어그램 명세

이 문서는 현재 버전의 챗봇 아키텍처를 다이어그램으로 재구성하기 위한 설계 명세다.

첨부된 기존 아키텍처 이미지는 Streamlit 중심 구조와 Local/Cloud LLM 투트랙 전략을 포함하고 있었다. 현재 시스템은 Frontend SPA, FastAPI Backend, Local LLM 중심 구조로 전환되었으므로 이를 반영한다.

단, 과거에 사용했거나 검토했던 구성은 완전히 삭제하지 않고 “개발 과정에서 거쳐온 이전 단계”로 표시한다.

## 1. 표기 원칙

### 현재 버전

- 컬러 박스
- 실선 테두리
- 실선 화살표
- 주요 흐름의 중심에 배치

### 과거 버전 또는 검토 후 제외된 구성

- 회색 박스
- 점선 테두리
- 점선 화살표
- 낮은 opacity
- “과거 버전”, “검토 후 제외”, “비활성” 등의 라벨 표시

## 2. 현재 핵심 흐름

```text
사용자
→ Frontend SPA
→ Nginx Reverse Proxy
→ FastAPI Backend
→ RAG Service
→ Hybrid Retrieval / TableStore / Evidence Gate
→ Local LLM
→ SSE Streaming 답변
→ SQLite 저장
```

## 3. 과거 흐름으로 남길 구성

```text
Streamlit Web UI
OpenAI API Client
GPT 계열 외부 API 모델
Local / Cloud 모델 선택 전략
OpenAI 토큰 사용량 집계
```

위 구성은 현재 운영 중심 경로가 아니므로 회색 점선으로 표시한다.

## 4. 최종 다이어그램 Mermaid 초안

```mermaid
flowchart LR
  %% =====================
  %% Legend
  %% =====================
  LEGEND_CURRENT[현재 버전<br/>실선 + 컬러]
  LEGEND_LEGACY[과거/검토 후 제외된 버전<br/>회색 + 점선]

  %% =====================
  %% Users
  %% =====================
  subgraph USER["사용자 / 권한 영역"]
    ADMIN[관리자]
    EMPLOYEE[직원 / 일반 사용자]
    VIEWER[viewer 권한]
  end

  %% =====================
  %% Current Frontend
  %% =====================
  subgraph FE["현재: Frontend SPA"]
    LOGIN[Login Page<br/>pages/login.js]
    CHAT[Chat Page<br/>SSE Streaming]
    ADMIN_PAGE[Admin Page<br/>사용자 / 로그 / 통계]
    FE_MODULES[JS Modules<br/>auth · session · ui · modal]
    API_FETCH[apiFetch / SSE parser / source formatting]
  end

  %% =====================
  %% Current Proxy
  %% =====================
  subgraph PROXY["현재: Nginx Reverse Proxy"]
    NGINX_ROOT["/ → Frontend 정적 파일"]
    NGINX_API["/api → FastAPI Backend"]
    NGINX_HEALTH["/health → health check"]
  end

  %% =====================
  %% Current Backend
  %% =====================
  subgraph API["현재: FastAPI Backend"]
    AUTH[Auth / RBAC<br/>JWT + HttpOnly Cookie]
    CHAT_API["/api/chat/stream<br/>SSE Streaming"]
    SESSION_API["/api/sessions<br/>세션 / 메시지 / 내보내기"]
    ADMIN_API["/api/admin<br/>사용자 / 감사 로그 / 통계"]
    SYSTEM_API["/api/system<br/>모델 목록 / 시스템 상태"]
    RAG_SERVICE[RAG Service<br/>src/api/rag_service.py]
    SQLITE[(SQLite<br/>sessions / messages / audit_logs)]
    USERS_JSON[(users.json<br/>role / password hash)]
  end

  %% =====================
  %% Current RAG
  %% =====================
  subgraph RAG["현재: RAG 검색 및 답변 생성 엔진"]
    ROUTER[질문 라우팅<br/>general / formal / quickcode]
    EVIDENCE[Evidence Gate<br/>근거 부족 시 답변 차단]
    HYBRID[Hybrid Retrieval]
    DENSE[Dense Search<br/>BGE-M3 + ChromaDB]
    BM25[BM25 Keyword Search]
    RRF[RRF Fusion]
    RERANKER[Reranker]
    TABLE_LOOKUP[TableStore Lookup<br/>Parquet 정형 테이블 직접 조회]
    PROMPT[Prompt Builder<br/>질문 + 검색 근거 + 시스템 프롬프트]
    ANSWER[출처 포함 답변 생성]
  end

  %% =====================
  %% Current Data / Index
  %% =====================
  subgraph DATA["현재: 문서 검색 / 인덱스 영역"]
    PDF[보험 약관 / 심평원 / 실무가이드 / 상담사례집 PDF]
    INGEST[Ingest / OCR / Chunking]
    CHUNKS[(JSONL Chunks)]
    EMBED[BGE-M3 Embedding]
    CHROMA[(ChromaDB<br/>Dense Vector Index)]
    BM25_INDEX[(BM25 pkl)]
    PARQUET[(Parquet Table Index<br/>수술종수 / 장해율)]
    INDEX_MODE[index modes<br/>default / v2_only / v1_v2_combined]
  end

  %% =====================
  %% Current Local LLM
  %% =====================
  subgraph LOCAL_LLM["현재: Local LLM 생성 영역"]
    LLM_ROUTER[Local LLM Router]
    VLLM[vLLM Server<br/>Gemma 계열]
    SGLANG[SGLang Server<br/>GPT-OSS 계열]
    OLLAMA[Ollama Server<br/>local models]
    LOCAL_POLICY[현재 방향<br/>외부 API 없이 로컬 LLM 중심 운영]
  end

  %% =====================
  %% Current Output
  %% =====================
  subgraph OUTPUT["현재: 응답 / 운영 표시"]
    SOURCES[출처 청크 표시<br/>문서명 / 페이지]
    TIMING[응답 시간 표시<br/>retrieve_ms / llm_ms / total_ms]
    EXPORT[채팅 저장 / 내보내기<br/>TXT / CSV / JSON]
    AUDIT[감사 로그 저장]
  end

  %% =====================
  %% Legacy UI
  %% =====================
  subgraph LEGACY_UI["과거 버전: Streamlit UI"]
    STREAMLIT[Streamlit Web UI]
    STREAMLIT_ADMIN[Streamlit 관리자 페이지]
    LEGACY_ROUTE["/legacy 경로로 보존 가능"]
  end

  %% =====================
  %% Legacy LLM Strategy
  %% =====================
  subgraph LEGACY_LLM["과거/검토 버전: 투트랙 LLM 전략"]
    MODEL_SELECT[LLM 모델 선택<br/>Local / Cloud]
    OPENAI_CLIENT[OpenAIClient]
    OPENAI_API[OpenAI Chat Completions API]
    GPT_MODELS[GPT 계열 외부 API 모델]
    TOKEN_USAGE[OpenAI 토큰 사용량 집계]
  end

  %% =====================
  %% Current Main Flow
  %% =====================
  ADMIN --> FE
  EMPLOYEE --> FE
  VIEWER --> FE

  FE --> PROXY
  PROXY --> API

  AUTH --> USERS_JSON
  CHAT_API --> RAG_SERVICE
  SESSION_API --> SQLITE
  ADMIN_API --> SQLITE
  CHAT_API --> SQLITE

  RAG_SERVICE --> ROUTER
  ROUTER --> HYBRID
  ROUTER --> TABLE_LOOKUP
  ROUTER --> EVIDENCE

  HYBRID --> DENSE
  HYBRID --> BM25
  DENSE --> RRF
  BM25 --> RRF
  RRF --> RERANKER
  RERANKER --> EVIDENCE
  TABLE_LOOKUP --> EVIDENCE
  EVIDENCE --> PROMPT
  PROMPT --> LLM_ROUTER

  LLM_ROUTER --> VLLM
  LLM_ROUTER --> SGLANG
  LLM_ROUTER --> OLLAMA
  VLLM --> ANSWER
  SGLANG --> ANSWER
  OLLAMA --> ANSWER

  ANSWER --> CHAT_API
  CHAT_API --> CHAT
  ANSWER --> SOURCES
  ANSWER --> TIMING
  ANSWER --> EXPORT
  ANSWER --> AUDIT
  AUDIT --> SQLITE

  %% =====================
  %% Data Flow
  %% =====================
  PDF --> INGEST
  INGEST --> CHUNKS
  INGEST --> EMBED
  EMBED --> CHROMA
  CHUNKS --> BM25_INDEX
  CHUNKS --> PARQUET
  CHROMA --> DENSE
  BM25_INDEX --> BM25
  PARQUET --> TABLE_LOOKUP
  INDEX_MODE --> HYBRID

  %% =====================
  %% Legacy Relationships
  %% =====================
  STREAMLIT -.과거 메인 UI였음. 현재는 SPA로 전환.-> FE
  STREAMLIT_ADMIN -.관리자 기능은 FastAPI Admin API + SPA Admin Page로 이전.-> ADMIN_PAGE
  LEGACY_ROUTE -.필요 시 Nginx /legacy로 보존 가능.-> PROXY

  MODEL_SELECT -.과거 Local / Cloud 선택 전략.-> LLM_ROUTER
  OPENAI_CLIENT -.현재 운영 방향에서는 제외.-> LLM_ROUTER
  OPENAI_API -.외부 API 호출 경로 비활성.-> LOCAL_POLICY
  GPT_MODELS -.외부 GPT 모델 사용 경로 비활성.-> LOCAL_POLICY
  TOKEN_USAGE -.OpenAI 사용량 집계는 현재 핵심 운영 경로 아님.-> ADMIN_API

  %% =====================
  %% Styles
  %% =====================
  classDef current fill:#ffffff,stroke:#2563eb,stroke-width:2px,color:#111827;
  classDef backend fill:#ffffff,stroke:#0f766e,stroke-width:2px,color:#111827;
  classDef rag fill:#ffffff,stroke:#16a34a,stroke-width:2px,color:#111827;
  classDef data fill:#ffffff,stroke:#7c3aed,stroke-width:2px,color:#111827;
  classDef llm fill:#ffffff,stroke:#ea580c,stroke-width:2px,color:#111827;
  classDef output fill:#ffffff,stroke:#dc2626,stroke-width:2px,color:#111827;
  classDef legacy fill:#f3f4f6,stroke:#9ca3af,stroke-width:2px,stroke-dasharray: 6 6,color:#6b7280;
  classDef store fill:#f8fafc,stroke:#64748b,stroke-width:2px,color:#111827;

  class USER,FE,PROXY current;
  class API backend;
  class RAG rag;
  class DATA data;
  class LOCAL_LLM llm;
  class OUTPUT output;
  class LEGACY_UI,LEGACY_LLM legacy;

  class STREAMLIT,STREAMLIT_ADMIN,LEGACY_ROUTE,MODEL_SELECT,OPENAI_CLIENT,OPENAI_API,GPT_MODELS,TOKEN_USAGE,LEGEND_LEGACY legacy;
  class SQLITE,USERS_JSON,CHUNKS,CHROMA,BM25_INDEX,PARQUET store;
  class LEGEND_CURRENT current;
```

## 5. 디자인 의뢰용 요약

### 현재 버전으로 강조할 영역

| 영역 | 추천 색상 | 설명 |
|---|---|---|
| Frontend SPA | 파랑 | 현재 사용자가 직접 접속하는 메인 화면 |
| FastAPI Backend | 청록 | 인증, 세션, 채팅, 관리자 API |
| RAG Engine | 초록 | 검색, 라우팅, Evidence Gate, 프롬프트 구성 |
| Data / Index | 보라 | ChromaDB, BM25, Parquet, JSONL chunks |
| Local LLM | 주황 | vLLM, SGLang, Ollama 기반 로컬 생성 |
| Output / Logs | 빨강 또는 남색 | 출처, 응답 시간, 내보내기, 감사 로그 |

### 과거 버전으로 표시할 영역

| 과거 구성 | 현재 상태 | 표시 방법 |
|---|---|---|
| Streamlit Web UI | Frontend SPA로 전환됨 | 회색 점선 박스 |
| Streamlit 관리자 페이지 | SPA Admin Page + FastAPI Admin API로 이전 | 회색 점선 박스 |
| Local / Cloud 모델 선택 | 로컬 LLM 중심으로 정리됨 | 회색 점선 박스 |
| OpenAIClient | 현재 핵심 운영 경로에서 제외 | 회색 점선 박스 |
| OpenAI Chat Completions API | 외부 API 사용 경로 비활성 | 회색 점선 박스 |
| GPT 계열 외부 API 모델 | 로컬 GPT-OSS/SGLang 방향으로 전환 | 회색 점선 박스 |
| OpenAI 토큰 사용량 집계 | 현재 핵심 운영 기능 아님 | 회색 점선 박스 |

## 6. 발표 메시지

이 다이어그램에서 전달해야 할 핵심 메시지는 다음과 같다.

1. 초기에는 Streamlit 기반으로 빠르게 RAG 챗봇을 구현했다.
2. 이후 운영성과 확장성을 위해 Frontend SPA와 FastAPI Backend 구조로 전환했다.
3. 기존에는 OpenAI API와 로컬 LLM을 함께 고려하는 투트랙 전략이었다.
4. 현재는 개인정보와 운영비, 내부망 실행 가능성을 고려해 로컬 LLM 중심 구조로 정리했다.
5. 과거 구성은 삭제된 실패물이 아니라, 현재 구조로 진화하기 위해 거쳐온 단계로 표시한다.

