# 보험 챗봇 수정 기술 명세서 (v3)

> 작성일: 2026-04-30  
> 버전: v3 (실제 코드 구조 기반 — Codex 전달용)  
> 목적: 현재 구현된 코드를 수정하여 4가지 요구사항을 반영한다.

---

## 1. 현재 프로젝트 구조 (실제)

```
로컬챗봇/
├── src/
│   ├── app.py                  # Streamlit UI
│   ├── config.py               # 환경설정 (Settings 데이터클래스)
│   ├── llm/
│   │   └── client.py           # LLM 클라이언트 (OpenAICompatibleClient, MockLLMClient)
│   ├── chat/
│   │   └── engine.py           # RAG 엔진 (RagEngine)
│   ├── ingest/
│   │   ├── build_index.py      # ChromaDB 인덱싱
│   │   ├── chunker.py          # PDF 텍스트 청킹
│   │   └── pdf_parser.py       # PDF 파싱
│   └── retrieval/
│       ├── retriever.py        # ChromaDB 검색
│       └── prompts.py          # 프롬프트 템플릿
├── scripts/
│   └── 01_ingest.py            # PDF 인덱싱 실행 스크립트
├── data/
│   ├── raw/                    # PDF 원본 파일 위치
│   └── processed/
│       └── chunks.jsonl        # 청킹 결과 캐시
├── chroma_db/                  # 벡터 DB 저장소
└── .env                        # 환경변수 (신규 생성 필요)
```

---

## 2. 요구사항 및 수정 대상 파일 정리

| # | 요구사항 | 수정 대상 파일 | 현재 상태 |
|---|----------|---------------|-----------|
| 1 | Qwen2.5:7b 로컬 모델 사용 | `src/config.py`, `src/llm/client.py` | vllm 서버 + 14B 모델로 설정됨 |
| 2 | LLM 서버 없이 Ollama로 로컬 실행 | `src/llm/client.py`, `src/config.py` | OpenAI 호환 서버 방식만 구현됨 (Mock 응답 출력 중) |
| 3 | 신한 약관 PDF RAG 추가 | `src/app.py`, `scripts/01_ingest.py` | 심평원 PDF 파일명 하드코딩됨 |
| 4 | 질문 예시에 맞는 답변 품질 확보 | `src/retrieval/prompts.py` | 프롬프트 미확인 → 확인 후 보완 필요 |

---

## 3. 수정 명세 (파일별 상세)

---

### 3.1 `src/config.py` — LLM 설정 변경

**현재 문제:**
```python
llm_backend: str = os.getenv("LLM_BACKEND", "vllm")          # vllm 서버 방식
llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
llm_model: str = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")  # 14B 대형 모델
```

**수정 방향:**
- 기본값을 ollama 방식으로 변경
- `.env` 파일로 오버라이드 가능하도록 유지

```python
llm_backend: str = os.getenv("LLM_BACKEND", "ollama")
llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")
llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b")
llm_api_key: str = os.getenv("LLM_API_KEY", "ollama")
```

---

### 3.2 `src/llm/client.py` — Ollama 클라이언트 추가

**현재 문제:**
- `OpenAICompatibleClient`와 `MockLLMClient` 2종류만 존재
- `create_llm_client()`가 `mock` 또는 `OpenAICompatibleClient` 중 하나만 반환
- Ollama 전용 클라이언트 없음
- 현재 화면에 "테스트용 mock 응답입니다. 실제 운영 답변은 로컬 LLM 서버 연결 후 생성됩니다." 가 출력되는 원인

**수정 방향:**
- `OllamaClient` 클래스 신규 추가
- `create_llm_client()` 함수에서 `llm_backend == "ollama"` 일 때 `OllamaClient` 반환하도록 수정

```python
# 추가할 클래스
class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str = settings.llm_model,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        import ollama as ollama_sdk
        self.ollama = ollama_sdk
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        response = self.ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": self.temperature, "num_predict": self.max_tokens},
        )
        return response["message"]["content"]

    def stream(self, prompt: str) -> Iterator[str]:
        stream = self.ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": self.temperature, "num_predict": self.max_tokens},
            stream=True,
        )
        for chunk in stream:
            delta = chunk["message"]["content"]
            if delta:
                yield delta


# 수정할 함수
def create_llm_client() -> LLMClient:
    backend = settings.llm_backend.lower()
    if backend == "mock":
        return MockLLMClient()
    if backend == "ollama":
        return OllamaClient()
    return OpenAICompatibleClient()
```

**추가 설치 패키지:**
```bash
pip install ollama
```

---

### 3.3 `src/app.py` — UI 수정 2가지

#### 수정 1: 사이드바 모델 선택 목록 변경

**현재 문제:**
```python
model = st.selectbox("모델", ["Qwen/Qwen2.5-14B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"], index=0)
```
vllm 서버용 모델명으로 하드코딩되어 있음. 선택해도 실제 동작에 반영되지 않음.

**수정 방향:**
```python
model = st.selectbox("모델", ["qwen2.5:7b", "qwen2.5:3b"], index=0)
```

#### 수정 2: index_info() 함수 — 다중 PDF 지원

**현재 문제:**
```python
pdf = ROOT_DIR / "data" / "raw" / "BZ202603053039374.pdf"  # 심평원 파일명 하드코딩
```

**수정 방향:**
- `data/raw/` 폴더의 모든 PDF 파일명을 동적으로 읽어서 표시
```python
def index_info() -> dict:
    chunks = ROOT_DIR / "data" / "processed" / "chunks.jsonl"
    raw_dir = ROOT_DIR / "data" / "raw"
    pdf_files = [p.name for p in raw_dir.glob("*.pdf")] if raw_dir.exists() else []
    updated = datetime.fromtimestamp(chunks.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if chunks.exists() else "미생성"
    return {"files": pdf_files, "chunks": chunks, "updated": updated}
```

---

### 3.4 `src/retrieval/prompts.py` — 답변 품질 향상

**현재 상태:** 파일 내용 미확인. 개발자가 아래 요구사항을 반영하여 프롬프트를 검토·수정한다.

**요구사항:**
답변 시 아래 3가지 예시와 같은 형식으로 출력되어야 한다.

| 질문 유형 | 답변 형식 예시 |
|-----------|---------------|
| 수술코드 조회 | "식도조루술의 코드는 Q2333 입니다.(심평원 PDF 956p)" |
| 약관 보상 여부 | "N39.3 진단은 질병급여(약관 PDF 37p), 질병비급여(약관 PDF 79p), 3대비급여(약관 PDF 81p)에서 보상하지 않는 사항으로 명시되어 있습니다." |
| 복합 조회 | "식도조루술의 코드는 Q2333 이며,(심평원 PDF 956p) 식도에 음식을 몸안으로 넣어주는 통로를 마련해주는 수술방법을 말합니다. 1-5종 수술비에서 3종에 해당합니다.(보상가이드북 107p)" |

**SYSTEM_PROMPT에 반드시 포함되어야 할 지침:**
```
1. 답변 근거가 되는 출처(문서명, 페이지)를 반드시 괄호 안에 명시할 것
   예: (심평원 PDF 956p), (약관 PDF 37p)
2. 여러 문서에서 근거를 찾은 경우 각각 출처를 표기할 것
3. 참고 문서에 없는 내용은 "해당 문서에서 관련 내용을 찾을 수 없습니다"라고 답변할 것
4. 추측하거나 일반 의료 지식으로 답변하지 말 것
```

---

## 4. `.env` 파일 생성 (개발자가 직접 생성)

프로젝트 루트(`로컬챗봇/`)에 `.env` 파일을 아래 내용으로 생성한다.

```env
LLM_BACKEND=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama
EMBEDDING_MODEL=BAAI/bge-m3
USE_RERANKER=false
```

> `USE_RERANKER=false` 로 설정하는 이유: 리랭커 모델(bge-reranker-v2-m3)은 맥북 에어에서 추가 메모리를 사용하므로 비활성화한다.

---

## 5. 수정 후 실행 방법

```bash
# 1. ollama 패키지 설치 (없는 경우)
pip install ollama

# 2. Ollama 서비스 실행 (터미널 별도 창 또는 백그라운드)
ollama serve

# 3. Streamlit 앱 실행
cd /Users/dahyun/Desktop/신한ez손해보험/로컬챗봇
streamlit run src/app.py
```

---

## 6. 수정 후 검증 테스트

앱 실행 후 아래 3가지 질문으로 정상 동작을 확인한다.

| 질문 | 참조 문서 | 정상 답변 기준 |
|------|-----------|---------------|
| 식도조루술의 코드를 알려줘 | 심평원 PDF | Q2333, 페이지 번호 포함 |
| N39.3 진단이 실손 약관에서 보상 가능한지 알려줘 | 신한 약관 PDF | 보상 불가 조항 + 페이지 번호 포함 |
| 식도조루술의 수술코드, 수술해설과 1-5종 해당여부를 알려줘 | 심평원 PDF | Q2333 + 수술 설명 + 페이지 번호 포함 |

> Mock 응답("테스트용 mock 응답입니다...")이 더 이상 출력되지 않아야 한다.

---

## 7. 수정 불필요 파일 (현재 정상)

| 파일 | 상태 |
|------|------|
| `src/ingest/chunker.py` | chunk_id 중복 버그 수정 완료 |
| `src/ingest/build_index.py` | 정상 |
| `scripts/01_ingest.py` | 정상 |
| `chroma_db/` | 18627개 청크 인덱싱 완료 (심평원 18232 + 신한 약관 395) |
