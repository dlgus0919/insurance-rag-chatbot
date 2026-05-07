# Codex 개발자 명세 — M11 (UI 개선 + 속도 최적화)

> **문서 유형:** Codex 전달용 개발자 명세
> **작성일:** 2026-05-04
> **기반 상태:** M10 완료 (recall@8=1.000, page_accuracy=1.000, Q1-Q5 5/5 PASS)
> **목표:** 사용자 경험 개선 및 실무 투입 전 완성도 향상

---

## 섹션 0 — Codex에게 전달할 프롬프트 (복사 붙여넣기용)

```
당신은 시니어 Python 개발자입니다.
"보험 문서 RAG 챗봇" 프로젝트 M10이 완료된 상태에서 아래 4가지 UI·성능 개선 사항을
구현해주세요. 각 항목은 독립적으로 구현·테스트 가능합니다.

---

## 요구사항 1 — Streamlit 모델 선택 드롭다운 개선

### 현재 상태
`src/ui/streamlit_app.py` 80번째 줄:
```python
model = st.selectbox("모델", [config.OLLAMA_MODEL], index=0)
```
단일 모델만 표시됨. 사용자가 다른 모델로 전환 불가.

### 구현 내용

**1-A. 사용 가능한 모델 동적 조회**

`src/llm/ollama_client.py`에 설치된 모델 목록 조회 메서드를 추가하세요:

```python
def list_models(self) -> list[str]:
    """Ollama에 설치된 모델 이름 목록을 반환한다. 실패 시 빈 리스트."""
    try:
        resp = requests.get(urljoin(self.host, "api/tags"), timeout=5)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except requests.RequestException:
        return []
```

**1-B. `config.py`에 권장 모델 화이트리스트 추가**

```python
# 모델 선택 UI에 표시할 권장 모델 목록 (설치 여부와 무관하게 정의)
OLLAMA_CANDIDATE_MODELS: list[str] = [
    "exaone3.5:7.8b-instruct",   # 한국어 특화, 권장
    "qwen2.5:7b-instruct",        # 범용 7B
    "qwen2.5:14b-instruct",       # 고성능
    "gemma3:4b",                  # 기본값 (빠름)
    "gemma3:1b",                  # 초경량
]
```

**1-C. `streamlit_app.py` 사이드바 수정**

```python
@st.cache_data(ttl=30)  # 30초 캐시로 잦은 API 호출 방지
def _get_available_models() -> list[str]:
    """Ollama에 설치된 모델 중 권장 목록에 포함된 것만 반환."""
    import requests
    from urllib.parse import urljoin
    try:
        resp = requests.get(urljoin(config.OLLAMA_HOST, "api/tags"), timeout=3)
        installed = {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        installed = set()

    # 권장 목록 중 설치된 것 + 현재 .env 설정 모델을 항상 포함
    candidates = [m for m in config.OLLAMA_CANDIDATE_MODELS if m in installed]
    if config.OLLAMA_MODEL not in candidates:
        candidates.insert(0, config.OLLAMA_MODEL)
    return candidates if candidates else [config.OLLAMA_MODEL]


# 사이드바에서 (기존 selectbox 교체)
available_models = _get_available_models()
default_idx = available_models.index(config.OLLAMA_MODEL) if config.OLLAMA_MODEL in available_models else 0
model = st.selectbox(
    "LLM 모델",
    available_models,
    index=default_idx,
    help="exaone3.5:7.8b-instruct 권장 (한국어 처리 최적화)"
)
```

**1-D. 모델 미설치 안내**

선택한 모델이 실제로 설치되지 않은 경우 에러 메시지에 설치 명령을 포함하세요:

```python
# load_pipeline 에서 OllamaClient.health() 실패 시 에러 메시지:
raise RuntimeError(
    f"Ollama 서버에 연결할 수 없거나 모델 '{model}'이 설치되지 않았습니다.\n"
    f"설치 명령: `ollama pull {model}`\n"
    "또는 Ollama 데스크톱 앱을 실행하세요."
)
```

---

## 요구사항 2 — 속도 최적화 (캐시 분리)

### 현재 문제
`load_pipeline(model, top_k)`가 `@st.cache_resource`로 캐시되어 있으나,
`top_k` 슬라이더를 조작할 때마다 embedder·vector_store·bm25·reranker 전체가
재로드됩니다. 이 컴포넌트들은 model이나 top_k와 무관하게 항상 동일합니다.

### 구현 내용

`streamlit_app.py`의 `load_pipeline` 함수를 아래와 같이 3단계로 분리하세요:

```python
@st.cache_resource
def _load_heavy_components():
    """임베더·벡터스토어·BM25·Reranker를 한 번만 로드한다 (수분 소요)."""
    from src.retrieval.embedder import Embedder
    from src.retrieval.vector_store import VectorStore
    from src.retrieval.bm25 import BM25Index
    from src.retrieval.reranker import build_reranker

    if not config.BM25_PATH.exists():
        raise RuntimeError(
            "BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요."
        )

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, vector_store, bm25, reranker


@st.cache_resource
def _load_llm(model: str):
    """선택된 모델 전용 OllamaClient를 생성한다 (모델별 캐시)."""
    llm = OllamaClient(config.OLLAMA_HOST, model)
    if not llm.health():
        raise RuntimeError(
            f"Ollama 서버에 연결할 수 없거나 모델 '{model}'이 설치되지 않았습니다.\n"
            f"설치 명령: `ollama pull {model}`"
        )
    return llm


def _get_pipeline(model: str, top_k: int) -> RagPipeline:
    """캐시된 컴포넌트로 RagPipeline 객체를 조합한다 (캐시 없음, 즉시 반환)."""
    embedder, vector_store, bm25, reranker = _load_heavy_components()
    llm = _load_llm(model)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=top_k,
        rrf_k=config.RRF_K,
        reranker=reranker,
    )
```

기존 `load_pipeline` 호출부를 모두 `_get_pipeline(model, top_k)`로 교체하세요.

**효과:**
- top_k 슬라이더 변경 → 재로드 없음 (RagPipeline 객체만 재조합, ~0ms)
- 모델 변경 → LLM 클라이언트만 교체 (embedder·BM25 재로드 없음)
- 최초 기동 시 heavy 로드 1회만 수행 후 영구 캐시

### 추가 최적화: LLM 스트리밍

`OllamaClient`에 스트리밍 생성 메서드를 추가하세요:

```python
def generate_stream(
    self, prompt: str, system: str = "", temperature: float = 0.2
):
    """토큰을 스트리밍으로 yield한다. Streamlit st.write_stream()에 사용."""
    payload = {
        "model": self.model,
        "prompt": prompt,
        "system": system,
        "stream": True,
        "options": {"temperature": temperature, "num_ctx": self.num_ctx},
    }
    try:
        with requests.post(
            urljoin(self.host, "api/generate"),
            json=payload,
            stream=True,
            timeout=180,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                import json as _json
                data = _json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    break
    except requests.RequestException as exc:
        raise RuntimeError("Ollama 서버에 연결할 수 없습니다.") from exc
```

`streamlit_app.py`에서 스트리밍을 사용하여 답변 표시:

```python
# 기존 (blocking)
with st.spinner("답변 생성 중"):
    result = pipeline.answer(question, temperature=temperature)
st.markdown(result.answer)

# 변경 후 (streaming)
import time as _time

t_start = _time.perf_counter()

# 검색 단계 (blocking, 빠름)
with st.spinner("관련 문서 검색 중..."):
    hits = pipeline.retrieve_hits(question)
    chunks = [pipeline._hit_to_chunk(hit) for hit in hits]  # 또는 동등 로직

t_retrieve = _time.perf_counter()

# 프롬프트 빌드
from src.llm.prompt import SYSTEM_PROMPT, build_user_prompt, append_retrieved_source_citations
prompt = build_user_prompt(question, chunks)

# LLM 스트리밍 (토큰 실시간 표시)
answer_placeholder = st.empty()
answer_tokens: list[str] = []
for token in pipeline.llm.generate_stream(prompt, system=SYSTEM_PROMPT, temperature=temperature):
    answer_tokens.append(token)
    answer_placeholder.markdown("".join(answer_tokens) + "▌")  # 커서 표시

full_answer = "".join(answer_tokens)
full_answer = append_retrieved_source_citations(full_answer, chunks)
answer_placeholder.markdown(full_answer)

t_llm = _time.perf_counter()

timing = {
    "retrieve_ms": (t_retrieve - t_start) * 1000,
    "llm_ms": (t_llm - t_retrieve) * 1000,
    "total_ms": (t_llm - t_start) * 1000,
}
```

> ⚠️ 스트리밍을 사용할 경우 `pipeline.answer()`를 직접 호출하지 않고
> retrieve → prompt → stream 순서로 분리해서 호출해야 합니다.
> `RagPipeline`에 `retrieve_hits()` 메서드가 이미 있으므로 이를 활용하세요.
> `_hit_to_chunk()`는 파이프라인 내부 함수이므로 `prompt.py`의 `build_user_prompt`에
> 직접 `Hit` 리스트를 받아 처리할 수 있게 오버로드하거나, 모듈 레벨로 분리하세요.

---

## 요구사항 3 — 출처 표시: 원본 PDF 파일명 + 페이지

### 현재 상태
- expander에서 `chunk.id | 조문계층 | p.X` 형식으로 표시
- chunk.id 예: `심평원_ch_000915`, `약관_ch_002344`
- 사용자가 실제 PDF 파일명과 페이지를 바로 알 수 없음

### 구현 내용 A — 청크 메타데이터에 pdf_filename 추가 (재인덱싱 필요)

**`src/parser/chunker.py`** — `_make_chunk()` 또는 동등 함수에서 `pdf_filename` 추가:

```python
# PdfSource 정보가 전달될 때 (doc_source 인자가 있을 때)
metadata["pdf_filename"] = doc_source.path.name  # 예: "BZ202603053039374.pdf"
```

**`scripts/ingest.py`** — 청크 저장 시 `pdf_filename`이 포함되도록 확인.

**재인덱싱 필요:**
```bash
python scripts/ingest.py --stage all
```
재인덱싱 후 청크 수는 기존 2,670개와 동일해야 합니다.

### 구현 내용 B — streamlit_app.py 출처 표시 함수 교체

`_source_title()` 함수를 아래와 같이 교체하세요:

```python
# config.py의 PDF_SOURCES에서 doc_short → 파일명 맵 생성
_DOC_SHORT_TO_FILENAME: dict[str, str] = {
    src.doc_short: src.path.name for src in config.PDF_SOURCES
}


def _source_title(chunk) -> str:
    metadata = chunk.metadata
    doc_short = metadata.get("doc_short", "")

    # pdf_filename이 메타데이터에 있으면 사용, 없으면 config 맵에서 조회
    filename = metadata.get("pdf_filename") or _DOC_SHORT_TO_FILENAME.get(doc_short, "")

    start = metadata.get("page_start")
    end = metadata.get("page_end")
    page_str = f"p.{start}" if (start == end or end is None) else f"p.{start}~{end}"

    hierarchy = " > ".join(
        str(v)
        for v in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if v
    )

    # 표시 형식: [약관] 2.약관_신한...pdf | p.38~40 | 제3조(보장종목별 보상내용)
    parts = [f"[{doc_short}]" if doc_short else "", filename, page_str]
    header = " | ".join(p for p in parts if p)
    if hierarchy:
        header += f"\n{hierarchy}"
    return header
```

`render_sources()` 함수에서 제목과 원문을 구조화하여 표시:

```python
def render_sources(chunks, timing: dict | None = None) -> None:
    with st.expander("📄 출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            title = _source_title(chunk)
            st.markdown(f"**{index}. {title}**")
            st.text(chunk.text[:500] + ("..." if len(chunk.text) > 500 else ""))
            st.divider()
```

> 원문 청크가 매우 긴 경우 500자로 잘라 가독성을 높입니다.
> 전체 내용은 필요 시 별도 UI 요소로 확장할 수 있습니다.

---

## 요구사항 4 — 응답 생성 시간 표시

### 현재 상태
`RagAnswer.timing` 딕셔너리가 이미 구현되어 있고 `st.session_state.messages`에도
저장되지만 UI에 표시하는 코드가 없음.

```python
timing={
    "retrieve_ms": retrieve_ms,
    "llm_ms": llm_ms,
    "total_ms": total_ms,
}
```

### 구현 내용

**신규 답변 표시 시 (채팅창에서 실시간)**:

```python
# st.markdown(result.answer) 바로 다음에 추가
t = result.timing
st.caption(
    f"⏱ 검색 {t['retrieve_ms']:.0f}ms · 생성 {t['llm_ms']:.0f}ms · "
    f"합계 {t['total_ms'] / 1000:.1f}초"
)
```

**히스토리 메시지 재표시 시 (이전 대화)**:

```python
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            if message.get("chunks"):
                render_sources(message["chunks"])
            if message.get("timing"):
                t = message["timing"]
                st.caption(
                    f"⏱ 검색 {t['retrieve_ms']:.0f}ms · 생성 {t['llm_ms']:.0f}ms · "
                    f"합계 {t['total_ms'] / 1000:.1f}초"
                )
```

스트리밍 방식으로 전환한 경우:
- `retrieve_ms`: 검색 완료 시점에 측정 가능
- `llm_ms`: 스트리밍 첫 토큰~마지막 토큰 시간
- `total_ms`: 전체 elapsed

스트리밍 완료 후 `st.caption()`으로 표시하세요.

---

## 섹션 1 — 파일별 변경 요약

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `src/config.py` | 수정 | `OLLAMA_CANDIDATE_MODELS` 리스트 추가 |
| `src/llm/ollama_client.py` | 수정 | `list_models()`, `generate_stream()` 메서드 추가 |
| `src/parser/chunker.py` | 수정 | `pdf_filename` 메타데이터 추가 |
| `src/ui/streamlit_app.py` | 수정 | 캐시 분리, 모델 선택, 출처 표시, 시간 표시, 스트리밍 |
| `scripts/ingest.py` | 확인 | `pdf_filename`이 청크에 포함되는지 검증 |

---

## 섹션 2 — 구현 순서

```
M11-1 (캐시 분리)   → M11-2 (모델 선택)  → M11-3 (출처 표시 개선 + 재인덱싱)
                                         → M11-4 (시간 표시)
                                         → M11-5 (스트리밍, 선택사항)
```

- M11-1은 다른 모든 작업의 선행 조건입니다. 캐시 분리 없이 모델 선택을 구현하면
  모델 변경 시 불필요한 전체 재로드가 발생합니다.
- M11-3의 재인덱싱은 `pdf_filename` 메타데이터를 위한 것으로,
  재인덱싱 전에도 config 맵 fallback으로 동작합니다.
- M11-5 스트리밍은 선택사항이나 7B+ 모델 사용 시 UX가 크게 향상됩니다.

---

## 섹션 3 — 완료 검증

```bash
# 1. pytest 통과 확인
pytest

# 2. 재인덱싱 (청킹 메타데이터 변경분 반영)
python scripts/ingest.py --stage all

# 3. eval.py 결과가 기존과 동일한지 확인
RERANKER_ENABLED=false python scripts/eval.py
# 기대: recall@8=1.000, page_accuracy=1.000

# 4. Streamlit 실행 및 수동 확인
streamlit run src/ui/streamlit_app.py
```

**수동 확인 체크리스트:**
- [ ] 사이드바 모델 드롭다운에 설치된 모델이 표시된다
- [ ] 모델 변경 시 스피너 없이 즉시 전환된다 (heavy 컴포넌트 재로드 없음)
- [ ] Top-K 슬라이더 변경 시 재로드 없이 즉시 반영된다
- [ ] 출처 보기에 `[심평원] BZ202603053039374.pdf | p.101` 형식이 표시된다
- [ ] 각 답변 하단에 `⏱ 검색 XXXms · 생성 Xs` 형식으로 시간이 표시된다

---

## 섹션 4 — 사용자가 직접 해야 하는 작업 (Codex 불가)

> 아래 항목은 로컬 Ollama 환경에서 직접 수행해야 합니다.

1. **exaone3.5:7.8b-instruct 모델 다운로드** (약 5GB, 최초 1회):
   ```bash
   ollama pull exaone3.5:7.8b-instruct
   ```
   다운로드 완료 후 `ollama list`로 확인하세요.

2. **Streamlit 재기동**: 코드 변경 후 서버를 재시작해야 적용됩니다.

3. **재인덱싱 실행** (M11-3 완료 후):
   ```bash
   python scripts/ingest.py --stage all
   ```

---

## 섹션 5 — Codex 완료 보고서 형식

```
## M11 완료 보고

### 변경된 파일
- [파일 경로]: [변경 내용]

### 구현된 기능
- [ ] 모델 선택 드롭다운 (동적 탐지)
- [ ] 캐시 분리 (heavy / LLM)
- [ ] 출처 표시 개선 (PDF 파일명 + 페이지)
- [ ] 응답 시간 표시
- [ ] LLM 스트리밍 (선택 구현 여부 명시)

### eval.py 결과 (재인덱싱 후)
recall@8: X.XXX / page_accuracy: X.XXX

### 수동 확인 결과
[체크리스트 항목별 결과]

### 이슈 및 특이사항
[없으면 "없음"]
```
```

---

*이 명세는 기획자가 현재 구현 코드(`src/ui/streamlit_app.py`, `src/llm/ollama_client.py`, `src/rag/pipeline.py`, `src/config.py`)를 검토한 후 작성하였습니다.*
