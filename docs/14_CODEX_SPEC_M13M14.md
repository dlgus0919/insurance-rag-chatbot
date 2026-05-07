# Codex 개발자 명세 — M13 · M14 (카테고리 필터 · 검색 모드 · PDF 미리보기)

> **작성:** 기획자
> **작성일:** 2026-05-04
> **기반 상태:** M12 완료 (인증·로깅·내보내기 적용된 Streamlit 알파)
> **참고:** [13_IMPROVEMENT_PLAN_v2.md](./13_IMPROVEMENT_PLAN_v2.md)

---

## 섹션 0 — Codex에게 전달할 프롬프트 (복사 붙여넣기용)

```
당신은 시니어 Python 개발자입니다.
"보험 문서 RAG 챗봇" 프로젝트는 현재 M12까지 완료되어 사내 임직원용으로 동작하는 Streamlit 챗봇 상태입니다.
다음 두 마일스톤(M13, M14)을 본 명세에 따라 순서대로 구현하세요.

원칙:
1. 명세를 임의로 확장하지 마세요. 명세 외 항목(예: M15의 top-k 자동, 멀티페이지 PDF 점프)은 구현 금지.
2. M13 → M14 순서로 작업하고, 각 마일스톤 완료 시 자가 검증 결과를 PR에 보고하세요.
3. 기존 동작(일반 질의 모드, 인증, 내보내기, 로깅)은 절대 깨지면 안 됩니다.
   - 회귀 테스트: pytest 전체 통과 + 일반 모드 질의 1회 정상 응답 확인.
4. 모호함 해결 순서: (a) 본 명세, (b) 기존 코드 컨벤션 따라가기, (c) 가장 단순한 해법 선택.
5. 각 신규/수정 모듈은 단위 테스트와 함께 제출. UI 코드는 기능별로 헬퍼 함수를 분리해 테스트 가능하게.
6. 한국어 docstring/주석 일관 유지.
7. 작업 디렉토리: 이 명세 파일의 프로젝트 루트.
8. 환경 가정: macOS Apple Silicon. PDF 파일 열기 기능은 macOS 전용.

산출물: 본 문서 섹션 1 (M13)과 섹션 2 (M14)의 모든 변경. 각 섹션 끝의 자가 검증 명령이 통과해야 완료.
시작 전 반드시 다음 파일을 먼저 읽고 현재 코드 컨벤션을 파악하세요:
- src/ui/streamlit_app.py
- src/rag/pipeline.py
- src/retrieval/vector_store.py
- src/retrieval/bm25.py
- src/llm/prompt.py
- src/parser/chunker.py
- src/config.py
```

---

## 섹션 1 — M13: 카테고리 필터 · PDF 미리보기 · 퀵 코드 모드

### 1.1 카테고리(문서) 필터 인프라

#### 1.1.1 `src/config.py` 수정

`PDF_SOURCES` 직후에 doc_short 정렬 상수 추가:

```python
DOC_SHORT_ORDER: list[str] = [source.doc_short for source in PDF_SOURCES]
# 예: ["심평원", "약관", "가이드북"]
```

#### 1.1.2 `src/retrieval/vector_store.py` 수정

`query`와 `query_with_filter` 메서드의 `where` 인자가 외부에서 주입 가능하도록 한다 (이미 있으면 호환 보존). 새 파라미터를 추가:

```python
def query(self, query_embedding, top_k: int,
          doc_filter: list[str] | None = None) -> list[Hit]: ...

def query_with_filter(self, query_embedding, filter_codes: list[str], top_k: int,
                      prefer_non_table: bool = True,
                      doc_filter: list[str] | None = None) -> list[Hit]: ...
```

`doc_filter`가 비어 있지 않으면 Chroma `where`에 다음 식을 합성:

```python
if doc_filter:
    where["doc_short"] = {"$in": list(doc_filter)}
```

기존 `filter_codes` 조건과 `$and`로 결합. Chroma가 단일 키만 허용하는 경우 `{"$and": [...]}` 컴포지션 사용.

#### 1.1.3 `src/retrieval/bm25.py` 수정

`Hit.metadata`에 최소한 `doc_short`가 포함되도록 한다. `BM25Index.build`가 메타를 보존하지 않는다면, build 시 `metadatas: list[dict]`를 함께 받아 인덱스에 저장하고 `query` 결과 Hit에 같이 반환하도록 확장한다. (기존 시그니처가 `texts`만 받는 경우, 후방 호환을 위해 `metadatas`는 옵션 인자로 추가하고 None일 때 빈 dict 채움.)

`scripts/ingest.py`도 BM25 build 호출에 metadata 전달하도록 수정.

> **주의:** BM25 인덱스 파일 포맷이 바뀌므로 기존 `data/index/bm25.pkl`은 재생성이 필요합니다. 명세 끝의 자가 검증 단계에 재인덱싱 명령이 들어갑니다.

#### 1.1.4 `src/rag/pipeline.py` 수정

`retrieve_hits`와 `answer`에 `doc_filter` 파라미터를 옵션으로 추가:

```python
def retrieve_hits(self, question: str, top_k: int | None = None,
                  doc_filter: list[str] | None = None) -> list[Hit]: ...

def answer(self, question: str, temperature: float = 0.2,
           top_k: int | None = None,
           doc_filter: list[str] | None = None) -> RagAnswer: ...
```

흐름:
- `doc_filter`가 None이거나 빈 리스트면 기존 동작 유지
- 값이 있으면 vector_store 호출 시 `doc_filter` 전달, BM25 결과에 대해서는 hit.metadata.doc_short post-filter
- 코드 라우팅(`query_with_filter`)도 `doc_filter` 동시 적용

#### 1.1.5 `src/ui/streamlit_app.py` 사이드바 추가

기존 `with st.sidebar:` 안 "대화 초기화" 버튼 위, 모델/Top-K/온도 슬라이더 아래에 다음 섹션 추가:

```python
st.divider()
st.markdown("**검색 대상 문서**")
selected_docs = []
for doc_short in config.DOC_SHORT_ORDER:
    if st.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
        selected_docs.append(doc_short)

if not selected_docs:
    st.warning("최소 1개 문서를 선택해주세요.")
```

`pipeline.answer`/`retrieve_hits` 호출부에 `doc_filter=selected_docs` 전달. 0개 선택 시 질문 처리를 차단(에러 메시지 + return).

### 1.2 PDF 페이지 미리보기 + 파일 열기

#### 1.2.1 새 모듈 `src/ui/pdf_view.py`

```python
"""PDF 페이지 렌더링 및 OS 파일 열기 헬퍼."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st


@st.cache_data(max_entries=64, show_spinner=False)
def render_pdf_page_png(pdf_path: str, page_no: int, dpi: int = 150) -> bytes:
    """PDF 1페이지를 PNG 바이트로 렌더링한다 (1-based page_no)."""
    import fitz  # pymupdf
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def open_pdf_in_native_viewer(pdf_path: Path) -> tuple[bool, str]:
    """OS 기본 PDF 뷰어로 파일을 연다. (성공 여부, 메시지)."""
    if not pdf_path.exists():
        return False, f"파일을 찾을 수 없습니다: {pdf_path}"
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(pdf_path)])
        return True, f"Preview에서 {pdf_path.name}을(를) 열었습니다."
    return False, "이 기능은 macOS에서만 동작합니다."
```

#### 1.2.2 `src/ui/streamlit_app.py`의 `render_sources` 수정

각 청크 카드 아래에 두 개의 버튼을 추가하고 미리보기 토글 상태를 세션에 저장한다.

```python
def render_sources(chunks, timing: dict | None = None) -> None:
    with st.expander("📄 출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{index}. {_source_title(chunk)}**")
            preview = chunk.text[:500] + ("..." if len(chunk.text) > 500 else "")
            st.text(preview)

            pdf_filename = chunk.metadata.get("pdf_filename")
            page_start = chunk.metadata.get("page_start")
            if pdf_filename and page_start is not None:
                pdf_path = config.ROOT_DIR / pdf_filename
                preview_key = f"_pdf_prev_{chunk.id}"

                col_prev, col_open = st.columns(2)
                with col_prev:
                    if st.button("📄 페이지 미리보기",
                                 key=f"prev_btn_{chunk.id}",
                                 use_container_width=True):
                        st.session_state[preview_key] = not st.session_state.get(preview_key, False)
                with col_open:
                    if st.button("📂 PDF 열기",
                                 key=f"open_btn_{chunk.id}",
                                 use_container_width=True):
                        ok, msg = open_pdf_in_native_viewer(pdf_path)
                        (st.success if ok else st.warning)(msg)

                if st.session_state.get(preview_key):
                    try:
                        img = render_pdf_page_png(str(pdf_path), int(page_start))
                        st.image(img, caption=f"{pdf_filename} p.{page_start}",
                                 use_container_width=True)
                    except Exception as exc:
                        st.error(f"페이지를 불러올 수 없습니다: {exc}")

            st.divider()
```

(`config.ROOT_DIR` 사용; `from src.ui.pdf_view import render_pdf_page_png, open_pdf_in_native_viewer` import 추가.)

### 1.3 퀵 코드 검색 모드

#### 1.3.1 검색 모드 라디오 (채팅 입력 영역 위)

`main()`에서 `st.chat_input` 호출 직전에 검색 모드 라디오를 둔다.

```python
SEARCH_MODES = ["일반 질의", "퀵 코드 검색", "약관 정형 검색"]
search_mode = st.radio("검색 모드", SEARCH_MODES,
                       horizontal=True, key="search_mode")
```

> M13 단계에서는 "약관 정형 검색"을 선택해도 "준비 중입니다" 안내만 출력하고 입력 차단. M14에서 채워 넣음.

#### 1.3.2 퀵 코드 모드 입력 폼

`search_mode == "퀵 코드 검색"`일 때 `st.chat_input` 대신 다음 폼을 노출:

```python
with st.form("quick_code_form", clear_on_submit=False):
    procedure_name = st.text_input("시술/수술명",
                                   placeholder="예: 식도조루술")
    col_a, col_b = st.columns(2)
    with col_a:
        opt_summary = st.checkbox("분류·점수·산정지침 요약", value=True)
    with col_b:
        opt_coverage = st.checkbox("실손 약관 기준 보상가능 여부", value=False)
    submitted = st.form_submit_button("코드 검색", type="primary",
                                       use_container_width=True)

if submitted and procedure_name.strip():
    _handle_quick_code(procedure_name.strip(), opt_summary, opt_coverage,
                       pipeline, model, temperature, session_id)
```

#### 1.3.3 새 모듈 `src/rag/quick_code.py`

```python
"""퀵 코드 검색 모드 — 시술명 입력으로 코드 추출."""

from __future__ import annotations

from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline, _hit_to_chunk

QUICK_CODE_TOP_K = 6

QUICK_SYSTEM_PROMPT = """당신은 보험사 직원의 시술/수술 코드 조회를 돕는 어시스턴트입니다.
아래 컨텍스트에서 입력된 시술명에 가장 정확히 일치하는 코드와 분류명을 우선 추출하세요.

## 출력 형식 (반드시 이 순서·라벨로)
[코드] <코드> — <분류명>
[분류 / 점수] <분류번호> / <점수>
{사용자 옵션에 따라 아래 줄 추가}
[산정지침 요약] <간단 요약 1-2문장>
[보상] <실손 약관 기준 보상 가능/불가/조건부> — <근거 한 줄>

## 규칙
- 코드를 찾을 수 없으면 "[코드] 정확한 코드를 찾지 못했습니다."를 출력하고 일반 모드 사용을 권유.
- 컨텍스트에 없는 정보는 추측하지 말고 해당 줄 자체를 생략.
- 출처는 본문 끝에 [출처: 문서명, p.페이지] 형식으로 붙이세요."""


def build_quick_code_prompt(procedure_name: str,
                            chunks: list[Chunk],
                            include_summary: bool,
                            include_coverage: bool) -> tuple[str, str]:
    """시스템 프롬프트와 유저 프롬프트를 조립한다."""
    sections = ["[코드] / [분류 / 점수] 두 줄은 항상 출력."]
    if include_summary:
        sections.append("[산정지침 요약] 줄 추가.")
    if include_coverage:
        sections.append("[보상] 줄 추가 — 실손 약관 컨텍스트가 있을 때만.")
    instructions = " ".join(sections)

    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        label = f"[{meta.get('doc_short', '')}] p.{meta.get('page_start', '?')}"
        blocks.append(f"[컨텍스트 {index}: {label}]\n{chunk.text}")
    context_block = "\n\n".join(blocks) if blocks else "제공된 컨텍스트 없음"

    user_prompt = (
        f"{context_block}\n\n[시술명] {procedure_name}\n"
        f"[지시] {instructions}\n"
        "답변 마지막에 [출처: 문서명, p.페이지]를 적으세요."
    )
    return QUICK_SYSTEM_PROMPT, user_prompt


def determine_doc_filter(include_coverage: bool) -> list[str]:
    """옵션에 따라 검색 대상 문서를 자동 결정한다 (사용자가 사이드바에서 추가 가능)."""
    return ["심평원", "약관"] if include_coverage else ["심평원"]


def run_quick_code(pipeline: RagPipeline,
                   procedure_name: str,
                   include_summary: bool,
                   include_coverage: bool,
                   temperature: float = 0.0):
    """퀵 코드 검색을 실행하고 (answer, chunks, timing)을 반환한다."""
    auto_filter = determine_doc_filter(include_coverage)
    hits = pipeline.retrieve_hits(procedure_name,
                                  top_k=QUICK_CODE_TOP_K,
                                  doc_filter=auto_filter)
    chunks = [_hit_to_chunk(h) for h in hits]
    system, user = build_quick_code_prompt(procedure_name, chunks,
                                           include_summary, include_coverage)
    answer = pipeline.llm.generate(user, system=system, temperature=temperature)
    return answer, chunks
```

(timing 구조는 기존 RagAnswer와 일관되게 `_handle_quick_code`에서 측정해 채움.)

#### 1.3.4 `_handle_quick_code` 헬퍼 (Streamlit 측)

`streamlit_app.py`에 추가. 사용자 사이드바 카테고리는 `selected_docs ∪ auto_filter`로 합산하되, 0개 선택 보호도 동일 적용. 응답·출처·로깅은 일반 모드와 동일 형식으로 `st.session_state.messages`에 누적해 히스토리·내보내기와 호환.

로깅: `EVENT_QUESTION`/`EVENT_ANSWER` 이벤트의 `details`에 `mode="quick_code"`, `options={"summary": bool, "coverage": bool}`, `selected_docs=...`를 추가.

### 1.4 M13 단위 테스트

신규/확장 테스트 파일:

| 파일 | 검사 항목 |
|---|---|
| `tests/test_pipeline.py` (확장) | `doc_filter=["약관"]` 전달 시 vector_store/BM25 호출의 doc_filter 인자 흐름 (mock) |
| `tests/test_vector_store.py` (확장) | `query(doc_filter=...)` 가 Chroma where 절에 `doc_short.$in` 추가하는지 |
| `tests/test_bm25.py` (확장) | `BM25Index.build(metadatas=...)` 후 hit.metadata.doc_short 접근 가능 / build·load 라운드트립 |
| `tests/test_quick_code.py` (신규) | `build_quick_code_prompt` 옵션 토글에 따른 instruction 변화, `determine_doc_filter` 분기 |
| `tests/test_pdf_view.py` (신규) | `render_pdf_page_png`가 PNG 시그니처 바이트로 시작 / `open_pdf_in_native_viewer`의 macOS 분기 (subprocess.Popen mock) |

### 1.5 M13 자가 검증

```bash
# 1. BM25 인덱스 재생성 (메타 추가)
python scripts/ingest.py --stage index

# 2. 단위 테스트
pytest -q

# 3. Streamlit 수동 확인
streamlit run src/ui/streamlit_app.py
```

수동 확인 체크리스트:
- [ ] 사이드바에 "검색 대상 문서" 체크박스 3개 표시
- [ ] 약관만 체크 후 일반 모드 질의 → 결과 청크 모두 doc_short="약관"
- [ ] 0개 체크 시 경고 표시되고 질의 차단
- [ ] 출처 expander 안에 "📄 페이지 미리보기" / "📂 PDF 열기" 버튼 노출
- [ ] 미리보기 클릭 시 해당 페이지 PNG 표시 (2초 이내)
- [ ] PDF 열기 클릭 시 macOS Preview에서 원본 PDF 열림
- [ ] 검색 모드 라디오 노출, "퀵 코드 검색" 선택 시 시술명 입력 폼 + 옵션 2개 체크박스
- [ ] 시술명 "식도조루술" + "분류·점수·산정지침 요약" ON → `[코드] Q2333 ...` 형식 답변
- [ ] 보상가능 여부 ON → 답변에 [보상] 줄 포함
- [ ] 일반 질의 모드의 기존 동작이 그대로 유지됨 (회귀 없음)
- [ ] `logs/chat_*.jsonl`에 `mode`/`options`/`selected_docs` 정보 포함

---

## 섹션 2 — M14: 약관 정형 검색 3종

전제: M13 완료 (카테고리 필터 인프라 / 검색 모드 라디오 골격).

### 2.1 시나리오 정의

| # | 모드 키 | 입력 | 동작 |
|---|---|---|---|
| ① | `coverage_judgment` | 진단코드 또는 시술명 (필수), 보장종목 다중 체크 [질병급여/질병비급여/3대비급여], 상황 메모(옵션) | "보상하지 않는 사항" 조항 우선 검색, 보장종목별 가/불가/조건부 명시 |
| ② | `clause_lookup` | 키워드 (필수), 조문번호 (옵션), 별표 포함 체크박스 | 조문 단위 retrieve, 본문 + 인용 |
| ③ | `keyword_search` | 키워드 (필수) | 시술명·용어 청크 우선, 동의어 보강 |

각 시나리오는 `doc_filter = ["약관"]`을 자동 적용하고, 사용자가 사이드바에서 추가 문서를 ON 한 경우 합집합. 0개 선택 시 차단.

### 2.2 새 모듈 `src/rag/insurance_form.py`

```python
"""약관 정형 검색 모드 — 3종 시나리오."""

from __future__ import annotations

from dataclasses import dataclass

from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline, _hit_to_chunk


COVERAGE_TOPICS = ["질병급여", "질병비급여", "3대비급여"]


@dataclass
class InsuranceFormInput:
    mode: str  # "coverage_judgment" | "clause_lookup" | "keyword_search"
    primary: str  # 진단코드/시술명/키워드
    coverage_topics: list[str] | None = None
    situation_note: str | None = None
    article_number: str | None = None
    include_appendix: bool = False


COVERAGE_SYSTEM_PROMPT = """당신은 실손의료보험 약관에 따라 보상가능 여부를 판정하는 어시스턴트입니다.
컨텍스트(약관)에서 '보상하지 않는 사항'과 '보상하는 사항' 조항을 모두 살펴
입력된 진단코드/시술명에 대해 선택된 보장종목별로 '보상 가능', '보상 불가', '조건부' 중 하나로 명확히 판정하세요.

## 출력 형식
- 질병급여 실손의료비: <판정> — <근거 1줄>
- 질병비급여 실손의료비: <판정> — <근거 1줄>
- 3대비급여 실손의료비: <판정> — <근거 1줄>

## 규칙
- 컨텍스트에 정보가 없는 보장종목은 "약관에서 확인되지 않습니다."라고 명시.
- 입력된 보장종목 외 항목은 출력에서 제외.
- 답변 마지막 줄에 자동 안내 부착: "본 답변은 검색 보조이며 최종 판정은 약관 원문과 사내 절차에 따릅니다."
- 출처는 [출처: 약관, 조문/별표, p.페이지]"""

CLAUSE_SYSTEM_PROMPT = """당신은 실손의료보험 약관 조문을 정확히 인용해 보여주는 어시스턴트입니다.
컨텍스트에서 키워드와 가장 일치하는 조문(또는 별표)을 찾아 다음 형식으로 답하세요.

## 출력 형식
[조문] <조문번호 / 제목>
[본문] <컨텍스트의 원문 인용 — 핵심 단락만, 임의 요약 금지>
[부가] <조건·예외 등이 있으면 항목별로>

## 규칙
- 본문은 컨텍스트의 원문을 그대로 인용. 윤문 금지.
- 조문번호가 입력으로 주어졌고 컨텍스트에 그 조문이 없으면 "해당 조문은 검색 결과에 없습니다."
- 출처: [출처: 약관, 조문번호, p.페이지]"""

KEYWORD_SYSTEM_PROMPT = """당신은 약관에서 키워드와 관련된 시술명·용어를 모아 보여주는 어시스턴트입니다.
컨텍스트에서 키워드와 직접 일치하거나 부분일치하는 항목들을 정리해 답하세요.

## 출력 형식
- <항목명>: <한 줄 요약 + 출처 페이지>

## 규칙
- 최대 6개 항목.
- 컨텍스트에 없으면 "검색 결과에 해당 키워드 항목이 없습니다."
- 답변 끝에 [출처: ...] 모음."""


def build_form_query(form: InsuranceFormInput) -> str:
    """모드별 retrieve 쿼리 문자열을 만든다."""
    if form.mode == "coverage_judgment":
        topics = " ".join(form.coverage_topics or [])
        situation = form.situation_note or ""
        return f"{form.primary} 보상하지 않는 사항 {topics} {situation}".strip()
    if form.mode == "clause_lookup":
        article = f"제{form.article_number}조" if form.article_number else ""
        appendix = "별표" if form.include_appendix else ""
        return f"{form.primary} {article} {appendix}".strip()
    if form.mode == "keyword_search":
        return form.primary
    raise ValueError(f"unknown mode: {form.mode}")


def build_form_prompt(form: InsuranceFormInput,
                      chunks: list[Chunk]) -> tuple[str, str]:
    """(system, user) 프롬프트 쌍을 반환한다."""
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        label = f"p.{meta.get('page_start', '?')}"
        blocks.append(f"[컨텍스트 {index}: {label}]\n{chunk.text}")
    context_block = "\n\n".join(blocks) if blocks else "제공된 컨텍스트 없음"

    if form.mode == "coverage_judgment":
        topics = ", ".join(form.coverage_topics or COVERAGE_TOPICS)
        note = f"\n[상황 메모] {form.situation_note}" if form.situation_note else ""
        user = (f"{context_block}\n\n[대상] {form.primary}\n"
                f"[보장종목] {topics}{note}\n"
                "선택된 보장종목별로 판정하세요.")
        return COVERAGE_SYSTEM_PROMPT, user

    if form.mode == "clause_lookup":
        extras = []
        if form.article_number:
            extras.append(f"조문번호 제{form.article_number}조")
        if form.include_appendix:
            extras.append("별표 포함")
        extras_str = ", ".join(extras) if extras else "조건 없음"
        user = (f"{context_block}\n\n[키워드] {form.primary}\n"
                f"[조건] {extras_str}\n조문 또는 별표를 인용하세요.")
        return CLAUSE_SYSTEM_PROMPT, user

    if form.mode == "keyword_search":
        user = (f"{context_block}\n\n[키워드] {form.primary}\n"
                "관련 항목을 정리해 보여주세요.")
        return KEYWORD_SYSTEM_PROMPT, user

    raise ValueError(form.mode)


def run_insurance_form(pipeline: RagPipeline,
                       form: InsuranceFormInput,
                       extra_doc_filter: list[str] | None = None,
                       temperature: float = 0.1):
    """약관 정형 검색을 실행하고 (answer, chunks)을 반환한다."""
    base_filter = ["약관"]
    if extra_doc_filter:
        merged = list(dict.fromkeys(base_filter + extra_doc_filter))
    else:
        merged = base_filter

    query = build_form_query(form)
    hits = pipeline.retrieve_hits(query, doc_filter=merged)
    chunks = [_hit_to_chunk(h) for h in hits]
    system, user = build_form_prompt(form, chunks)
    answer = pipeline.llm.generate(user, system=system, temperature=temperature)

    if form.mode == "coverage_judgment":
        disclaimer = "\n\n본 답변은 검색 보조이며 최종 판정은 약관 원문과 사내 절차에 따릅니다."
        if disclaimer.strip() not in answer:
            answer = answer.rstrip() + disclaimer
    return answer, chunks
```

### 2.3 Streamlit UI — 약관 정형 폼

`streamlit_app.py`에 다음 헬퍼를 추가하고 `search_mode == "약관 정형 검색"` 분기에서 호출:

```python
def render_insurance_form_panel(...):
    sub_mode = st.radio("시나리오", ["보상가능 여부 판정",
                                    "약관 조문 검색",
                                    "키워드/시술명 검색"],
                        horizontal=True, key="insurance_sub_mode")
    sub_key = {"보상가능 여부 판정": "coverage_judgment",
               "약관 조문 검색": "clause_lookup",
               "키워드/시술명 검색": "keyword_search"}[sub_mode]

    with st.form("insurance_form", clear_on_submit=False):
        if sub_key == "coverage_judgment":
            primary = st.text_input("진단코드 또는 시술명", placeholder="예: N39.3")
            topics = st.multiselect("보장종목",
                                    ["질병급여", "질병비급여", "3대비급여"],
                                    default=["질병급여", "질병비급여", "3대비급여"])
            note = st.text_area("상황 메모(옵션)", "")
        elif sub_key == "clause_lookup":
            primary = st.text_input("키워드", placeholder="예: 보상하지 않는 사항")
            col_a, col_b = st.columns(2)
            with col_a:
                article = st.text_input("조문번호(옵션, 숫자만)", "")
            with col_b:
                include_appx = st.checkbox("별표 포함", value=False)
        else:
            primary = st.text_input("키워드", placeholder="예: 도수치료")
        submitted = st.form_submit_button("검색", type="primary",
                                           use_container_width=True)
    # submitted 시 InsuranceFormInput 구성 → run_insurance_form 호출
```

### 2.4 자동 카테고리 매핑

`run_insurance_form`이 `["약관"]`을 강제. 사용자가 사이드바에서 추가로 [심평원] 또는 [가이드북]을 ON 한 경우 합집합 적용. 0개 선택 시 사이드바 경고 + 차단(이미 M13에서 처리).

### 2.5 로깅

`EVENT_QUESTION`/`EVENT_ANSWER` 이벤트에 다음 필드 추가:
- `mode = "insurance_form"`
- `sub_mode = "coverage_judgment" | "clause_lookup" | "keyword_search"`
- `form_input = {...}` (보안상 진단코드만 기록, 상황 메모는 200자 미리보기)
- `selected_docs = [...]`

### 2.6 M14 단위 테스트

| 파일 | 검사 |
|---|---|
| `tests/test_insurance_form.py` (신규) | `build_form_query`/`build_form_prompt`의 3개 모드 분기, `run_insurance_form`의 disclaimer 부착 |
| `tests/test_streamlit_app.py` (확장) | 약관 정형 모드 선택 → 서브 라디오 노출 (Streamlit testing API 사용 가능 범위 내) |

### 2.7 M14 자가 검증

```bash
pytest -q
streamlit run src/ui/streamlit_app.py
```

수동 체크:
- [ ] 검색 모드 "약관 정형 검색" 선택 시 서브 라디오 3개 표시
- [ ] 보상판정 폼: N39.3 + [질병급여 + 비급여 + 3대비급여] → 보장종목별 답변 분기
- [ ] 답변 하단에 자동 disclaimer 부착
- [ ] 조문 검색: "보상하지 않는 사항" → 조문 형식 답변
- [ ] 키워드 검색: "도수치료" → 항목 리스트
- [ ] 모든 정형 모드에서 출처는 약관에서만 (사이드바에 다른 문서 추가 ON 시 합산)
- [ ] 로그에 `sub_mode` 등 신규 필드 기록

---

## 섹션 3 — 명세 외 / 구현 금지

다음은 본 명세 범위 밖이며 임의 구현 금지:
- M15 (Top-K · 온도 자동 설정)
- 멀티페이지 PDF 미리보기에서 prev/next 점프
- 약관 정형 모드 답변에 PDF 하이라이트
- 카테고리별 RRF 가중치
- 멀티턴 컨텍스트 누적
- 신규 LLM 모델 도입(LLM 변경은 `.env`만으로 가능, 코드 변경 불요)

## 섹션 4 — 변경 파일 요약

| 파일 | M13 | M14 |
|---|---|---|
| `src/config.py` | 수정 (DOC_SHORT_ORDER) | — |
| `src/retrieval/vector_store.py` | 수정 (doc_filter) | — |
| `src/retrieval/bm25.py` | 수정 (metadata 보존) | — |
| `src/rag/pipeline.py` | 수정 (doc_filter 인자 흐름) | — |
| `scripts/ingest.py` | 수정 (BM25 build 시 메타) | — |
| `src/ui/pdf_view.py` | 신규 | — |
| `src/ui/streamlit_app.py` | 수정 (사이드바·미리보기·검색 모드·퀵 코드 폼) | 수정 (정형 폼) |
| `src/rag/quick_code.py` | 신규 | — |
| `src/rag/insurance_form.py` | — | 신규 |
| `tests/test_*` | 확장/신규 | 신규 |

## 섹션 5 — PR 보고서 양식

```
## M13 완료 보고
### 변경된 파일
- ...
### 자가 검증 결과
- pytest: NN passed
- 수동 체크리스트: [통과/실패]
### 이슈 및 특이사항
- ...

## M14 완료 보고
(동일 양식)
```
