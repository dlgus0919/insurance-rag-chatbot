"""Streamlit 챗 UI."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.ollama_client import OllamaClient
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.rag.pipeline import RagPipeline, _hit_to_chunk
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.reranker import build_reranker
from src.retrieval.vector_store import VectorStore

_DOC_SHORT_TO_FILENAME: dict[str, str] = {source.doc_short: source.path.name for source in config.PDF_SOURCES}


def _source_title(chunk) -> str:
    metadata = chunk.metadata
    doc_short = metadata.get("doc_short", "")
    filename = metadata.get("pdf_filename") or _DOC_SHORT_TO_FILENAME.get(doc_short, "")
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    page = f"p.{start}" if start == end or end is None else f"p.{start}~{end}"
    hierarchy = " > ".join(
        str(value)
        for value in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if value
    )
    parts = [f"[{doc_short}]" if doc_short else "", filename, page]
    header = " | ".join(part for part in parts if part)
    return f"{header}\n{hierarchy}" if hierarchy else header


def _format_timing(timing: dict) -> str:
    """응답 시간 딕셔너리를 UI 표시 문자열로 변환한다."""

    return (
        f"검색 {timing['retrieve_ms']:.0f}ms · 생성 {timing['llm_ms']:.0f}ms · "
        f"합계 {timing['total_ms'] / 1000:.1f}초"
    )


@st.cache_data(ttl=30)
def _get_available_models() -> list[str]:
    """Ollama에 설치된 권장 모델 목록을 반환한다."""

    installed = set(OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL).list_models())
    candidates = [model for model in config.OLLAMA_CANDIDATE_MODELS if model in installed]
    if config.OLLAMA_MODEL not in candidates:
        candidates.insert(0, config.OLLAMA_MODEL)
    return candidates if candidates else [config.OLLAMA_MODEL]


@st.cache_resource
def _load_heavy_components():
    """임베더·벡터스토어·BM25·Reranker를 한 번만 로드한다."""

    if not config.BM25_PATH.exists():
        raise RuntimeError("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, vector_store, bm25, reranker


@st.cache_resource
def _load_llm(model: str) -> OllamaClient:
    """선택된 모델 전용 OllamaClient를 생성한다."""

    llm = OllamaClient(config.OLLAMA_HOST, model)
    installed_models = llm.list_models()
    if not installed_models or model not in installed_models:
        raise RuntimeError(
            f"Ollama 서버에 연결할 수 없거나 모델 '{model}'이 설치되지 않았습니다.\n"
            f"설치 명령: `ollama pull {model}`\n"
            "또는 Ollama 데스크톱 앱을 실행하세요."
        )
    return llm


def _get_pipeline(model: str, top_k: int) -> RagPipeline:
    """캐시된 컴포넌트로 RagPipeline 객체를 조합한다."""

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


def render_sources(chunks, timing: dict | None = None) -> None:
    """답변 출처 청크를 expander 안에 표시한다."""

    with st.expander("📄 출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{index}. {_source_title(chunk)}**")
            preview = chunk.text[:500] + ("..." if len(chunk.text) > 500 else "")
            st.text(preview)
            st.divider()


def render_timing(timing: dict | None) -> None:
    """응답 시간을 caption으로 표시한다."""

    if timing:
        st.caption(_format_timing(timing))


def _stream_answer(pipeline: RagPipeline, question: str, temperature: float) -> tuple[str, list, dict]:
    """검색 후 LLM 스트리밍 답변을 렌더링하고 결과를 반환한다."""

    total_started = time.perf_counter()
    with st.spinner("관련 문서 검색 중..."):
        retrieve_started = time.perf_counter()
        hits = pipeline.retrieve_hits(question)
        chunks = [_hit_to_chunk(hit) for hit in hits]
        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

    prompt = build_user_prompt(question, chunks)
    llm_started = time.perf_counter()
    placeholder = st.empty()
    tokens: list[str] = []
    for token in pipeline.llm.generate_stream(prompt, system=SYSTEM_PROMPT, temperature=temperature):
        tokens.append(token)
        placeholder.markdown("".join(tokens) + "▌")

    answer = append_retrieved_source_citations("".join(tokens).strip(), chunks)
    placeholder.markdown(answer)
    llm_ms = (time.perf_counter() - llm_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000
    return answer, chunks, {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}


def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇 (Alpha)")
    st.title("보험 고시 문서 RAG 챗봇 (Alpha)")

    with st.sidebar:
        available_models = _get_available_models()
        default_index = available_models.index(config.OLLAMA_MODEL) if config.OLLAMA_MODEL in available_models else 0
        model = st.selectbox(
            "LLM 모델",
            available_models,
            index=default_index,
            help="exaone3.5:7.8b-instruct 권장 (한국어 처리 최적화)",
        )
        top_k = st.slider("Top-K", min_value=4, max_value=12, value=8)
        temperature = st.slider("온도", min_value=0.0, max_value=0.7, value=0.2, step=0.1)
        if st.button("대화 초기화"):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    try:
        pipeline = _get_pipeline(model, top_k)
    except RuntimeError as exc:
        st.error(str(exc))
        pipeline = None

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if message.get("chunks"):
                    render_sources(message["chunks"])
                render_timing(message.get("timing"))

    question = st.chat_input("질문을 입력하세요")
    if question and pipeline is not None:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                answer, chunks, timing = _stream_answer(pipeline, question, temperature)
            except RuntimeError as exc:
                st.error(str(exc))
                return
            render_sources(chunks)
            render_timing(timing)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "chunks": chunks,
                "timing": timing,
            }
        )


if __name__ == "__main__":
    main()
