# Codex 개발자 명세서 — 보험 문서 RAG 챗봇 (Alpha)

> **이 문서는 Codex 에이전트(개발자)가 받아 구현하는 명세입니다.**
> 기획·검토는 별도 에이전트가 담당하며, 본 명세를 임의로 변경하지 마세요.
> 결정 변경이 필요한 사안이 발생하면 변경 사유와 옵션을 PR 설명에 명시하고 검토자에게 알리세요.

---

## 0. Codex에게 전달할 프롬프트 (이 섹션을 그대로 Codex에 붙여넣으세요)

```
당신은 시니어 Python 개발자입니다. 아래 명세에 따라 "보험 문서 RAG 챗봇 (Alpha)" 을 구현하세요.

원칙:
1. 명세를 임의로 확장하지 마세요. 알파 범위 외 기능(OCR, 리랭커, 멀티턴 등)은 구현하지 않습니다.
2. 마일스톤(M1→M5) 순서대로 작업하고, 각 마일스톤마다 커밋·요약을 남기세요.
3. 결정에 모호함이 있으면 명세 7장 "기본값 우선" 규칙을 따르세요. 그래도 안 되면 PR 설명에 질문을 남기고 진행하세요.
4. 모든 모듈은 단위 테스트와 함께 제출하며, 테스트 없이는 마일스톤 완료가 아닙니다.
5. 외부 네트워크가 필요한 작업(BGE-M3 모델 다운로드, Ollama 모델 pull)은 README 사전 단계로 분리하고 코드에서는 캐시 사용을 가정합니다.
6. 코드 주석과 docstring은 한국어 또는 영어 중 일관되게 사용하세요. 한국어 우선.
7. 작업 디렉토리: 이 명세 파일이 있는 프로젝트 루트.
8. 입력 PDF: 프로젝트 루트의 BZ202603053039374.pdf (이미 존재).
9. 실행 환경 가정: macOS (M4 Apple Silicon). 기본 LLM은 Ollama의 `qwen2.5:3b-instruct` (사용자가 이미 다운로드함). `OLLAMA_MODEL` 환경변수로 교체 가능하도록 하드코딩 금지.

요구되는 산출물:
- 명세 5장 "프로젝트 구조"의 모든 파일
- requirements.txt, README.md, .env.example
- pytest 테스트 (`tests/`)
- eval/smoke_qa.jsonl (10문항)

먼저 명세 전체를 읽고, M1부터 순차적으로 진행하세요. 각 마일스톤 완료 시 명세 6장 "마일스톤별 완료 기준"을 자가 검증한 결과를 함께 보고하세요.
```

---

## 1. 프로젝트 개요

1,429페이지 한국어 건강보험 고시 문서를 RAG로 검색·답변하는 Streamlit 챗봇의 알파 버전. 모든 처리는 로컬에서 수행되며, LLM은 Ollama를 통한 로컬 모델을 사용한다.

## 2. 기술 스택 (고정)

| 영역 | 라이브러리/도구 | 버전 (최소) |
|---|---|---|
| Python | python | `3.11` |
| PDF | pdfplumber, pymupdf | `0.10`, `1.24` |
| 임베딩 | sentence-transformers, FlagEmbedding(선택) | `2.7` |
| 벡터 DB | chromadb | `0.5` |
| BM25 | rank_bm25 | `0.2.2` |
| 한국어 토크나이저 | kiwipiepy | `0.17` |
| LLM 클라이언트 | requests | `2.31` |
| UI | streamlit | `1.30` |
| 환경 변수 | python-dotenv | `1.0` |
| 테스트 | pytest | `8.0` |
| 임베딩 모델 | `BAAI/bge-m3` (HuggingFace) | — |
| 기본 LLM | `qwen2.5:3b-instruct` (Ollama) — 사용자 환경(M4 Mac)에 이미 설치됨 | — |

## 3. 프로젝트 구조

```
보험 문서 RAG 챗봇/
├── BZ202603053039374.pdf            # 입력 PDF (이미 존재, 수정 금지)
├── README.md                         # M5에서 작성
├── requirements.txt
├── .env.example
├── pyproject.toml                    # (선택) 패키지 메타
├── docs/
│   ├── 01_PROJECT_PLAN.md            # (이미 존재, 참조용)
│   └── 02_CODEX_SPEC.md              # 본 문서
├── data/
│   ├── processed/
│   │   └── chunks.jsonl              # M1 산출
│   └── index/
│       ├── chroma/                   # M2 산출 (Chroma 영속 디렉토리)
│       └── bm25.pkl                  # M2 산출
├── eval/
│   └── smoke_qa.jsonl                # M5 산출
├── scripts/
│   ├── ingest.py                     # PDF → 청크 → 인덱스 (M1, M2)
│   ├── cli.py                        # 콘솔 RAG 검증 (M3)
│   └── eval.py                       # smoke 평가 (M5)
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── pdf_parser.py
│   │   └── chunker.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── embedder.py
│   │   ├── vector_store.py
│   │   ├── bm25.py
│   │   └── hybrid.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── ollama_client.py
│   │   └── prompt.py
│   ├── rag/
│   │   ├── __init__.py
│   │   └── pipeline.py
│   └── ui/
│       └── streamlit_app.py
└── tests/
    ├── __init__.py
    ├── test_chunker.py
    ├── test_bm25.py
    ├── test_hybrid.py
    └── test_pipeline.py              # 모킹 기반
```

## 4. 모듈별 명세

### 4.1 `src/config.py`

환경 변수와 상수를 한 곳에 모은다. dotenv로 `.env` 로드 시도.

```python
# 노출되어야 하는 상수
PDF_PATH: Path
CHUNKS_PATH: Path             # data/processed/chunks.jsonl
CHROMA_DIR: Path              # data/index/chroma
BM25_PATH: Path               # data/index/bm25.pkl
EMBEDDING_MODEL: str          # 기본 "BAAI/bge-m3"
OLLAMA_HOST: str              # 기본 "http://localhost:11434"
OLLAMA_MODEL: str             # 기본 "qwen2.5:3b-instruct" (사용자 M4 Mac 환경에 이미 설치됨)
TOP_K_DENSE: int = 12
TOP_K_BM25: int = 12
TOP_K_FINAL: int = 8
RRF_K: int = 60
CHUNK_TARGET_CHARS: int = 800
CHUNK_OVERLAP_CHARS: int = 100
```

### 4.2 `src/parser/pdf_parser.py`

```python
def parse_pdf(pdf_path: Path) -> list[tuple[int, str]]:
    """
    PDF를 페이지 단위로 텍스트 추출. pdfplumber 우선, 빈 결과 시 PyMuPDF로 폴백.
    Returns:
        [(page_no(1-based), text), ...]
        텍스트 추출 실패 페이지는 빈 문자열로 포함하되 로그를 남긴다.
    """
```

### 4.3 `src/parser/chunker.py`

핵심: 한국어 고시 문서의 계층(편/부/장/절) 메타데이터를 보존한다.

**헤더 정규식 (정확히 이 패턴 사용):**
- 편: `r"^\s*제\s*\d+\s*편\b.*"`
- 부: `r"^\s*제\s*\d+\s*부\b.*"`
- 장: `r"^\s*제\s*\d+\s*장\b.*"`
- 절: `r"^\s*제\s*\d+\s*절\b.*"`

**코드 정규식:**
- 알파벳+숫자 코드: `r"\b[A-Z]{1,3}\d{2,5}\b"` (예: AA157, B5070)
- 5자리 숫자 코드: `r"\b\d{5}\b"` (예: 10100)

```python
@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict  # {page_start, page_end, volume, part, chapter, section, codes, char_count}

def chunk_pages(pages: list[tuple[int, str]],
                target_chars: int = 800,
                overlap_chars: int = 100) -> list[Chunk]:
    """
    페이지를 순회하며 헤더 컨텍스트를 누적·전파한다.
    한 페이지 안에서도 절(節) 변경이 감지되면 청크를 분리한다.
    절을 만나지 못한 채 target_chars를 넘기면 슬라이딩 윈도우(overlap_chars)로 분할.
    각 청크에서 코드 패턴을 추출해 metadata.codes에 채운다.
    id는 'ch_' + zfill(6) 순번.
    """
```

**청킹 우선순위 규칙:**
1. 절(節) 단위로 자른다.
2. 절이 없거나 너무 길면 빈 줄(`\n\n`) 단위로 자른다.
3. 그래도 길면 슬라이딩 윈도우.

**메타데이터 누적 규칙:**
- 헤더가 새로 등장하면 해당 레벨과 그 하위 레벨을 갱신한다(예: 새 부(部)가 나오면 chapter, section을 None으로 리셋).
- 청크가 여러 페이지에 걸치면 `page_start`/`page_end`로 표기.

### 4.4 `src/retrieval/embedder.py`

```python
class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        # sentence-transformers SentenceTransformer 로드
        ...

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        ...

    def embed_query(self, text: str) -> np.ndarray:
        ...
```

L2 정규화된 임베딩 반환. 진행률 로그(tqdm).

### 4.5 `src/retrieval/vector_store.py`

```python
class VectorStore:
    def __init__(self, persist_dir: Path, collection_name: str = "insurance"):
        # chromadb.PersistentClient
        ...

    def upsert(self, ids: list[str], embeddings: np.ndarray,
               metadatas: list[dict], documents: list[str]) -> None: ...

    def query(self, query_embedding: np.ndarray, top_k: int) -> list[Hit]:
        # Hit = {id, score, document, metadata}
        ...
```

ChromaDB는 metadata 값으로 list를 직접 저장하지 못하므로 `codes`는 `","` 조인된 문자열로 저장하고, 조회 시 다시 split.

### 4.6 `src/retrieval/bm25.py`

```python
class BM25Index:
    def __init__(self): ...

    def build(self, ids: list[str], texts: list[str]) -> None: ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> "BM25Index": ...

    def query(self, text: str, top_k: int) -> list[Hit]: ...
```

토크나이저 어댑터:
```python
def tokenize(text: str) -> list[str]:
    """
    1순위: kiwipiepy로 형태소 분석 → 명사/동사/외국어/한자 토큰.
    2순위(import 실패 시): 정규식 기반 단순 토큰화 (공백 + 한영숫자).
    """
```

### 4.7 `src/retrieval/hybrid.py`

```python
def rrf_fuse(dense_hits: list[Hit], bm25_hits: list[Hit],
             top_k: int = 8, rrf_k: int = 60) -> list[Hit]:
    """
    Reciprocal Rank Fusion: score(d) = sum(1 / (rrf_k + rank_i(d)))
    동일 id는 합산. score 기준 내림차순 top_k 반환.
    """
```

### 4.8 `src/llm/ollama_client.py`

```python
class OllamaClient:
    def __init__(self, host: str, model: str): ...

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.2, num_ctx: int = 8192) -> str:
        # POST {host}/api/generate (stream=False)
        # 연결 실패 시 RuntimeError("Ollama 서버에 연결할 수 없습니다 ...")
        ...

    def health(self) -> bool:
        # GET {host}/api/tags
        ...
```

### 4.9 `src/llm/prompt.py`

> **3B 모델 친화 원칙**: 시스템 프롬프트는 짧고 규칙은 5개 이내로 유지한다. 길고 추상적인 지시는 작은 모델에서 준수도가 떨어지므로, 규칙을 늘리지 말 것. 예시(few-shot)는 알파에서 사용하지 않는다(컨텍스트 토큰 절약 + 단순성).

```python
SYSTEM_PROMPT = """당신은 대한민국 건강보험 고시 문서를 참고해 보험사 직원의 질문에 답하는 어시스턴트입니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 사용한 출처를 [출처: 편/부/장/절, p.페이지] 형식으로 나열하세요.
5. 한국어로 간결하고 정확하게 답하세요."""

def build_user_prompt(question: str, chunks: list[Chunk]) -> str:
    """
    [컨텍스트 N] 헤더와 함께 청크를 순서대로 나열, 마지막에 [질문] 표시.
    각 컨텍스트 헤더에 청크의 편/부/장/절/page를 포함.
    """
```

### 4.10 `src/rag/pipeline.py`

```python
@dataclass
class RagAnswer:
    answer: str
    chunks: list[Chunk]      # 인용된 청크들
    timing: dict             # {retrieve_ms, llm_ms, total_ms}

class RagPipeline:
    def __init__(self, embedder, vector_store, bm25, llm,
                 top_k_dense=12, top_k_bm25=12, top_k_final=8): ...

    def answer(self, question: str) -> RagAnswer:
        # 1) embed query
        # 2) dense + bm25 검색
        # 3) RRF 융합 → top_k_final
        # 4) 프롬프트 조립
        # 5) Ollama 호출
        # 6) 결과 반환
        ...
```

### 4.11 `src/ui/streamlit_app.py`

요구 동작:
- 페이지 타이틀: "보험 고시 문서 RAG 챗봇 (Alpha)"
- 사이드바
  - 모델 선택(Selectbox, 기본값=`OLLAMA_MODEL`)
  - Top-K(Slider 4–12, 기본 8)
  - 온도(Slider 0.0–0.7, 기본 0.2)
  - "대화 초기화" 버튼
- 본문
  - `st.chat_message`로 역할별 말풍선
  - 입력은 `st.chat_input`
  - 답변 메시지 하단 `st.expander("출처 보기")` 안에 청크 별 메타데이터 + 본문 표시
- 첫 진입 시 인덱스 로드(캐시: `@st.cache_resource`로 파이프라인 1회 초기화)
- Ollama 미연결 시 명확한 에러 표시

### 4.12 `scripts/ingest.py`

```bash
python scripts/ingest.py --stage all   # chunks + index
python scripts/ingest.py --stage chunks
python scripts/ingest.py --stage index
```

각 단계 시작/완료 로그와 통계(청크 수, 평균 길이, 코드 추출 수, 임베딩 시간) 출력.

### 4.13 `scripts/cli.py`

콘솔 챗 루프. 종료어: `:q`. 답변 + 출처(페이지/섹션) 출력.

### 4.14 `scripts/eval.py`

`eval/smoke_qa.jsonl` 읽어 각 항목에 대해 retrieval 결과·답변을 생성하고 다음 지표 출력:
- retrieval recall@8 (정답 페이지가 top-8 청크 중 하나의 page 범위 안에 포함된 비율)
- 페이지 정확도 (LLM 답변 텍스트에 정답 페이지 번호가 등장한 비율)

## 5. 데이터 스키마

### 5.1 `chunks.jsonl` (한 줄 = 한 청크)

```json
{
  "id": "ch_000123",
  "text": "...",
  "metadata": {
    "page_start": 88,
    "page_end": 88,
    "volume": "제1편 ...",
    "part": "제1부 ...",
    "chapter": "제2장 ...",
    "section": "재진 진찰료",
    "codes": ["AA157", "AA100"],
    "char_count": 742
  }
}
```

### 5.2 `eval/smoke_qa.jsonl`

```json
{"question": "...", "expected_pages": [88, 89], "expected_codes": ["AA157"], "type": "code|semantic"}
```

10문항 (코드 조회 5 + 의미 검색 5). Codex가 PDF 스캔 후 명백한 사실 위주로 작성. 작성 시 페이지 번호는 PDF 인쇄 페이지(예: p.88) 기준이 아니라 PDF 파일의 1-based 페이지 인덱스를 사용한다(혼동 방지).

## 6. 마일스톤별 완료 기준

| M | 자가 검증 명령 | 통과 조건 |
|---|---|---|
| M1 | `pytest tests/test_chunker.py && python scripts/ingest.py --stage chunks` | 테스트 통과, JSONL 생성, 청크 1,000개 이상, 코드 1개 이상 추출된 청크 비율 > 5% |
| M2 | `python scripts/ingest.py --stage index` | Chroma·BM25 산출물 존재, 임의 질의 5건 retrieve OK |
| M3 | `python scripts/cli.py` 후 5문항 입력 | 답변·출처 정상 출력. Ollama 미실행 시 명확한 에러 |
| M4 | `streamlit run src/ui/streamlit_app.py` | UI 정상 동작, 출처 expander 표시, 대화 초기화 버튼 동작 |
| M5 | `python scripts/eval.py` + README 검증 | recall@8 ≥ 0.7, 페이지 정확도 ≥ 0.6, README 셋업 가이드 완비 |

## 7. 기본값 우선 규칙 (모호함 해결)

명세에 없는 사항은 다음 순서로 해결:

1. **단순한 쪽 우선** — 추가 라이브러리 없이 구현할 수 있다면 그쪽을 택한다.
2. **알파 범위 외는 구현하지 않는다** — 의심스러우면 베타로 미룬다.
3. **에러는 사용자가 읽을 수 있게** — 한국어 에러 메시지, 다음 단계 힌트 포함.
4. **외부 네트워크 호출은 README 사전 단계로** — 코드는 이미 받았다고 가정.
5. **로그는 표준출력** — 파일 로깅은 알파 범위 외.

## 8. README.md 필수 섹션 (M5)

1. 프로젝트 소개 (3줄)
2. 사전 요구사항
   - Python 3.11
   - Ollama 설치 (macOS Apple Silicon 가정)
   - 기본 모델: `ollama pull qwen2.5:3b-instruct` (이미 받았다면 스킵)
   - `ollama serve` 또는 Ollama 데스크톱 앱 실행
   - 다른 모델 사용 시: `.env` 의 `OLLAMA_MODEL` 변경 (예: `qwen2.5:7b-instruct`)
3. 셋업: venv, requirements.txt, 환경 변수 (`.env.example` 복사)
4. 인덱싱: `python scripts/ingest.py --stage all` (M4 Mac CPU 기준 BGE-M3 임베딩 예상 소요 시간 명시)
5. 실행: CLI / Streamlit
6. 트러블슈팅: Ollama 미연결, 모델 미존재(태그명 오타 포함), kiwipiepy 설치 실패, BGE-M3 다운로드 실패
7. 평가: `python scripts/eval.py`
8. 알파 범위 외 / 베타 이월 항목 (LLM 7B 업그레이드 평가 포함)

## 9. 테스트 가이드라인

- 모든 테스트는 PDF 없이 동작해야 한다(샘플 텍스트 fixture 사용).
- LLM 호출 테스트는 `OllamaClient.generate`을 mock으로 처리.
- 외부 모델 다운로드는 테스트에서 발생하지 않아야 한다(Embedder 테스트는 dummy 임베딩으로 우회).

## 10. 제출 시 보고서 양식 (각 마일스톤 PR 설명)

```
## M{N} 완료 보고
- 변경 파일: ...
- 자가 검증 결과:
  - [통과 조건 1]: 결과
  - [통과 조건 2]: 결과
- 알파 명세 외 추가/생략 사항: ...
- 다음 마일스톤 진행 전 검토자 확인 필요 항목: ...
```
