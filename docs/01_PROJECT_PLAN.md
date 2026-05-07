# 보험 문서 RAG 챗봇 — 프로젝트 계획서

> 작성: 기획자 / 최초작성: 2026-04-30 / 최종수정: 2026-04-30 (M6-M7 확장계획 추가)
> 현재 상태: Alpha M1-M5 완료 / M6-M7 계획 수립 완료

## 1. 배경 및 목표

### 1.1 문제
보험사 직원은 여러 종류의 전문 문서 — ① 1,429페이지짜리 「건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수」(이하 심평원 고시), ② 실손의료보험 약관, ③ 보상가이드북 등 — 을 교차 참조하여 보상 여부, 수술코드, 산정 기준 등을 수작업으로 확인해야 한다. 페이지 수와 문서 간 연결 복잡성 때문에 단순 Ctrl+F 검색은 비효율적이며, 동일 진단코드가 여러 문서에 분산되어 있어 맥락 파악이 어렵다.

### 1.2 목표 (알파)
보험사 직원이 자연어 질문으로 고시 문서의 관련 조항을 즉시 찾고, 출처 페이지·조항과 함께 답변받을 수 있는 챗봇 어시스턴트의 작동 가능한 최소 버전(Working Alpha)을 구축한다.

### 1.3 비목표 (알파)
- 다국어 지원, 권한·인증, 멀티 사용자 동시 운영
- 스캔 이미지 페이지의 OCR
- 멀티턴 대화 기반 질의 재작성·맥락 누적
- 운영 배포(Docker/CI/CD)
- 답변의 법적 효력 보장 — 어디까지나 검색 보조

## 2. 요구사항

### 2.1 사용자 시나리오
1. 직원이 챗 UI에 자연어로 질문한다. (예: "치과의원 재진 진찰료의 야간 가산 규정은?")
2. 시스템이 관련 조항을 검색하고 로컬 LLM이 답변을 생성한다.
3. 답변과 함께 출처(편/부/장/절, 페이지)와 원문 청크가 표시된다.
4. 직원이 출처를 확인하고 해당 조항의 신뢰도를 판단한다.

### 2.2 기능 요구사항
- 한국어 자연어 질의 입력
- 코드 기반 조회(AA157, 12345 등)와 의미 기반 조회 모두 지원
- 답변에 출처 인용 (편/부/장/절, 페이지 번호)
- 검색 결과 청크 원문 열람
- 세션 내 대화 히스토리 표시
- 사이드바에서 LLM 모델, Top-K 등 설정 가능

### 2.3 비기능 요구사항
- macOS / Linux 환경에서 동작
- 단일 사용자 로컬 실행
- 외부 API 호출 없음 (LLM 포함 모두 로컬)
- 인덱싱은 1회성 오프라인 작업으로 분리
- 챗 응답 지연: 로컬 LLM 한도 내(질문당 30초 이내 목표)

## 3. 기술 스택 결정

| 영역 | 선택 | 사유 |
|---|---|---|
| 언어 | Python 3.11 | 생태계, 라이브러리 호환 |
| 프론트엔드 | Streamlit `1.30+` | 사용자 지정 |
| PDF 파싱 | pdfplumber + PyMuPDF(fitz) 폴백 | 표/한국어 안정성 |
| 청킹 전략 | 계층 헤더 인식 + 슬라이딩 윈도우 | 문서 구조 보존 |
| 임베딩 | BAAI/bge-m3 (sentence-transformers) | 다국어 SOTA, 한국어 양호 |
| 벡터 스토어 | ChromaDB (PersistentClient) | 로컬 영속화, 메타데이터 필터 |
| 키워드 검색 | rank_bm25 + kiwipiepy 토크나이저 | 코드/고유어 정확매칭. 자바 비의존 |
| 융합 | RRF (Reciprocal Rank Fusion) | 구현 단순, 강건 |
| 로컬 LLM | Ollama + `qwen2.5:3b-instruct` (사용자 환경에 이미 설치됨) | M4 Mac Metal, 한국어 양호, Apache-2.0, 알파 검증 속도 우선. 환경변수로 교체 가능 |
| 단위 테스트 | pytest | 표준 |

## 4. 시스템 아키텍처

### 4.1 컴포넌트 도식

```
[사용자]
   │ 질문
   ▼
┌──────────────────────────────────────────┐
│  Streamlit Chat UI                       │
│  · 입력창, 메시지 히스토리                 │
│  · 사이드바: 모델/Top-K/온도              │
│  · 출처 expander                         │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  RAG Pipeline (src/rag/pipeline.py)      │
│  ┌────────────────────────────────────┐  │
│  │ 질의 전처리 (코드 패턴 감지)         │  │
│  └────────────────────────────────────┘  │
│  ┌────────────┬───────────────────────┐  │
│  │ Dense 검색  │ BM25 검색              │  │
│  │ (Chroma)   │ (rank_bm25 + kiwi)    │  │
│  └─────┬──────┴───────────┬───────────┘  │
│        └──── RRF 융합 ────┘              │
│                  │ Top-K 청크             │
│                  ▼                        │
│  ┌────────────────────────────────────┐  │
│  │ 프롬프트 조립                        │  │
│  └────────────────────────────────────┘  │
│                  │                        │
│                  ▼                        │
│  ┌────────────────────────────────────┐  │
│  │ Ollama LLM 호출                     │  │
│  └────────────────────────────────────┘  │
│                  │                        │
│                  ▼                        │
│         답변 + 인용 청크 ID                │
└──────────────────────────────────────────┘

────────── 오프라인 인덱싱 (1회) ──────────

[PDF]
  │
  ▼ pdfplumber/PyMuPDF
[페이지별 raw text + 페이지 번호]
  │
  ▼ HierarchicalChunker
[chunks.jsonl] — 메타: volume/part/chapter/section/page/codes[]
  │
  ├─ BGE-M3 임베딩 ─→ ChromaDB
  └─ kiwipiepy 토큰화 ─→ BM25 인덱스 (pickle)
```

### 4.2 데이터 스키마

**Chunk JSON (chunks.jsonl 한 줄):**
```json
{
  "id": "ch_000123",
  "text": "...청크 본문 (한국어 원문)...",
  "metadata": {
    "page_start": 88,
    "page_end": 88,
    "volume": "제1편 행위 급여·비급여 목록 및 급여 상대가치점수",
    "part": "제1부 일반원칙",
    "chapter": "제2장 ...",
    "section": "재진 진찰료",
    "codes": ["AA157", "AA100"],
    "char_count": 742
  }
}
```

## 5. 알파 개발 로드맵

총 5 마일스톤. 각 마일스톤은 별도 PR로 제출되며, 다음 마일스톤 시작 전에 기획자가 검토한다.

### M1 — 프로젝트 스캐폴드 & PDF 인제스천
- 프로젝트 디렉토리 구조 생성
- `requirements.txt`, `.env.example`, `config.py`
- `src/parser/pdf_parser.py`: PDF → `[(page_no, text), ...]`
- `src/parser/chunker.py`: 계층 인식 청커
- `scripts/ingest.py` (1단계: 청크 JSONL 생성까지)
- 단위 테스트: 청커가 헤더·코드를 올바르게 감지하는지

**완료 기준:** `python scripts/ingest.py --stage chunks` 실행 시 `data/processed/chunks.jsonl` 생성. 청크 수 / 평균 길이 / 코드 추출 수 로그.

### M2 — 인덱싱 (벡터 + BM25)
- `src/retrieval/embedder.py`: BGE-M3 sentence-transformer 래퍼
- `src/retrieval/vector_store.py`: ChromaDB PersistentClient 래퍼
- `src/retrieval/bm25.py`: rank_bm25 + kiwipiepy 토크나이저 (kiwi 실패 시 공백 분할 fallback)
- `scripts/ingest.py` (2단계: 인덱싱)

**완료 기준:** `python scripts/ingest.py --stage index` 실행으로 ChromaDB와 BM25 인덱스 생성. 샘플 질의(예: "재진 진찰료") 입력 시 retrieve 결과 5건 출력.

### M3 — 하이브리드 리트리버 + LLM 연결 + CLI
- `src/retrieval/hybrid.py`: RRF 융합
- `src/llm/ollama_client.py`: Ollama HTTP 클라이언트
- `src/llm/prompt.py`: 시스템·유저 프롬프트 템플릿
- `src/rag/pipeline.py`: end-to-end 파이프라인
- `scripts/cli.py`: 콘솔 챗 (UI 전 검증용)

**완료 기준:** `python scripts/cli.py` 실행 후 질문 입력 시 답변과 출처가 콘솔에 출력. Ollama 미실행 시 명확한 에러 메시지.

### M4 — Streamlit UI 알파
- `src/ui/streamlit_app.py`
  - `st.chat_message`로 히스토리
  - 사이드바: 모델, Top-K, 온도
  - 답변 하단 expander로 출처 청크 본문 표시
  - "대화 초기화" 버튼

**완료 기준:** `streamlit run src/ui/streamlit_app.py` 으로 챗 UI 동작. 사용자 질문 → 답변+출처 표시. 5회 연속 질문 시 히스토리 누적.

### M5 — Smoke Eval & 문서화
- `eval/smoke_qa.jsonl`: 10문항 (코드 조회 5 + 의미 검색 5)
- `scripts/eval.py`: retrieval recall@8 / 출처 페이지 정확도
- `README.md`: 셋업·실행·트러블슈팅

**완료 기준:**
- retrieval recall@8 ≥ 0.7 (정답 청크가 상위 8개 안에 포함된 비율)
- 출처 페이지 정확도 ≥ 0.6 (LLM 답변이 인용한 페이지가 정답 페이지와 일치 또는 ±1)
- README만 보고 빈 머신에서 셋업·실행 가능

## 6. 위험 및 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| 1,429p 임베딩 시간(CPU) | 인덱싱 30분~수 시간 | 1회성 작업, 진행률 로그, M2 완료 후 `data/index/` 보존 |
| Ollama 미설치/모델 미존재 | 챗 작동 불가 | README에 사전 설치 단계 명시. 클라이언트가 명확한 에러 |
| 일부 페이지 텍스트 추출 실패 (앞쪽 목차) | 검색 누락 | 알파에선 스킵 + 로그. OCR은 베타 |
| kiwipiepy wheel 누락 (희귀 OS) | BM25 미동작 | 토크나이저 어댑터 패턴, 공백 분할 fallback |
| BGE-M3 모델 다운로드 실패 (네트워크) | 임베딩 불가 | README에 huggingface 캐시 경로 명시, 사전 다운로드 안내 |
| qwen2.5-3B의 답변 품질 한계 (긴 산정지침 다단계 추론·인용 형식 준수도) | 답변 정확도/형식 일관성 저하 | M5 평가에서 페이지 정확도 < 0.6 시 베타에서 7B/8B 업그레이드. 시스템 프롬프트는 짧고 명확하게 유지하여 작은 모델 친화적으로 작성 |

## 7. 알파 → 베타 이월 항목

- **로컬 LLM 업그레이드 평가**: 알파 평가 결과에 따라 `qwen2.5:7b-instruct` 또는 `exaone3.5:7.8b-instruct` 등으로 교체 검토
- 스캔 페이지 OCR (Tesseract Korean)
- bge-reranker-v2 리랭킹
- 멀티턴 질의 재작성 (HyDE / step-back prompting)
- 코드 정확매칭 우선 라우팅
- 인덱스 버전 관리, 증분 업데이트
- 세션 영속화, 사용자별 히스토리
- Docker 패키징, 단일 명령 배포
- 답변 품질 자동 평가(LLM-as-judge)

---

## 8. 확장 계획 — M6·M7: 멀티 문서 RAG (2026-04-30 추가)

### 8.1 배경

알파 완료 후 신규 요구사항으로 다음 문서들이 추가되었다:
- **약관 PDF** (`2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf`, 172페이지): 진단코드별 보상/비보상 여부, 실손보험 보장 범위를 포함.
- **보상가이드북** (미입수, 추후 추가 예정): 수술종별(1~5종) 분류표 포함.

이 두 문서를 기존 심평원 고시와 함께 단일 RAG 파이프라인에서 검색할 수 있어야 한다.

### 8.2 핵심 요구사항 (예시 Q&A 기반)

| 질문 유형 | 참조 문서 | 예시 |
|---|---|---|
| 수술코드 조회 | 심평원 | "식도조루술 코드는?" → Q2333 (심평원 p.956) |
| 진단코드 보상 판단 | 약관 | "N39.3은 보상 가능한가?" → 질병급여/비급여/3대비급여 모두 보상 안 됨 |
| 수술코드 + 종별 판단 | 심평원 + 가이드북 | "식도조루술 코드, 해설, 1-5종?" → Q2333, 3종 해당 |

### 8.3 확장 마일스톤

**M6 — 멀티 문서 인제스천 & 청커 개선**
목표: 약관 PDF를 기존 심평원 PDF와 함께 인덱싱.
- `src/config.py`: PdfSource 데이터클래스 및 PDF_SOURCES 목록 추가
- `src/parser/chunker.py`: 문서 유형별 헤더 패턴 분기 (심평원용 편/부/장/절 vs 약관용 관/조), ICD-10 코드 패턴(`r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b"`) 추가, chunk metadata에 `doc_short`/`doc_name`/`doc_type` 필드 추가
- `scripts/ingest.py`: PDF_SOURCES 전체 반복 처리, 단일 chunks.jsonl 통합 출력
- 청크 ID 충돌 방지: `{doc_short}_ch_{번호}` 형식

**M7 — 프롬프트 개선 & Q&A 데이터셋 확장**
목표: 멀티 문서 인용 형식 및 평가 데이터 반영.
- `src/llm/prompt.py`: 복수 문서 인용 형식 `[출처: 문서명, 조문/절, p.페이지]`
- `eval/smoke_qa.jsonl`: 기존 10문항에 doc_sources 필드 추가 + 신규 5문항(약관 3 + 복합 2) 추가
- `docs/qa_reference.md` 내용 반영 (별도 파일로 관리)

### 8.4 추가 문서 등록 가이드 (보상가이드북)

보상가이드북 PDF가 준비되면 다음 절차로 등록:
1. PDF를 프로젝트 루트에 `보상가이드북.pdf`로 저장
2. `src/config.py`의 `PDF_SOURCES`에 `PdfSource(path=ROOT_DIR/"보상가이드북.pdf", doc_type="guide_book", doc_name="보상가이드북", doc_short="가이드북")` 추가
3. `python scripts/ingest.py --stage all` 재실행
